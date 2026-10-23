"""最終評估槽位服務層：業務鍵 insert-on-conflict、成員資格、單向結算與提交狀態流。

Service-level FinalEvaluationSlot acquisition, eligibility and single-forward settlement."""
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from fractions import Fraction
import hashlib
from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID, uuid4
from django.contrib.auth.models import User
from django.db import IntegrityError, connection, connections, transaction
from django.test import TransactionTestCase, override_settings
from catalog.artifacts import register as register_artifact
from catalog.candidates import persist
from catalog.final_evaluation import acquire, settle
from catalog.final_manifest import documents, limit_for
from catalog.freezing import frozen_candidate, frozen_submission
from catalog.ingest import complete_upload, ingest_tick
from catalog.models import Account, Artifact, Candidate, Dataset, DatasetVersion, FitRun, FrozenCandidate, FrozenSubmission, Provenance, RepresentationSpec, ResearchBudget, ResearchVersion, SealRegistration, Tenant, Upload
from catalog.research import create_research, create_version, research_for
from catalog.services import actor_for, create_dataset, create_upload, put_upload
from catalog.tasks import relay_ingest, relay_profile
from catalog.tests.test_research import CONTENT, LIMITS, draft_data
from catalog.validation import ApiError
from mathematics.search import Domain, Request, Variable, search
from runtime.contracts import identity_hash, validate
from runtime.control import enqueue
from runtime.models import FinalEvaluationSlot, RunEvent, RuntimeAttempt, RuntimeRun
from runtime.records import ControlError, snapshot_for

DIMENSIONLESS = (0,) * 7
FINAL_BUDGET = {"cpu_seconds": 120, "gpu_seconds": 0, "wall_seconds": 600, "tokens": 0,
    "candidate_limit": 10, "memory_bytes": 4 * 1024**3}


def request(fit: list[tuple[float, float]], development: list[tuple[float, float]]) -> Request:
    """固定域與無量綱單位的離線請求；槽位測試不觸及 final_test 內容。"""
    return Request(Variable("x", DIMENSIONLESS), DIMENSIONLESS, Domain(Fraction(-1000), Fraction(1000), True, True),
        tuple(fit), tuple(development))


def enforce(action: Callable[[], object]) -> None:
    """在單一交易內執行資料庫變動；觸發器或約束拒絕時拋 IntegrityError。"""
    with transaction.atomic():
        action()
        connection.check_constraints()


