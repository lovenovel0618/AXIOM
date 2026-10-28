"""真實 PostgreSQL 與隔離子程序的 SEARCH 派送、扣帳、恢復與資料遮罩。"""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import BytesIO
import hashlib
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import UUID, uuid4
from django.contrib.auth.models import User
from django.db import connections, transaction, DatabaseError
from django.test import Client, TransactionTestCase, override_settings
from catalog.models import Account, Artifact, Candidate, Dataset, DatasetVersion, ResearchBudget, ResearchVersion, Reservation, RootBudget, Tenant, Upload
from catalog.ingest import complete_upload, ingest_tick
from catalog.research import create_research, create_version, research_for
from catalog.research_state import document_for
from catalog.search import search_tick, recover_search
from catalog.profile import enqueue_profile, profile_tick
from catalog.tests.test_sealing import sealed_authority
from catalog.services import actor_for, create_dataset, create_upload, put_upload
from catalog.tests.test_research import draft_data
from catalog.tests.test_profile import LIMITS as PROFILE_LIMITS, MEMORY

LIMITS = dict(PROFILE_LIMITS, max_parse_seconds=30)
from catalog.tasks import relay_search
from ingestion.research_protocol import decode_report
from ingestion.limits import ImportRejected
from mathematics.search import search, merge_reports
from mathematics.search_process import request_for
from runtime.models import InputSnapshot, RuntimeAttempt, RuntimeCheckpoint, RuntimeRun, RunEvent
from runtime.records import db_now

SEARCH_LIMITS = {"max_rows": 100, "max_strategy_seconds": 20, "max_candidates": 8}


@override_settings(INGEST_ENABLED=True, INGEST_LIMITS_JSON=json.dumps(LIMITS), SEARCH_ENABLED=True, SEARCH_LIMITS_JSON=json.dumps(SEARCH_LIMITS), PROFILE_ENABLED=True, PROFILE_LIMITS_JSON=json.dumps(LIMITS))
class SearchFixture(TransactionTestCase):
    def setUp(self) -> None:
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        override = self.settings(OBJECT_ROOT=Path(directory.name))
        override.enable()
        self.addCleanup(override.disable)
        user = User.objects.create(username=uuid4().hex,password="!")
        self.actor = Account.objects.create(user=user,tenant=Tenant.objects.create(name="profile-synthetic"))
        self.version = self.fixture()
        self.enterContext(sealed_authority())
        with transaction.atomic():
            profile = enqueue_profile(self.actor, self.version, {}, 0)
        self.assertTrue(profile_tick(str(self.actor.tenant_id), str(profile["id"]), 0))
        ready = document_for(self.version)
        quality = Artifact.objects.filter(pk=ready["quality_report_id"]).first() if ready["quality_report_id"] else None
        self.assertEqual(ready["status"], "READY", {"run": RuntimeRun.objects.get(pk=UUID(str(profile["id"]))).document,
            "quality": None if quality is None else quality.content})
        self.initial_usage = ResearchBudget.objects.get(research_version=self.version).document["usage"].copy()
        self.url = f'/api/v2/research-versions/{self.version.id}/runs'
        self.client.force_login(user)
        from catalog.http import error_response
        from catalog.validation import ApiError
        from django.http import JsonResponse
        def expose(problem: ApiError) -> JsonResponse:
            error = sys.exc_info()[1]
            if isinstance(error, DatabaseError):
                raise error
            return error_response(problem)
        expose_patch = patch("catalog.http.error_response", side_effect=expose)
        expose_patch.start()
        self.addCleanup(expose_patch.stop)

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
        completed = RuntimeRun.objects.get(pk=UUID(run["id"]))
        self.assertEqual(completed.document["status"], "SUCCEEDED", completed.document)
        version = DatasetVersion.objects.get(dataset=dataset)
        with transaction.atomic():
            actor = actor_for(self.actor.user_id)
            research = research_for(actor,UUID(create_research(actor,{"name":"profile"})["id"]))
            data = draft_data(version.id)
            data["budget"].update(cpu_seconds=100,wall_seconds=600,memory_bytes=MEMORY)
            document = create_version(actor,research,data)
        return ResearchVersion.objects.get(pk=UUID(document["id"]))

    def enqueue(self) -> UUID:
        response = self.client.post(self.url, '{"type":"SEARCH","seed":42}', content_type="application/json",
            headers={"Idempotency-Key": "search", "If-Control-Revision": "2"})
        self.assertEqual(response.status_code, 202, response.content)
        return UUID(response.json()["id"])

    def execute(self, identity: UUID, generation: int = 0) -> bool:
        return search_tick(str(self.actor.tenant_id), str(identity), generation)



