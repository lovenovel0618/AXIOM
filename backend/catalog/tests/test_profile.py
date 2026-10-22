"""Real PROFILE, two-level receipts, cancellation and tenant-scope regressions."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from datetime import timedelta
from functools import partial
from io import BytesIO
import hashlib
import json
import sys
from collections.abc import Generator
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import skipUnless
from unittest.mock import patch
from uuid import UUID, uuid4
from django.contrib.auth.models import User
from django.db import DatabaseError, IntegrityError, connections, transaction
from django.http import JsonResponse
from catalog.http import error_response
from catalog.validation import ApiError
from django.test import Client, TransactionTestCase, override_settings
from catalog.budget import report_usage, usage_report, zero_usage
from catalog.ingest import Meter, complete_upload, ingest_tick
from catalog.models import Account, Dataset, DatasetVersion, EvidenceBundle, ProfileBinding, ResearchBudget, ResearchEvent, ResearchState, ResearchVersion, Reservation, RootBudget, SealRegistration, Tenant, Upload, UsageReceipt
from catalog.profile import close_state, profile_tick, recover_profile, reject, results
from catalog.research import create_research, create_version, research_for
from catalog.research_state import document_for, state_for
from catalog.services import actor_for, create_dataset, create_upload, put_upload
from catalog.tests.test_research import draft_data
from catalog.tests.test_sealing import LocalJournal
from ingestion.supervisor import inspect_research
from runtime.completion import finish
from runtime.control import cancel, claim, Lease
from runtime.models import RunEvent, RuntimeAttempt, RuntimeRun
from runtime.records import ControlError, db_now, lock_run
from sealing.journal import JournalStore
from sealing.types import Attestation

LIMITS = {"max_rows":100,"max_columns":8,"max_cell_utf8_bytes":4096,"max_decoded_bytes":65536,"max_parse_seconds":10}
MEMORY = 2*1024**3


def local_journal(journal: LocalJournal, endpoint: str, token: str) -> LocalJournal:
    """取代私有 RPC 的固定工廠；endpoint 與憑證仍被忽略但簽名相容。"""
    return journal


@contextmanager
def sealed_authority() -> Generator[None]:
    """以同一 authority 檔的 in-process journal 取代私有 RPC；封存 child 仍是真實子程序。"""
    root = TemporaryDirectory()
    try:
        base = Path(root.name)
        journal = LocalJournal(JournalStore(base/"events",base/"checkpoint"))
        with patch("catalog.sealing.JournalClient",partial(local_journal,journal)), override_settings(
                SEALING_ENABLED=True,SEALING_DATA=base/"data",SEALING_KEYS=base/"keys",
                JOURNAL_SOCKET="/var/lib/axiom/socket/journal.sock",JOURNAL_TOKEN="synthetic-journal-token-"+"0"*16):
            yield
    finally:
        root.cleanup()


@override_settings(INGEST_ENABLED=True,INGEST_LIMITS_JSON=json.dumps(LIMITS),PROFILE_ENABLED=True,PROFILE_LIMITS_JSON=json.dumps(LIMITS))
class ProfileTests(TransactionTestCase):
    def setUp(self) -> None:
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        override = self.settings(OBJECT_ROOT=Path(directory.name))
        override.enable()
        self.addCleanup(override.disable)
        user = User.objects.create(username=uuid4().hex,password="!")
        self.actor = Account.objects.create(user=user,tenant=Tenant.objects.create(name="profile-synthetic"))
        self.version = self.fixture()
        self.url = f'/api/v2/research-versions/{self.version.id}/validate'
        self.client.force_login(user)

    def fixture(self, invalid: bool = False) -> ResearchVersion:
        content = ('x,y\n'+''.join(f'{i},{2*i+1 if not invalid or i<9 else "private-final-marker"}\n' for i in range(10))).encode()
        with transaction.atomic():
            actor = actor_for(self.actor.user_id)
            dataset = Dataset.objects.get(pk=UUID(create_dataset(actor,{"name":"profile"})["id"]))
            upload = create_upload(actor,dataset,{"filename":"synthetic","format":"CSV","size_bytes":len(content),"sha256":hashlib.sha256(content).hexdigest()},"http://localhost")
            row = Upload.objects.get(pk=UUID(upload["id"]))
            put_upload(actor,row,upload["required_headers"]["X-Upload-Token"],BytesIO(content))
            run = complete_upload(actor,row,row.sha256,"complete")
        self.assertTrue(ingest_tick(str(actor.tenant_id),run["id"],0))
        version = DatasetVersion.objects.get(dataset=dataset)
        with transaction.atomic():
            actor = actor_for(self.actor.user_id)
            research = research_for(actor,UUID(create_research(actor,{"name":"profile"})["id"]))
            data = draft_data(version.id)
            data["budget"].update(cpu_seconds=100,wall_seconds=300,memory_bytes=MEMORY)
            document = create_version(actor,research,data)
        return ResearchVersion.objects.get(pk=UUID(document["id"]))

    def post(self, data: dict[str,object] | None = None, revision: int = 0, key: str = "profile") -> tuple[int,dict[str,object]]:
        def expose_database_error(problem: ApiError) -> JsonResponse:
            current_error = sys.exc_info()[1]
            if isinstance(current_error,DatabaseError):
                raise current_error
            return error_response(problem)
        with patch("catalog.http.error_response",side_effect=expose_database_error):
            response = self.client.post(self.url,json.dumps(data or {}),content_type="application/json",headers={"Idempotency-Key":key,"If-Control-Revision":str(revision)})
        return response.status_code,json.loads(response.content)

    def enqueue(self, data: dict[str,object] | None = None, revision: int = 0, key: str = "profile") -> UUID:
        status,response = self.post(data,revision,key)
        self.assertEqual(status,202,response)
        return UUID(str(response["id"]))

    def execute(self, identity: UUID) -> bool:
        def expose_database_error(binding: ProfileBinding, lease: Lease, meter: Meter, code: str) -> None:
            current_error = sys.exc_info()[1]
            if isinstance(current_error,DatabaseError):
                raise current_error
            reject(binding,lease,meter,code)
        with patch("catalog.profile.reject",side_effect=expose_database_error):
            return profile_tick(str(self.actor.tenant_id),str(identity),0)

    def lease(self, identity: UUID) -> Lease:
        result = claim(self.actor.tenant_id,identity,0,"test-supervisor")
        assert result is not None
        return result

    def terminate(self, lease: Lease, usage: object) -> None:
        report = usage_report(lease,usage)
        with transaction.atomic():
            lock_run(lease.tenant_id,lease.run_id)
            binding = ProfileBinding.objects.get(run_id=lease.run_id)
            state_for(binding.research_version)
            report_usage(lease,report,stopped=True)
            def failed(_row: RuntimeRun, code: str) -> None:
                binding.error_code = code
                binding.save(update_fields=["error_code"])
            finish(lease,usage,lambda:None,failed,"DEPENDENCY_UNAVAILABLE")
            close_state(binding)

    def expire(self, lease: Lease) -> None:
        row = RuntimeAttempt.objects.get(pk=lease.attempt_id)
        row.document["lease_expires_at"] = (db_now()-timedelta(seconds=1)).isoformat()
        row.save()
        recover_profile(lease.tenant_id,lease.run_id)

    def test_http_profile_to_private_reports_and_two_equal_usage_projections(self) -> None:
        identity = self.enqueue()
        queued = document_for(self.version)
        self.assertEqual((queued["status"],queued["revision"]),("VALIDATING",1))
        self.assertTrue(self.execute(identity))
        result = document_for(self.version)
        self.assertEqual((result["status"],result["revision"]),("DRAFT",2))
        self.assertIsNotNone(result["quality_report_id"],ProfileBinding.objects.get(run_id=identity).error_code)
        self.assertIsNotNone(result["structure_assessment_artifact_id"])
        research = ResearchBudget.objects.get(research_version=self.version)
        root = RootBudget.objects.get(run_id=identity)
        self.assertEqual(research.document["usage"],root.document["usage"])
        self.assertGreater(research.document["usage"]["cpu_seconds"],0)
        self.assertEqual(research.document["reservations"],[])
        self.assertEqual(Reservation.objects.get(root=root).state,"RELEASED")
        self.assertEqual(UsageReceipt.objects.count(),1)
        quality = self.client.get(f'/api/v2/artifacts/{result["quality_report_id"]}/content')
        body = json.loads(quality.content)
        self.assertEqual((body["quality"],body["readiness"]),("PASS","BLOCKED"))
        self.assertNotIn("final_test",body)
        run = self.client.get(f'/api/v2/runs/{identity}')
        self.assertEqual(json.loads(run.content)["status"],"SUCCEEDED")
        self.assertEqual(run["X-Usage-Status"],"MEASURED_UPPER_BOUND")
        self.assertFalse(self.execute(identity))
        self.assertEqual(UsageReceipt.objects.count(),1)

    def test_same_key_replay_ignores_old_revision_without_new_reservation(self) -> None:
        identity = self.enqueue()
        self.execute(identity)
        self.assertEqual(self.enqueue(),identity)
        self.assertEqual(ProfileBinding.objects.count(),1)
        self.assertEqual(Reservation.objects.count(),1)
        self.assertEqual(ResearchEvent.objects.count(),2)

    def test_revision_body_and_capability_preconditions(self) -> None:
        headers = {"Idempotency-Key":"key"}
        response = self.client.post(self.url,'{}',content_type="application/json",headers=headers)
        self.assertEqual(response.status_code,428)
        self.assertEqual(self.post(revision=1)[0],412)
        self.assertEqual(self.post({"unknown":1})[0],422)
        with self.settings(PROFILE_LIMITS_JSON='{}'):
            self.assertEqual(self.post()[0],503)
        self.assertFalse(ProfileBinding.objects.exists())
        self.assertEqual(ResearchBudget.objects.get(research_version=self.version).document["reservations"],[])

    def test_root_budget_too_small_and_research_consumption_across_roots(self) -> None:
        requested = {"cpu_seconds":70,"wall_seconds":100,"memory_bytes":MEMORY,"gpu_seconds":0,"tokens":0,"candidate_limit":0}
        insufficient = dict(requested,cpu_seconds=1)
        self.assertEqual(self.post({"run_budget":insufficient})[0],429)
        identity = self.enqueue({"run_budget":requested})
        lease = self.lease(identity)
        usage = zero_usage()
        usage.update(cpu_seconds=60,elapsed_wall_seconds=60,peak_memory_bytes=1024)
        self.terminate(lease,usage)
        requested["cpu_seconds"] = 60
        status,error = self.post({"run_budget":requested},revision=2,key="second")
        self.assertEqual((status,error["code"]),(429,"RESEARCH_BUDGET_EXHAUSTED"))
        self.assertEqual(ProfileBinding.objects.count(),1)
        self.assertEqual(ResearchBudget.objects.get(research_version=self.version).document["usage"]["cpu_seconds"],60)

    def test_memory_uses_active_reservations_not_historical_peak(self) -> None:
        lease = self.lease(self.enqueue())
        usage = zero_usage()
        usage.update(cpu_seconds=1,elapsed_wall_seconds=1,peak_memory_bytes=100000000)
        self.terminate(lease,usage)
        next_id = self.enqueue(revision=2,key="next")
        self.assertIsNotNone(next_id)
        account = ResearchBudget.objects.get(research_version=self.version)
        self.assertEqual(account.document["usage"]["peak_memory_bytes"],100000000)
        self.assertEqual(len(account.document["reservations"]),1)

    def test_usage_replay_conflicts_and_held_to_consumed(self) -> None:
        lease = self.lease(self.enqueue())
        usage = zero_usage()
        usage.update(cpu_seconds=3,elapsed_wall_seconds=4,peak_memory_bytes=1000)
        report = usage_report(lease,usage)
        self.assertTrue(report_usage(lease,report))
        self.assertFalse(report_usage(lease,report))
        root = RootBudget.objects.get(run_id=lease.run_id)
        self.assertEqual(Reservation.objects.get(root=root).held["cpu_seconds"],root.document["limit"]["cpu_seconds"]-3)
        later = usage_report(lease,dict(usage,cpu_seconds=5,elapsed_wall_seconds=7,peak_memory_bytes=1500),2)
        self.assertTrue(report_usage(lease,later))
        self.assertEqual(ResearchBudget.objects.get(research_version=self.version).document["usage"]["cpu_seconds"],5)
        conflicting = deepcopy(report)
        conflicting["cumulative_usage"]["cpu_seconds"] = 4
        with self.assertRaises(ControlError): report_usage(lease,conflicting)
        same_sequence = usage_report(lease,usage,2)
        with self.assertRaises(ControlError): report_usage(lease,same_sequence)
        self.assertEqual(UsageReceipt.objects.count(),2)

    def test_older_usage_is_recorded_without_reducing_projection(self) -> None:
        lease = self.lease(self.enqueue())
        usage = zero_usage()
        usage.update(cpu_seconds=5,elapsed_wall_seconds=5,peak_memory_bytes=1000)
        self.assertTrue(report_usage(lease,usage_report(lease,usage,2)))
        older = usage_report(lease,dict(usage,cpu_seconds=2,elapsed_wall_seconds=2),1)
        self.assertFalse(report_usage(lease,older))
        self.assertFalse(report_usage(lease,older))
        self.assertEqual(UsageReceipt.objects.count(),2)
        self.assertEqual(ResearchBudget.objects.get(research_version=self.version).document["usage"]["cpu_seconds"],5)

    def test_lost_attempt_holds_budget_until_authorized_late_stop(self) -> None:
        identity = self.enqueue()
        lease = self.lease(identity)
        self.expire(lease)
        loan = Reservation.objects.get(root__run_id=identity)
        self.assertEqual(loan.state,"UNCERTAIN")
        self.assertGreater(loan.held["cpu_seconds"],0)
        self.assertEqual(self.client.get(f'/api/v2/runs/{identity}')["X-Usage-Status"],"UNKNOWN")
        self.assertEqual(self.post(revision=2,key="blocked")[0],429)
        before = RunEvent.objects.filter(run_id=identity).count()
        usage = zero_usage()
        usage.update(cpu_seconds=2,elapsed_wall_seconds=2,peak_memory_bytes=1000)
        report_usage(lease,usage_report(lease,usage),stopped=True)
        self.assertEqual(RunEvent.objects.filter(run_id=identity).count(),before)
        self.assertEqual(self.client.get(f'/api/v2/runs/{identity}')["X-Usage-Status"],"MEASURED_UPPER_BOUND")
        self.assertEqual(self.post(revision=2,key="allowed")[0],202)

    def test_queue_timeout_releases_only_unstarted_usage(self) -> None:
        identity = self.enqueue()
        RuntimeRun.objects.filter(pk=identity).update(queue_deadline=db_now()-timedelta(seconds=1))
        recover_profile(self.actor.tenant_id,identity)
        self.assertEqual(Reservation.objects.get(root__run_id=identity).state,"RELEASED")
        self.assertEqual(document_for(self.version)["status"],"DRAFT")
        self.assertEqual(ResearchBudget.objects.get(research_version=self.version).document["usage"],zero_usage())
        self.assertEqual(self.client.get(f'/api/v2/runs/{identity}')["X-Usage-Status"],"NOT_STARTED")

    def test_queued_cancel_is_atomic_and_idempotent(self) -> None:
        identity = self.enqueue()
        path = f'/api/v2/runs/{identity}/cancel'
        headers = {"Idempotency-Key":"cancel","If-Control-Revision":"0"}
        response = self.client.post(path,'{}',content_type="application/json",headers=headers)
        self.assertEqual(response.status_code,202,response.content)
        self.assertEqual(json.loads(response.content)["status"],"CANCELLED")
        replay = self.client.post(path,'{}',content_type="application/json",headers=headers)
        self.assertEqual(replay.content,response.content)
        self.assertEqual(ResearchBudget.objects.get(research_version=self.version).document["usage"],zero_usage())
        self.assertEqual(document_for(self.version)["status"],"DRAFT")

    def test_cancel_during_real_child_discards_results_but_charges_usage(self) -> None:
        identity = self.enqueue()
        def parse_then_cancel(*args: object, **kwargs: object) -> dict[str,object]:
            from typing import Any, cast
            result = inspect_research(*cast(Any,args),**cast(Any,kwargs))
            row = RuntimeRun.objects.get(pk=identity)
            cancel(self.actor.tenant_id,identity,row.document["revision"])
            return result
        with patch("catalog.profile.inspect_research",side_effect=parse_then_cancel):
            self.execute(identity)
        self.assertEqual(RuntimeRun.objects.get(pk=identity).document["status"],"CANCELLED")
        self.assertEqual(Reservation.objects.get(root__run_id=identity).state,"RELEASED")
        self.assertIsNone(ProfileBinding.objects.get(run_id=identity).result_id)
        self.assertGreater(ResearchBudget.objects.get(research_version=self.version).document["usage"]["cpu_seconds"],0)

    def test_cancelled_lost_attempt_needs_stop_proof(self) -> None:
        identity = self.enqueue()
        lease = self.lease(identity)
        cancel(self.actor.tenant_id,identity,1)
        self.expire(lease)
        self.assertEqual(RuntimeRun.objects.get(pk=identity).document["status"],"CANCEL_REQUESTED")
        self.assertEqual(Reservation.objects.get(root__run_id=identity).state,"UNCERTAIN")
        usage = zero_usage()
        usage.update(cpu_seconds=2,elapsed_wall_seconds=2)
        report_usage(lease,usage_report(lease,usage),stopped=True)
        recover_profile(self.actor.tenant_id,identity)
        self.assertEqual(RuntimeRun.objects.get(pk=identity).document["status"],"CANCELLED")
        self.assertEqual(document_for(self.version)["status"],"DRAFT")

    def test_quality_failure_is_masked_and_never_ready(self) -> None:
        version = self.fixture(invalid=True)
        self.url = f'/api/v2/research-versions/{version.id}/validate'
        identity = self.enqueue()
        self.execute(identity)
        report_id = document_for(version)["quality_report_id"]
        response = self.client.get(f'/api/v2/artifacts/{report_id}/content')
        report = json.loads(response.content)
        self.assertEqual(report["quality"],"BLOCKED")
        self.assertIsNone(report["fit_summary"])
        self.assertNotIn(b'private-final-marker',response.content)
        self.assertNotIn("final_test",report)
        self.assertEqual(document_for(version)["status"],"DRAFT")

    def test_other_account_hides_profile_and_artifacts(self) -> None:
        identity = self.enqueue()
        self.execute(identity)
        report = document_for(self.version)["quality_report_id"]
        user = User.objects.create(username=uuid4().hex,password="!")
        Account.objects.create(user=user,tenant=self.actor.tenant)
        paths = [f'/api/v2/runs/{identity}',f'/api/v2/artifacts/{report}/content',f'/api/v2/runs/{identity}/events',f'/api/v2/research-versions/{self.version.id}/events']
        self.client.force_login(user)
        for path in paths:self.assertEqual(self.client.get(path).status_code,404)
        self.assertEqual(self.post()[0],404)

    def test_events_resume_and_control_header(self) -> None:
        identity = self.enqueue()
        self.execute(identity)
        response = self.client.get(f'/api/v2/research-versions/{self.version.id}')
        self.assertEqual(response["X-Control-Revision"],"2")
        path = f'/api/v2/research-versions/{self.version.id}/events'
        response = self.client.get(path,headers={"Last-Event-ID":f'RESEARCH:{self.version.id}:1'})
        self.assertEqual(response.status_code,200)
        self.assertTrue(response['Content-Type'].startswith('text/event-stream'))
        self.assertIn(b'"status": "DRAFT"',response.content)
        self.assertNotIn(b'"status": "VALIDATING"',response.content)
        self.assertEqual(self.client.get(path,headers={"Last-Event-ID":f'RUN:{identity}:1'}).status_code,400)
        run_events = self.client.get(f'/api/v2/runs/{identity}/events',headers={"Last-Event-ID":f'RUN:{identity}:1'})
        self.assertNotIn(b'RunQueued',run_events.content)
        self.assertIn(b'RunFinished',run_events.content)

    def test_parallel_same_key_creates_one_root_and_reservation(self) -> None:
        def invoke(_index: int) -> object:
            try:
                client = Client()
                client.force_login(self.actor.user)
                response = client.post(self.url,'{}',content_type="application/json",headers={"Idempotency-Key":"parallel","If-Control-Revision":"0"})
                self.assertEqual(response.status_code,202,response.content)
                return json.loads(response.content)["id"]
            finally: connections.close_all()
        with ThreadPoolExecutor(max_workers=4) as pool:
            self.assertEqual(len(set(pool.map(invoke,range(4)))),1)
        self.assertEqual(ProfileBinding.objects.count(),1)
        self.assertEqual(Reservation.objects.count(),1)

    def test_native_ledger_rewrites_and_fake_ready_are_rejected(self) -> None:
        identity = self.enqueue()
        self.execute(identity)
        account = ResearchBudget.objects.get(research_version=self.version)
        changed = deepcopy(account.document)
        changed["usage"]["cpu_seconds"] = 0
        for action in [lambda: ResearchBudget.objects.filter(pk=account.id).update(document=changed),lambda: UsageReceipt.objects.update(document={}),lambda: ResearchState.objects.update(status="READY"),lambda: Reservation.objects.update(state="HELD")]:
            with self.assertRaises(IntegrityError),transaction.atomic():action()

    def test_true_overrun_is_recorded_not_clipped_and_blocks_new_root(self) -> None:
        identity = self.enqueue()
        lease = self.lease(identity)
        usage = zero_usage()
        usage.update(cpu_seconds=101,elapsed_wall_seconds=101,peak_memory_bytes=MEMORY+1)
        self.terminate(lease,usage)
        account = ResearchBudget.objects.get(research_version=self.version)
        self.assertEqual(account.document["usage"]["cpu_seconds"],101)
        self.assertEqual(account.document["status"],"CLOSING")
        self.assertEqual(RuntimeRun.objects.get(pk=identity).document["stop_reason"],"BUDGET_EXHAUSTED")
        self.assertEqual(self.post(revision=2,key="overdrawn")[0],429)
        count = RunEvent.objects.filter(run_id=identity).count()
        late = usage_report(lease,dict(usage,cpu_seconds=102,elapsed_wall_seconds=102),2)
        self.assertTrue(report_usage(lease,late,stopped=True))
        self.assertEqual(ResearchBudget.objects.get(research_version=self.version).document["usage"]["cpu_seconds"],102)
        self.assertEqual(RunEvent.objects.filter(run_id=identity).count(),count)

    def test_decreasing_cumulative_usage_and_forged_worker_are_rejected(self) -> None:
        from dataclasses import replace
        lease = self.lease(self.enqueue())
        usage = zero_usage()
        usage.update(cpu_seconds=5,elapsed_wall_seconds=5,peak_memory_bytes=1000)
        report_usage(lease,usage_report(lease,usage))
        decreasing = usage_report(lease,dict(usage,cpu_seconds=4),2)
        with self.assertRaises(ControlError): report_usage(lease,decreasing)
        forged = replace(lease,worker_id="forged")
        next_report = usage_report(lease,dict(usage,cpu_seconds=6),2)
        with self.assertRaises(ControlError): report_usage(forged,next_report)
        self.assertEqual(UsageReceipt.objects.count(),1)
        self.assertEqual(ResearchBudget.objects.get(research_version=self.version).document["usage"]["cpu_seconds"],5)

    def test_result_callback_failure_rolls_back_partial_artifacts_but_bills_once(self) -> None:
        from catalog.models import Artifact
        identity = self.enqueue()
        before = Artifact.objects.count()
        def fail_after_result(binding: ProfileBinding, run: RuntimeRun, result: dict[str,object], execution: UUID, seal: Attestation | None = None, remaining: str = "") -> tuple[UUID,UUID | None]:
            results(binding,run,result,execution,seal,remaining)
            raise ApiError("DEPENDENCY_UNAVAILABLE",503)
        with patch("catalog.profile.results",side_effect=fail_after_result): self.execute(identity)
        self.assertEqual(Artifact.objects.count(),before)
        self.assertIsNone(ProfileBinding.objects.get(run_id=identity).result_id)
        self.assertEqual(RuntimeRun.objects.get(pk=identity).document["status"],"FAILED")
        self.assertEqual(UsageReceipt.objects.count(),1)
        self.assertEqual(Reservation.objects.get(root__run_id=identity).state,"RELEASED")

    def test_expired_child_result_is_discarded_but_late_cost_is_settled(self) -> None:
        identity = self.enqueue()
        def expire_after_child(*args: object, **kwargs: object) -> dict[str,object]:
            from typing import Any, cast
            result = inspect_research(*cast(Any,args),**cast(Any,kwargs))
            attempt = RuntimeAttempt.objects.get(run_id=identity)
            attempt.document["lease_expires_at"] = (db_now()-timedelta(seconds=1)).isoformat()
            attempt.save()
            recover_profile(self.actor.tenant_id,identity)
            return result
        with patch("catalog.profile.inspect_research",side_effect=expire_after_child): self.execute(identity)
        self.assertEqual(RuntimeRun.objects.get(pk=identity).document["status"],"FAILED")
        self.assertIsNone(ProfileBinding.objects.get(run_id=identity).result_id)
        self.assertEqual(Reservation.objects.get(root__run_id=identity).state,"RELEASED")
        self.assertEqual(UsageReceipt.objects.count(),1)
        self.assertEqual(ResearchEvent.objects.count(),2)

    def test_parallel_different_keys_cannot_create_two_active_roots(self) -> None:
        def invoke(index: int) -> int:
            try:
                client = Client()
                client.force_login(self.actor.user)
                response = client.post(self.url,'{}',content_type="application/json",headers={"Idempotency-Key":str(index),"If-Control-Revision":"0"})
                return response.status_code
            finally: connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(invoke,range(2))),[202,412])
        self.assertEqual(ProfileBinding.objects.count(),1)
        self.assertEqual(Reservation.objects.count(),1)

    def test_run_page_recovers_roots_and_rejects_wrong_scope(self) -> None:
        first = self.enqueue()
        self.execute(first)
        second = self.enqueue(revision=2,key="second")
        url = f"/api/v2/research-versions/{self.version.id}/runs"
        response = self.client.get(url,{"limit":1})
        self.assertEqual(response.status_code,200)
        page = response.json()
        self.assertEqual([row["id"] for row in page["items"]],[str(second)])
        resumed = self.client.get(url,{"limit":1,"cursor":page["next_cursor"]}).json()
        self.assertEqual([row["id"] for row in resumed["items"]],[str(first)])
        self.assertIsNone(resumed["next_cursor"])
        other = self.fixture()
        wrong = self.client.get(f"/api/v2/research-versions/{other.id}/runs",{"cursor":page["next_cursor"]})
        self.assertEqual(wrong.status_code,400)
        self.assertEqual(self.client.get(url,{"limit":201}).status_code,422)
        self.assertEqual(self.client.get(url,{"cursor":"bad"}).status_code,400)

    @skipUnless(sys.platform=="linux","formal sealing requires the Linux journal and child boundary")
    def test_formal_seal_projects_ready_without_exposing_final_rows(self) -> None:
        with sealed_authority():
            identity = self.enqueue()
            self.assertTrue(self.execute(identity))
            result = document_for(self.version)
            registration = SealRegistration.objects.get(research_version=self.version)
            self.assertEqual(result["status"],"READY")
            self.assertEqual(result["observation_split"]["sealed_test_id"],str(registration.sealed_test_id))
            self.assertEqual((registration.run_id,registration.authority_sequence),(identity,2))
            self.assertNotIn("final_observation_tokens",json.dumps(result))
            quality = self.client.get(f'/api/v2/artifacts/{result["quality_report_id"]}/content')
            body = json.loads(quality.content)
            self.assertEqual((body["quality"],body["readiness"],body["remaining"]),("PASS","READY",[]))
            self.assertNotIn("final_test",body)
            self.assertNotIn(b"sealed.sqlite3",quality.content)
            bundle = EvidenceBundle.objects.get(research_version=self.version)
            self.assertEqual(result["evidence_bundle_ids"],[str(bundle.id)])
            self.assertEqual(bundle.document["proof_artifact_ids"],[str(result["quality_report_id"]),str(result["structure_assessment_artifact_id"])])
            self.assertEqual(bundle.document["validation_ids"],[])
            response = self.client.get(f"/api/v2/evidence-bundles/{bundle.id}")
            self.assertEqual(response.status_code,200)
            self.assertEqual(response["X-Control-Revision"],"0")
            self.assertEqual(response["Cache-Control"],"no-store")
            self.assertEqual(json.loads(response.content),bundle.document)
            self.assertEqual(self.client.get(f"/api/v2/evidence-bundles/{uuid4()}").status_code,404)
            other = User.objects.create(username=uuid4().hex,password="!")
            Account.objects.create(user=other,tenant=self.actor.tenant)
            self.client.force_login(other)
            self.assertEqual(self.client.get(f"/api/v2/evidence-bundles/{bundle.id}").status_code,404)

    @skipUnless(sys.platform=="linux","formal sealing requires the Linux journal and child boundary")
    def test_blocked_sealing_keeps_draft_and_registers_nothing(self) -> None:
        with sealed_authority(), patch("catalog.profile.attach",return_value=(None,"EXPOSURE_RECOVERY_BLOCKED")):
            identity = self.enqueue()
            self.assertTrue(self.execute(identity))
        result = document_for(self.version)
        quality = self.client.get(f'/api/v2/artifacts/{result["quality_report_id"]}/content')
        self.assertEqual((result["status"],result["observation_split"]["sealed_test_id"]),("DRAFT",None))
        self.assertFalse(SealRegistration.objects.exists())
        self.assertFalse(EvidenceBundle.objects.exists())
        body = json.loads(quality.content)
        self.assertEqual((body["quality"],body["readiness"],body["remaining"]),("PASS","BLOCKED",["EXPOSURE_RECOVERY_BLOCKED"]))