@override_settings(INGEST_ENABLED=True, INGEST_LIMITS_JSON=json.dumps(LIMITS), PROFILE_ENABLED=False)
class FinalEvaluationTests(TransactionTestCase):
    def setUp(self) -> None:
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        override = self.settings(OBJECT_ROOT=Path(directory.name))
        override.enable()
        self.addCleanup(override.disable)
        self.actor = self.account(Tenant.objects.create(name="final-evaluation"))
        self.other = self.account(Tenant.objects.create(name="final-evaluation-other"))
        self.version = self.fixture()
        self.budget = ResearchBudget.objects.get(research_version=self.version)
        self.candidates = self.store()
        self.frozen = self.freeze_one(self.candidates[0])
        self.outsider = self.freeze_one(self.candidates[1])
        self.submission = self.submit([self.frozen])

    def account(self, tenant: Tenant) -> Account:
        user = User.objects.create(username=uuid4().hex, password="!")
        return Account.objects.create(user=user, tenant=tenant)

    def fixture(self) -> ResearchVersion:
        """以真實匯入建立資料與研究版本，不以偽造 fixture 代替來源鏈。"""
        with transaction.atomic():
            actor = actor_for(self.actor.user_id)
            dataset = Dataset.objects.get(pk=UUID(create_dataset(actor, {"name": "final-evaluation"})["id"]))
            upload = create_upload(actor, dataset, {"filename": "synthetic", "format": "CSV", "size_bytes": len(CONTENT),
                "sha256": hashlib.sha256(CONTENT).hexdigest()}, "http://localhost")
            row = Upload.objects.get(pk=UUID(upload["id"]))
            put_upload(actor, row, upload["required_headers"]["X-Upload-Token"], BytesIO(CONTENT))
            run = complete_upload(actor, row, row.sha256, "complete")
        self.assertTrue(ingest_tick(str(actor.tenant_id), run["id"], 0))
        version_row = DatasetVersion.objects.get(dataset=dataset)
        with transaction.atomic():
            actor = actor_for(self.actor.user_id)
            research = research_for(actor, UUID(create_research(actor, {"name": "final-evaluation"})["id"]))
            data = draft_data(version_row.id)
            data["budget"] = dict(FINAL_BUDGET)
            document = create_version(actor, research, data)
        return ResearchVersion.objects.get(pk=UUID(document["id"]))

    def store(self) -> list[Candidate]:
        """精確線性資料的離線報告，只含 fit／development。"""
        fit = [(float(index), float(2 * index + 1)) for index in range(6)]
        development = [(float(index), float(2 * index + 1)) for index in range(6, 8)]
        with transaction.atomic():
            return persist(self.actor, self.version, self.budget, search(request(fit, development)))

    def freeze_one(self, candidate: Candidate) -> FrozenCandidate:
        fit = FitRun.objects.get(pk=UUID(candidate.document["fit_run_ids"][0]))
        representation = RepresentationSpec.objects.get(pk=fit.representation_artifact_id)
        with transaction.atomic():
            return frozen_candidate(self.actor, candidate, fit, candidate.equation_version, representation, self.version)

    def register_plan(self) -> Artifact:
        content = {"id": str(uuid4()), "tenant_id": str(self.version.tenant_id),
            "research_version_id": str(self.version.id), "purpose": self.version.document["purpose"]}
        source = Provenance.objects.get(pk=self.version.provenance_id, tenant_id=self.version.tenant_id)
        return register_artifact(self.actor, self.version.dataset_version, UUID(str(content["id"])), content, source, research_version=self.version)

    def register_seal(self) -> SealRegistration:
        existing = SealRegistration.objects.filter(research_version=self.version).first()
        if existing is not None:
            return existing
        run = RuntimeRun.objects.filter(document__type="INGEST").order_by("id").first()
        self.assertIsNotNone(run)
        return SealRegistration.objects.create(tenant_id=self.version.tenant_id, research_version=self.version, run=run,
            sealed_test_id=uuid4(), source_sha256="1" * 64, protocol_hash="2" * 64, authority_epoch=uuid4(),
            authority_sequence=1, attestation_hash="3" * 64, available=True)

    def submit(self, frozen: list[FrozenCandidate]) -> FrozenSubmission:
        artifact = self.register_plan()
        self.register_seal()
        with transaction.atomic():
            return frozen_submission(self.actor, self.version, frozen, artifact)

    def test_first_dispatch_creates_a_pending_slot_and_advances_the_submission(self) -> None:
        slot, created = acquire(self.actor, self.submission, self.frozen)
        self.assertTrue(created)
        validate(slot.document, "runtime-v2.schema.json", "FinalEvaluationSlot")
        self.assertEqual((slot.status, slot.validation_run_id), ("PENDING", None))
        self.assertEqual((slot.run_id, slot.metric_version), (UUID(str(slot.document["run_id"])), "2.0"))
        self.assertEqual((slot.submission_id, slot.frozen_candidate_id), (self.submission.id, self.frozen.id))
        validate(FinalEvaluationSlot.objects.get(pk=slot.id).document, "runtime-v2.schema.json", "FinalEvaluationSlot")
        stored = FrozenSubmission.objects.get(pk=self.submission.id)
        self.assertEqual((stored.status, stored.document["status"]), ("EVALUATING", "EVALUATING"))

    def test_dispatch_creates_one_final_only_validate_root(self) -> None:
        slot, created = acquire(self.actor, self.submission, self.frozen)
        self.assertTrue(created)
        run = RuntimeRun.objects.get(pk=slot.run_id)
        validate(run.document, "runtime-v2.schema.json", "RunRecord")
        self.assertEqual((run.document["type"], run.document["dispatch_stage"]), ("VALIDATE", "FINAL_ONLY"))
        self.assertEqual((run.document["status"], run.control_only), ("QUEUED", False))
        self.assertEqual((run.document["is_root"], run.document["parent_run_id"]), (True, None))
        self.assertEqual(run.document["root_run_id"], str(run.id))
        self.assertEqual(run.document["research_version_id"], str(self.version.id))
        self.assertEqual(run.document["research_budget_account_id"], str(self.budget.id))
        self.assertEqual(run.document["equation_version_id"], str(self.frozen.equation_version_id))
        self.assertFalse(RuntimeAttempt.objects.filter(run=run).exists())
        snapshot = snapshot_for(run)
        self.assertEqual(snapshot.content_hash, identity_hash([snapshot.task_input, snapshot.execution, snapshot.budget]))
        self.assertEqual((snapshot.task_input["type"], snapshot.task_input["payload"]["split_role"]), ("VALIDATE", "FINAL_TEST"))
        self.assertEqual(snapshot.task_input["payload"]["frozen_candidate_id"], str(self.frozen.id))
        self.assertEqual(snapshot.task_input["payload"]["submission_id"], str(self.submission.id))
        self.assertEqual(snapshot.execution["semantic_profile_hash"], identity_hash(self.version.document["semantic_profile"]))
        self.assertEqual(snapshot.execution["retry_policy"]["max_attempts"], 1)
        events = RunEvent.objects.filter(run=run).order_by("sequence")
        self.assertEqual([event.document["event_type"] for event in events], ["RunQueued"])
        self.assertEqual(events[0].document["producer_version"], "t07-validate-v1")

    def test_final_bindings_refuse_non_final_test_manifests(self) -> None:
        """最終評估 root 只接受凍結後的 FINAL_TEST 身分，冒充探索或重試必須在入庫前被拒。"""
        account = ResearchBudget.objects.get(pk=self.budget.id)
        for case in ("stage", "role", "split", "retry"):
            with self.subTest(case=case):
                record, task, execution, budget = documents(self.actor, self.version, account, limit_for(account), self.submission, self.frozen)
                if case == "stage":
                    record["dispatch_stage"] = "SEARCH_OPEN"
                elif case == "role":
                    task["payload"]["split_role"] = "FIT"
                elif case == "split":
                    task["observation_split_id"] = str(uuid4())
                else:
                    execution["retry_policy"]["max_attempts"] = 2
                with self.assertRaisesRegex(ValueError, "FINAL TEST binding mismatch"):
                    enqueue(self.actor.tenant_id, record, task, execution, budget, control_only=False)
                self.assertFalse(RuntimeRun.objects.filter(document__type="VALIDATE").exists())

    def test_final_root_must_stay_a_root(self) -> None:
        """最終評估仍走最小權威入口：非 root 的 VALIDATE 一律 FEATURE_DISABLED，不建立任何 root。"""
        account = ResearchBudget.objects.get(pk=self.budget.id)
        record, task, execution, budget = documents(self.actor, self.version, account, limit_for(account), self.submission, self.frozen)
        record["is_root"] = False
        with self.assertRaisesRegex(ControlError, "FEATURE_DISABLED"):
            enqueue(self.actor.tenant_id, record, task, execution, budget, control_only=False)
        self.assertFalse(RuntimeRun.objects.filter(document__type="VALIDATE").exists())

    def test_manifest_rejects_a_candidate_outside_the_frozen_submission(self) -> None:
        """候選不在凍結提交的固定排序內時，manifest 產生階段即 Fail-Closed，不建立任何 root。"""
        account = ResearchBudget.objects.get(pk=self.budget.id)
        with self.assertRaises(ApiError) as denied:
            documents(self.actor, self.version, account, limit_for(account), self.submission, self.outsider)
        self.assertEqual(denied.exception.code, "FIT_REFERENCE_MISMATCH")
        self.assertFalse(RuntimeRun.objects.filter(document__type="VALIDATE").exists())

    def test_final_limit_requests_the_full_reservation(self) -> None:
        """最終評估的固定預留需求來自 manifest 常數，不被較小的假預留超賣研究容量。"""
        limit = limit_for(ResearchBudget.objects.get(pk=self.budget.id))
        self.assertEqual(limit["cpu_seconds"], 60)
        self.assertEqual(limit["wall_seconds"], 300)
        self.assertEqual(limit["memory_bytes"], 2 * 1024**3)

    def test_final_limit_refuses_undersized_or_spent_research_budgets(self) -> None:
        """研究設定限額或剩餘不足以涵蓋固定需求時，各自回穩定代碼而不是縮小預留。"""
        account = ResearchBudget.objects.get(pk=self.budget.id)
        account.document = dict(account.document) | {"limit": dict(FINAL_BUDGET) | {"cpu_seconds": 1}}
        with self.assertRaises(ApiError) as configured:
            limit_for(account)
        self.assertEqual(configured.exception.code, "RUN_BUDGET_EXHAUSTED")
        account.document = dict(account.document) | {"limit": dict(FINAL_BUDGET), "usage": dict(account.document["usage"]) | {"cpu_seconds": 10**6}}
        with self.assertRaises(ApiError) as spent:
            limit_for(account)
        self.assertEqual(spent.exception.code, "RESEARCH_BUDGET_EXHAUSTED")

    def test_dispatch_root_is_invisible_to_the_ingest_and_profile_relays(self) -> None:
        slot, _created = acquire(self.actor, self.submission, self.frozen)
        self.assertEqual((relay_ingest(), relay_profile()), (0, 0))
        run = RuntimeRun.objects.get(pk=slot.run_id)
        self.assertEqual((run.document["status"], run.document["lease_generation"]), ("QUEUED", 0))
        self.assertIsNone(run.last_polled_at)

    def test_repeated_dispatch_reads_back_the_same_run(self) -> None:
        first, first_created = acquire(self.actor, self.submission, self.frozen)
        second, second_created = acquire(self.actor, self.submission, self.frozen)
        self.assertTrue(first_created)
        self.assertFalse(second_created)
        self.assertEqual((first.id, second.id), (first.id, first.id))
        self.assertEqual(second.run_id, first.run_id)
        self.assertEqual(FinalEvaluationSlot.objects.count(), 1)
        self.assertEqual(RuntimeRun.objects.filter(document__type="VALIDATE").count(), 1)

    def test_parallel_dispatch_keeps_one_slot_and_one_run(self) -> None:
        def compete(_index: int) -> tuple[bool, UUID]:
            try:
                slot, created = acquire(self.actor, self.submission, self.frozen)
                return created, slot.run_id
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=4) as pool:
            outcomes = list(pool.map(compete, range(4)))
        self.assertEqual(sum(created for created, _run in outcomes), 1)
        self.assertEqual(len({str(run) for _created, run in outcomes}), 1)
        self.assertEqual(FinalEvaluationSlot.objects.count(), 1)
        self.assertEqual(RuntimeRun.objects.filter(document__type="VALIDATE").count(), 1)

    def test_two_members_hold_independent_slots(self) -> None:
        pair = self.submit([self.frozen, self.outsider])
        first, first_created = acquire(self.actor, pair, self.frozen)
        second, second_created = acquire(self.actor, pair, self.outsider)
        self.assertTrue(first_created and second_created)
        self.assertNotEqual(first.run_id, second.run_id)
        self.assertEqual((first.frozen_candidate_id, second.frozen_candidate_id), (self.frozen.id, self.outsider.id))
        self.assertEqual(FinalEvaluationSlot.objects.count(), 2)
        self.assertEqual(RuntimeRun.objects.filter(document__type="VALIDATE").count(), 2)

    def test_candidate_outside_the_submission_is_not_eligible(self) -> None:
        with self.assertRaises(ApiError) as denied:
            acquire(self.actor, self.submission, self.outsider)
        self.assertEqual(denied.exception.code, "BLIND_ELIGIBILITY_DENIED")
        self.assertFalse(FinalEvaluationSlot.objects.exists())
        self.assertFalse(RuntimeRun.objects.filter(document__type="VALIDATE").exists())
        self.assertEqual(FrozenSubmission.objects.get(pk=self.submission.id).status, "FROZEN")

    def test_foreign_tenant_cannot_touch_the_slot(self) -> None:
        slot, _created = acquire(self.actor, self.submission, self.frozen)
        with self.assertRaises(ApiError) as acquired:
            acquire(self.other, self.submission, self.frozen)
        self.assertEqual(acquired.exception.code, "NOT_FOUND")
        with self.assertRaises(ApiError) as settled:
            settle(self.other, slot, "COMPLETED", uuid4())
        self.assertEqual(settled.exception.code, "NOT_FOUND")
        self.assertEqual(FinalEvaluationSlot.objects.get(pk=slot.id).status, "PENDING")

    def test_settlement_is_single_and_forward_only(self) -> None:
        slot, _created = acquire(self.actor, self.submission, self.frozen)
        result = uuid4()
        settled = settle(self.actor, slot, "COMPLETED", result)
        self.assertEqual((settled.status, settled.validation_run_id), ("COMPLETED", result))
        stored = FinalEvaluationSlot.objects.get(pk=slot.id)
        self.assertEqual((stored.status, stored.validation_run_id), ("COMPLETED", result))
        self.assertEqual(stored.document["validation_run_id"], str(result))
        self.assertEqual(FrozenSubmission.objects.get(pk=self.submission.id).status, "EVALUATED")
        with self.assertRaises(ApiError) as again:
            settle(self.actor, slot, "FAILED", None)
        self.assertEqual(again.exception.code, "INVALID_TRANSITION")
        self.assertEqual(FinalEvaluationSlot.objects.get(pk=slot.id).status, "COMPLETED")

    def test_result_reference_shape_is_enforced(self) -> None:
        slot, _created = acquire(self.actor, self.submission, self.frozen)
        for status, reference in [("COMPLETED", None), ("FAILED", uuid4()), ("DONE", None)]:
            with self.subTest(status=status), self.assertRaises(ApiError) as invalid:
                settle(self.actor, slot, status, reference)
            self.assertEqual(invalid.exception.code, "INVALID_SCHEMA")
        self.assertEqual(FinalEvaluationSlot.objects.get(pk=slot.id).status, "PENDING")

    def test_failed_settlement_keeps_the_reference_null(self) -> None:
        slot, _created = acquire(self.actor, self.submission, self.frozen)
        settled = settle(self.actor, slot, "FAILED", None)
        self.assertEqual((settled.status, settled.validation_run_id), ("FAILED", None))
        self.assertEqual(FinalEvaluationSlot.objects.get(pk=slot.id).validation_run_id, None)
        self.assertEqual(FrozenSubmission.objects.get(pk=self.submission.id).status, "FAILED")

    def test_settled_submission_reads_the_result_back_instead_of_dispatching_again(self) -> None:
        slot, _created = acquire(self.actor, self.submission, self.frozen)
        settle(self.actor, slot, "COMPLETED", uuid4())
        fresh = FrozenSubmission.objects.get(pk=self.submission.id)
        again, created = acquire(self.actor, fresh, self.frozen)
        self.assertFalse(created)
        self.assertEqual((again.id, again.status), (slot.id, "COMPLETED"))
        self.assertEqual(FinalEvaluationSlot.objects.count(), 1)

    def test_submission_outside_dispatchable_states_rejects_new_slot(self) -> None:
        identity = self.submission.id
        evaluating = dict(self.submission.document) | {"status": "EVALUATING"}
        evaluated = dict(evaluating) | {"status": "EVALUATED"}
        enforce(lambda: FrozenSubmission.objects.filter(pk=identity).update(status="EVALUATING", document=evaluating))
        enforce(lambda: FrozenSubmission.objects.filter(pk=identity).update(status="EVALUATED", document=evaluated))
        self.assertFalse(FinalEvaluationSlot.objects.exists())
        fresh = FrozenSubmission.objects.get(pk=identity)
        with self.assertRaises(ApiError) as blocked:
            acquire(self.actor, fresh, self.frozen)
        self.assertEqual(blocked.exception.code, "DISPATCH_STAGE_VIOLATION")
        self.assertFalse(FinalEvaluationSlot.objects.exists())

    def test_submission_status_flow_and_immutability_are_guarded(self) -> None:
        identity = self.submission.id
        invalid = dict(self.submission.document) | {"status": "EVALUATED"}
        desynced = dict(self.submission.document)
        for action in [lambda: FrozenSubmission.objects.filter(pk=identity).update(status="EVALUATED", document=invalid),
                       lambda: FrozenSubmission.objects.filter(pk=identity).update(status="EVALUATING", document=desynced),
                       lambda: FrozenSubmission.objects.filter(pk=identity).update(snapshot_hash="0" * 64),
                       lambda: FrozenSubmission.objects.filter(pk=identity).delete()]:
            with self.subTest(action=action), self.assertRaises(IntegrityError):
                enforce(action)
        self.assertEqual(FrozenSubmission.objects.get(pk=identity).status, "FROZEN")