class SearchTests(SearchFixture):
    def test_enqueue_tick_one_root_real_snapshots_and_usage(self) -> None:
        identity = self.enqueue()
        self.assertEqual(document_for(self.version)["status"], "QUEUED")
        snapshot = InputSnapshot.objects.get(run_id=identity)
        for artifact_id in (snapshot.task_input["payload"]["projection_artifact_id"], RuntimeRun.objects.get(pk=identity).document["input_artifact_id"]):
            artifact = Artifact.objects.get(pk=artifact_id)
            self.assertEqual(artifact.document["access_class"], "SEALED_DETAIL")
            self.assertEqual(self.client.get(f"/api/v2/artifacts/{artifact_id}/content").status_code, 404)
        self.assertTrue(self.execute(identity))
        run = RuntimeRun.objects.get(pk=identity)
        self.assertEqual((run.document["status"], run.document["phase"]), ("SUCCEEDED", "SEARCHING"))
        self.assertEqual(RuntimeRun.objects.filter(document__type="SEARCH").count(), 1)
        self.assertEqual(set(Candidate.objects.values_list("search_run_id", flat=True)), {identity})
        self.assertEqual(RuntimeCheckpoint.objects.filter(run=run).count(), 3)
        usage = run.document["budget_usage"]
        self.assertEqual(usage["candidates_generated"], 8)
        self.assertEqual(usage["candidates_accepted"], Candidate.objects.count())
        self.assertGreater(usage["cpu_seconds"], 0)
        self.assertEqual(ResearchBudget.objects.get(research_version=self.version).document["usage"]["cpu_seconds"], self.initial_usage["cpu_seconds"] + usage["cpu_seconds"])
        self.assertEqual(ResearchBudget.objects.get(research_version=self.version).document["status"], "CLOSING")
        self.assertEqual(Reservation.objects.get(root__run=run).state, "RELEASED")
        self.assertFalse(self.execute(identity))
        detail = self.client.get(f"/api/v2/runs/{identity}")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail["X-Usage-Status"], "MEASURED_UPPER_BOUND")
        self.assertTrue(all(event.document["producer_version"] == "t07-search-v1" for event in RunEvent.objects.filter(run=run)))
        checkpoint = RuntimeCheckpoint.objects.filter(run=run).latest("created_at")
        progress = checkpoint.document["strategy_progress"]
        self.assertNotIn("final_test", json.dumps(progress))
        self.assertEqual(progress["completed"], ["linear@1", "polynomial@1", "harmonic@1"])
        self.assertEqual(merge_reports(progress["reports"]), search(request_for(self.version.document, progress["projection"])))

    def test_revision_idempotency_and_missing_precondition(self) -> None:
        identity = self.enqueue()
        same = self.client.post(self.url, '{"type":"SEARCH","seed":42}', content_type="application/json", headers={"Idempotency-Key":"search", "If-Control-Revision":"2"})
        self.assertEqual(same.json()["id"], str(identity))
        different = self.client.post(self.url, '{"type":"SEARCH","seed":42}', content_type="application/json", headers={"Idempotency-Key":"different", "If-Control-Revision":"2"})
        self.assertEqual(different.status_code, 412, different.content)
        missing = self.client.post(self.url, '{"type":"SEARCH","seed":42}', content_type="application/json", headers={"Idempotency-Key":"missing"})
        self.assertEqual(missing.status_code, 428)
        self.assertEqual(RootBudget.objects.filter(run__document__type="SEARCH").count(), 1)

    def test_unsafe_integer_seed_is_rejected_without_root(self) -> None:
        response = self.client.post(self.url, json.dumps({"type":"SEARCH", "seed":2**60}), content_type="application/json", headers={"Idempotency-Key":"unsafe-seed", "If-Control-Revision":"2"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "INVALID_JSON")
        self.assertFalse(RuntimeRun.objects.filter(document__type="SEARCH").exists())

    def test_parallel_different_keys_only_one_revision_wins(self) -> None:
        def invoke(index: int) -> int:
            try:
                client = Client()
                client.force_login(self.actor.user)
                response = client.post(self.url, '{"type":"SEARCH","seed":42}', content_type="application/json", headers={"Idempotency-Key":str(index), "If-Control-Revision":"2"})
                return response.status_code
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(invoke, range(2))), [202, 412])
        self.assertEqual(RootBudget.objects.filter(run__document__type="SEARCH").count(), 1)

    def test_disabled_or_bad_capacity_has_no_side_effects(self) -> None:
        for settings in ({"SEARCH_ENABLED": False}, {"SEARCH_LIMITS_JSON": "{}"}, {"SEARCH_LIMITS_JSON": '{"max_rows":4097,"max_strategy_seconds":5,"max_candidates":8}'}):
            with self.settings(**settings):
                response = self.client.post(self.url, '{"type":"SEARCH","seed":42}', content_type="application/json", headers={"Idempotency-Key":"disabled", "If-Control-Revision":"2"})
                self.assertEqual(response.status_code, 503, response.content)
        self.assertFalse(RootBudget.objects.filter(run__document__type="SEARCH").exists())

    def test_budget_rejects_results_and_keeps_actual_candidate_usage(self) -> None:
        with self.settings(SEARCH_LIMITS_JSON=json.dumps(dict(SEARCH_LIMITS, max_candidates=1))):
            identity = self.enqueue()
            self.execute(identity)
        run = RuntimeRun.objects.get(pk=identity)
        self.assertEqual(run.document["status"], "FAILED")
        self.assertEqual(run.document["stop_reason"], "BUDGET_EXHAUSTED")
        self.assertFalse(Candidate.objects.exists())
        self.assertGreater(run.document["budget_usage"]["candidates_generated"], 1)
        self.assertEqual(document_for(self.version)["status"], "FAILED")

    def test_queue_timeout_fails_version_and_closes_ledgers(self) -> None:
        identity = self.enqueue()
        RuntimeRun.objects.filter(pk=identity).update(queue_deadline=db_now() - timedelta(seconds=1))
        recover_search(self.actor.tenant_id, identity)
        self.assertEqual(document_for(self.version)["status"], "FAILED")
        self.assertEqual(ResearchBudget.objects.get(research_version=self.version).document["status"], "CLOSED")
        self.assertEqual(Reservation.objects.get(root__run_id=identity).state, "RELEASED")

    def test_relay_and_tick_exclude_fit_and_offline_roots(self) -> None:
        identity = self.enqueue()
        with patch("catalog.tasks.app.send_task") as send:
            self.assertEqual(relay_search(), 1)
            self.assertEqual(send.call_args.kwargs["queue"], "search")
        self.execute(identity)
        fit = RuntimeRun.objects.filter(document__type="FIT").first()
        assert fit is not None
        self.assertFalse(self.execute(fit.id))
        with patch("catalog.tasks.app.send_task") as send:
            self.assertEqual(relay_search(), 0)
            send.assert_not_called()

    def test_queued_cancel_closes_state_without_results(self) -> None:
        identity = self.enqueue()
        response = self.client.post(f"/api/v2/runs/{identity}/cancel", '{}', content_type="application/json", headers={"Idempotency-Key":"cancel", "If-Control-Revision":"0"})
        self.assertEqual(response.status_code, 202, response.content)
        self.assertEqual(response.json()["status"], "CANCELLED")
        self.assertEqual(document_for(self.version)["status"], "CANCELLED")
        self.assertEqual(ResearchBudget.objects.get(research_version=self.version).document["status"], "CLOSED")
        self.assertFalse(self.execute(identity))

    def test_foreign_owner_cannot_enqueue_or_read_run(self) -> None:
        identity = self.enqueue()
        user = User.objects.create(username=uuid4().hex)
        Account.objects.create(user=user, tenant=self.actor.tenant)
        self.client.force_login(user)
        from catalog.http import error_response
        from catalog.validation import ApiError
        from django.http import JsonResponse
        def expose(problem: ApiError) -> JsonResponse:
            error = sys.exc_info()[1]
            if isinstance(error, DatabaseError):
                raise error
            return error_response(problem)
        expose_patch = patch("catalog.http.error_response", side_effect=expose)
        expose_patch.start()
        self.addCleanup(expose_patch.stop)
        self.assertEqual(self.client.get(f"/api/v2/runs/{identity}").status_code, 404)
        response = self.client.post(self.url, '{"type":"SEARCH","seed":42}', content_type="application/json", headers={"Idempotency-Key":"foreign", "If-Control-Revision":"2"})
        self.assertEqual(response.status_code, 404)

    def test_projection_protocol_rejects_final_nonfinite_and_wrong_counts(self) -> None:
        config = {"mode":"SEARCH_PROJECTION", "research":{"observation_split":{"fit":[0],"development":[1]}}}
        valid = {"kind":"SearchProjection", "precision_bits":53, "fit":[["0", "1"]], "development":[["1", "3"]]}
        self.assertEqual(decode_report(json.dumps({"status":"PASS", "report":valid}).encode(), config), valid)
        for bad in (dict(valid, final_test=[[2, 5]]), dict(valid, fit=[]), dict(valid, fit=[[float('nan'), 1]]), dict(valid, fit=[[True, 1]])):
            with self.assertRaises(ImportRejected):
                decode_report(json.dumps({"status":"PASS", "report":bad}).encode(), config)

    def test_checkpoint_resume_skips_completed_family_and_holds_unknown_cost(self) -> None:
        identity = self.enqueue()
        from catalog.search import run_strategy
        def crash_after_first(document: dict[str, object], projection: dict[str, object], index: int, seconds: int) -> dict[str, object]:
            if index == 1:
                raise SystemExit("synthetic worker crash")
            return run_strategy(document, projection, index, seconds)
        with patch("catalog.search.run_strategy", side_effect=crash_after_first), self.assertRaises(SystemExit):
            self.execute(identity)
        self.assertEqual(RuntimeCheckpoint.objects.filter(run_id=identity).count(), 1)
        attempt = RuntimeAttempt.objects.get(run_id=identity)
        attempt.document["lease_expires_at"] = (db_now() - timedelta(seconds=1)).isoformat()
        attempt.save()
        recover_search(self.actor.tenant_id, identity)
        RuntimeRun.objects.filter(pk=identity).update(available_at=db_now() - timedelta(seconds=1))
        with patch("catalog.search.run_strategy", wraps=run_strategy) as execute:
            self.assertTrue(self.execute(identity, 1))
            self.assertEqual([call.args[2] for call in execute.call_args_list], [1, 2])
        run = RuntimeRun.objects.get(pk=identity)
        self.assertEqual(run.document["status"], "SUCCEEDED")
        self.assertEqual(run.document["budget_usage"]["candidates_generated"], 8)
        self.assertEqual(ResearchBudget.objects.get(research_version=self.version).document["status"], "CLOSING")
        self.assertNotEqual(Reservation.objects.get(root__run_id=identity).state, "RELEASED")

    def test_result_transaction_rolls_back_partial_candidates_and_bills_usage(self) -> None:
        identity = self.enqueue()
        from catalog.search import persist_under
        def fail_after_persist(actor: Account, version: ResearchVersion, budget: ResearchBudget, run: RuntimeRun, report: dict[str, object]) -> None:
            persist_under(actor, version, budget, run, report)
            raise ApiError("DEPENDENCY_UNAVAILABLE", 503)
        from catalog.validation import ApiError
        with patch("catalog.search.persist_under", side_effect=fail_after_persist):
            self.execute(identity)
        self.assertFalse(Candidate.objects.exists())
        self.assertEqual(RuntimeRun.objects.get(pk=identity).document["status"], "FAILED")
        self.assertGreater(ResearchBudget.objects.get(research_version=self.version).document["usage"]["cpu_seconds"], 0)

    def test_cancel_during_strategy_rejects_results_and_charges_generated_candidates(self) -> None:
        identity = self.enqueue()
        from catalog.search import run_strategy
        from runtime.control import cancel
        def cancel_after_strategy(document: dict[str, object], projection: dict[str, object], index: int, seconds: int) -> dict[str, object]:
            response = self.client.get(f"/api/v2/runs/{identity}")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response["X-Usage-Status"], "UNKNOWN")
            report = run_strategy(document, projection, index, seconds)
            current = RuntimeRun.objects.get(pk=identity)
            cancel(self.actor.tenant_id, identity, current.document["revision"])
            return report
        with patch("catalog.search.run_strategy", side_effect=cancel_after_strategy):
            self.execute(identity)
        run = RuntimeRun.objects.get(pk=identity)
        self.assertEqual(run.document["status"], "CANCELLED")
        self.assertGreater(run.document["budget_usage"]["cpu_seconds"], 0)
        self.assertEqual(run.document["budget_usage"]["candidates_generated"], 3)
        self.assertFalse(Candidate.objects.exists())
        self.assertEqual(Reservation.objects.get(root__run=run).state, "RELEASED")

    def test_native_active_state_and_stopped_proof_are_guarded(self) -> None:
        identity = self.enqueue()
        self.execute(identity)
        from catalog.models import ResearchState, SearchAttemptStop
        from django.db import IntegrityError
        with self.assertRaises(IntegrityError), transaction.atomic():
            SearchAttemptStop.objects.update(created_at=db_now())
        state = ResearchState.objects.get(research_version=self.version)
        with self.assertRaises(IntegrityError), transaction.atomic():
            ResearchState.objects.filter(pk=state.pk).update(status="RUNNING", revision=state.revision + 1, active_run_id=None)

    def test_draft_cannot_enqueue_and_offline_root_cannot_enter_dispatch_control(self) -> None:
        draft = self.fixture()
        response = self.client.post(f"/api/v2/research-versions/{draft.id}/runs", '{"type":"SEARCH","seed":42}', content_type="application/json", headers={"Idempotency-Key":"draft-search", "If-Control-Revision":"0"})
        self.assertEqual(response.status_code, 409)
        from catalog.search_run import create
        with transaction.atomic():
            offline = create(self.actor, self.version, ResearchBudget.objects.get(research_version=self.version), "SEARCH")
        response = self.client.post(f"/api/v2/runs/{offline.id}/cancel", '{}', content_type="application/json", headers={"Idempotency-Key":"offline-cancel", "If-Control-Revision":"0"})
        self.assertEqual(response.status_code, 503)
        self.assertFalse(self.execute(offline.id))

    def test_known_stopped_retry_keeps_reservation_until_root_finishes(self) -> None:
        identity = self.enqueue()
        from catalog.search import run_strategy
        from runtime.records import ControlError
        def expire_between_families(document: dict[str, object], projection: dict[str, object], index: int, seconds: int) -> dict[str, object]:
            if index == 1:
                attempt = RuntimeAttempt.objects.get(run_id=identity)
                attempt.document["lease_expires_at"] = (db_now() - timedelta(seconds=1)).isoformat()
                attempt.save()
                raise ControlError("STALE_ATTEMPT")
            return run_strategy(document, projection, index, seconds)
        with patch("catalog.search.run_strategy", side_effect=expire_between_families):
            self.execute(identity)
        self.assertEqual(RuntimeRun.objects.get(pk=identity).document["status"], "QUEUED")
        self.assertEqual(Reservation.objects.get(root__run_id=identity).state, "HELD")
        self.assertEqual(RootBudget.objects.get(run_id=identity).document["status"], "OPEN")
        RuntimeRun.objects.filter(pk=identity).update(available_at=db_now() - timedelta(seconds=1))
        self.execute(identity, 1)
        run = RuntimeRun.objects.get(pk=identity)
        self.assertEqual(run.document["status"], "SUCCEEDED")
        self.assertEqual(run.document["budget_usage"]["candidates_generated"], 8)
        self.assertEqual(Reservation.objects.get(root__run_id=identity).state, "RELEASED")

    def test_closed_research_accepts_late_overrun_without_reopening(self) -> None:
        identity = self.enqueue()
        self.execute(identity)
        # 模擬全部固定最終評估已結算的 CLOSED 前置條件；本測試只驗遲到扣帳不重新開帳。
        account = ResearchBudget.objects.get(research_version=self.version)
        account.document["status"] = "CLOSED"
        account.save(update_fields=["document"])
        from catalog.budget import report_usage, usage_report
        from runtime.control import Lease
        attempt = RuntimeAttempt.objects.get(run_id=identity)
        lease = Lease(self.actor.tenant_id, identity, attempt.id, attempt.generation,
            attempt.document["root_epoch_at_dispatch"], attempt.document["worker_id"])
        usage = attempt.document["actual_usage"].copy()
        usage["cpu_seconds"] += 101
        sequence = attempt.document["usage_sequence"] + 1
        count = RunEvent.objects.filter(run_id=identity).count()
        self.assertTrue(report_usage(lease, usage_report(lease, usage, sequence), stopped=True))
        account = ResearchBudget.objects.get(research_version=self.version)
        self.assertEqual(account.document["status"], "CLOSED")
        self.assertEqual(account.document["usage"]["cpu_seconds"], self.initial_usage["cpu_seconds"] + usage["cpu_seconds"])
        self.assertEqual(RunEvent.objects.filter(run_id=identity).count(), count)

    def test_real_search_freeze_and_final_evaluation_close_research_without_reopening(self) -> None:
        from catalog.artifacts import register
        from catalog.final_evaluation import acquire
        from catalog.final_evaluator import validate_tick
        from catalog.freezing import freeze_candidates
        from catalog.models import FrozenCandidate, Provenance
        from runtime.models import FinalEvaluationSlot
        identity = self.enqueue()
        self.execute(identity)
        self.assertEqual(ResearchBudget.objects.get(research_version=self.version).document["status"], "CLOSING")
        candidate = Candidate.objects.filter(search_run_id=identity).order_by("development_rank").first()
        assert candidate is not None
        from catalog.fit import attach, fit_tick
        from catalog.models import FitRun
        fit = FitRun.objects.get(pk=UUID(candidate.document["fit_run_ids"][0]))
        with self.settings(FIT_ENABLED=True, FIT_LIMITS_JSON=json.dumps(LIMITS)):
            attach(self.actor.tenant_id, fit.run_id)
            self.assertTrue(fit_tick(str(self.actor.tenant_id), str(fit.run_id), 0))
        with transaction.atomic():
            source = Provenance.objects.get(pk=self.version.provenance_id)
            plan_id = uuid4()
            plan = register(self.actor, self.version.dataset_version, plan_id,
                {"id":str(plan_id), "tenant_id":str(self.actor.tenant_id), "research_version_id":str(self.version.id), "purpose":self.version.document["purpose"]},
                source, research_version=self.version)
            submission = freeze_candidates(self.actor, self.version, [candidate.id], plan.id, document_for(self.version)["revision"])
            frozen = FrozenCandidate.objects.get(pk=UUID(submission.document["frozen_candidate_ids"][0]))
            slot, created = acquire(self.actor, submission, frozen)
            self.assertTrue(created)
        self.assertEqual(ResearchBudget.objects.get(research_version=self.version).document["status"], "CLOSING")
        with self.settings(VALIDATE_ENABLED=True):
            self.assertTrue(validate_tick(str(self.actor.tenant_id), str(slot.run_id), 0))
        self.assertEqual(RuntimeRun.objects.get(pk=slot.run_id).document["status"], "SUCCEEDED")
        self.assertEqual(FinalEvaluationSlot.objects.get(pk=slot.id).status, "COMPLETED")
        self.assertEqual(ResearchBudget.objects.get(research_version=self.version).document["status"], "CLOSED")
