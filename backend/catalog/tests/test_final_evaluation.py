"""最終評估槽位服務層：業務鍵 insert-on-conflict、成員資格、單向結算與提交狀態流。

Service-level FinalEvaluationSlot acquisition, eligibility and single-forward settlement.

派送與結算都會前進曝光帳本的狀態，故本檔以 in-process journal 掛載真實 `Vault`，逐案核對
`RESERVED`／`CONSUMED`／`RETIRED` 的可觀察後果，不以假登記冒充已封存。"""
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
from catalog.final_evaluation import acquire, evaluation_view, settle
from catalog.final_manifest import documents, limit_for
from catalog.freezing import frozen_candidate, frozen_submission
from catalog.ingest import complete_upload, ingest_tick
from catalog.models import Account, Artifact, Candidate, Dataset, DatasetVersion, EvidenceBundle, FitRun, FrozenCandidate, FrozenSubmission, Provenance, RepresentationSpec, ResearchBudget, ResearchVersion, SealRegistration, Tenant, Upload
from catalog.research import create_research, create_version, research_for
from catalog.sealing import authority
from catalog.services import actor_for, create_dataset, create_upload, put_upload
from catalog.tasks import relay_ingest, relay_profile
from catalog.tests.test_research import CONTENT, LIMITS, draft_data
from catalog.tests.test_sealing import sealed_authority
from catalog.validation import ApiError
from mathematics.search import Domain, Request, Variable, search
from runtime.contracts import JsonObject, identity_hash, validate
from runtime.control import enqueue
from runtime.models import FinalEvaluationSlot, RunEvent, RuntimeAttempt, RuntimeRun, ValidationRun
from runtime.records import ControlError, db_now, snapshot_for
from sealing.types import SealRejected
from sealing.vault import Vault

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
        self.enterContext(sealed_authority())
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
        """以真實 `Vault` 登記最小合法封存包；登記身分即凍結提交所引用的 `sealed_test_id`。"""
        existing = SealRegistration.objects.filter(research_version=self.version).first()
        if existing is not None:
            return existing
        run = RuntimeRun.objects.filter(document__type="INGEST").order_by("id").first()
        self.assertIsNotNone(run)
        tenant, source = str(self.version.tenant_id), hashlib.sha256(CONTENT).hexdigest()
        vault = authority()
        document: dict[str, object] = {"kind": "SealedTest", "id": str(uuid4()), "tenant_id": tenant, "schema_version": "2.0",
            "created_at": db_now().isoformat(), "dataset_version_id": str(self.version.dataset_version_id),
            "observation_split_id": str(uuid4()), "benchmark_partition_id": None, "benchmark_case_id": None,
            "final_rows_hash": identity_hash(["final-test-rows"]), "protocol_hash": identity_hash(["final-test-protocol"]),
            "state": "AVAILABLE", "submission_id": None, "source_content_sha256": source,
            "final_observation_tokens": sorted(vault.token(tenant, "CONTENT", {"row": index}) for index in range(2)),
            "final_lineage_tokens": sorted(vault.token(tenant, "LINEAGE", ["LOCAL_UNTRUSTED_SOURCE", source, index]) for index in range(2)),
            "exposure_fingerprint_version": "1.0"}
        attestation = vault.register(document, b"final-rows")
        return SealRegistration.objects.create(tenant_id=self.version.tenant_id, research_version=self.version, run=run,
            sealed_test_id=UUID(attestation.sealed_test_id), source_sha256=attestation.source_sha256, protocol_hash=attestation.protocol_hash,
            authority_epoch=UUID(attestation.authority_epoch), authority_sequence=attestation.authority_sequence,
            attestation_hash=attestation.attestation_hash, available=True)

    def exposure(self) -> tuple[Vault, str, str, str, str]:
        """回權威、租戶、封存身分、提交與快照；五者即曝光狀態機的完整輸入。"""
        return (authority(), str(self.submission.tenant_id), str(self.submission.sealed_test_id),
            str(self.submission.id), self.submission.snapshot_hash)

    def submit(self, frozen: list[FrozenCandidate]) -> FrozenSubmission:
        artifact = self.register_plan()
        self.register_seal()
        with transaction.atomic():
            return frozen_submission(self.actor, self.version, frozen, artifact)

    def result(self, slot: FinalEvaluationSlot, **overrides: object) -> JsonObject:
        """組出與槽位及凍結輸入一致的最終結果文件；反例測試再逐欄覆寫製造不符。"""
        payload = snapshot_for(RuntimeRun.objects.get(pk=slot.run_id)).task_input["payload"]
        document: JsonObject = {"kind": "ValidationRun", "id": str(uuid4()), "tenant_id": str(self.actor.tenant_id),
            "schema_version": "2.0", "created_at": db_now().isoformat(), "run_id": str(slot.run_id),
            "fit_run_id": str(payload["fit_run_id"]), "metric_version": slot.metric_version,
            "metrics": {"mae": 0.5, "rmse": 0.7}, "valid_coverage": 1.0, "empirical_level": "E1", "proof_level": "P1",
            "outcome_status": "SUPPORTED", "artifact_uri": "objects/final-result", "sha256": "a" * 64,
            "metric_reasons": {}, "artifact_id": str(uuid4()), "observation_split_id": str(payload["observation_split_id"]),
            "split_role": "FINAL_TEST", "frozen_candidate_id": str(slot.frozen_candidate_id),
            "submission_id": str(slot.submission_id), "evaluation_policy_hash": payload["evaluation_policy_hash"],
            "selected_count": 4, "valid_count": 4, "failed_count": 0,
            "verification_plan_artifact_id": str(payload["verification_plan_artifact_id"]),
            "verification_plan_hash": payload["verification_plan_hash"]}
        document.update(overrides)
        return document

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

    def test_dispatch_reserves_the_sealed_test_for_this_submission_only(self) -> None:
        """派送在同一權威提交內預留封存包：因已綁定本提交而冪等，別的提交或快照一律重疊。"""
        acquire(self.actor, self.submission, self.frozen)
        vault, tenant, identity, submission, snapshot = self.exposure()
        authorized: list[int] = []
        with self.assertRaises(SealRejected) as unconsumed:
            vault.read_final(tenant, identity, submission, snapshot, lambda: authorized.append(1))
        self.assertEqual(unconsumed.exception.code, "INVALID_TRANSITION")
        self.assertEqual(authorized, [])
        self.assertEqual(vault.transition(tenant, identity, "RESERVE", submission, snapshot), "RESERVED")
        for selected, other in ((str(uuid4()), snapshot), (submission, "b" * 64)):
            with self.subTest(submission=selected, snapshot=other), self.assertRaises(SealRejected) as aliased:
                vault.transition(tenant, identity, "RESERVE", selected, other)
            self.assertEqual(aliased.exception.code, "TEST_ALREADY_RESERVED")

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
            settle(self.other, slot, "COMPLETED", {})
        self.assertEqual(settled.exception.code, "NOT_FOUND")
        self.assertEqual(FinalEvaluationSlot.objects.get(pk=slot.id).status, "PENDING")

    def test_settlement_is_single_and_forward_only(self) -> None:
        slot, _created = acquire(self.actor, self.submission, self.frozen)
        document = self.result(slot)
        settled = settle(self.actor, slot, "COMPLETED", document)
        reference = UUID(str(document["id"]))
        self.assertEqual((settled.status, settled.validation_run_id), ("COMPLETED", reference))
        stored = FinalEvaluationSlot.objects.get(pk=slot.id)
        self.assertEqual((stored.status, stored.validation_run_id), ("COMPLETED", reference))
        self.assertEqual(stored.document["validation_run_id"], str(reference))
        self.assertEqual(FrozenSubmission.objects.get(pk=self.submission.id).status, "EVALUATED")
        with self.assertRaises(ApiError) as again:
            settle(self.actor, slot, "FAILED", None)
        self.assertEqual(again.exception.code, "INVALID_TRANSITION")
        self.assertEqual(FinalEvaluationSlot.objects.get(pk=slot.id).status, "COMPLETED")

    def test_completed_settlement_records_result_evidence_and_outbox(self) -> None:
        """成功結算以同一權威提交寫入結果列、只引用該結果的證據包與結果 outbox。"""
        slot, _created = acquire(self.actor, self.submission, self.frozen)
        document = self.result(slot)
        settle(self.actor, slot, "COMPLETED", document)
        result = ValidationRun.objects.get(pk=UUID(str(document["id"])))
        validate(result.document, "runtime-v2.schema.json", "ValidationRun")
        self.assertEqual((result.tenant_id, result.run_id, result.split_role), (self.actor.tenant_id, slot.run_id, "FINAL_TEST"))
        self.assertEqual((result.submission_id, result.frozen_candidate_id), (slot.submission_id, slot.frozen_candidate_id))
        bundle = EvidenceBundle.objects.get(run_id=slot.run_id)
        self.assertEqual(bundle.document["validation_ids"], [str(result.id)])
        self.assertEqual(bundle.document["proof_artifact_ids"], [])
        self.assertEqual(bundle.research_version_id, self.version.id)
        events = RunEvent.objects.filter(run_id=slot.run_id).order_by("sequence")
        self.assertEqual([event.document["event_type"] for event in events], ["RunQueued", "ValidationFinished"])
        finished = events[1]
        self.assertEqual(finished.document["payload"], {"validation_run_id": str(result.id),
            "evidence_bundle_id": str(bundle.id), "outcome_status": "SUPPORTED"})
        self.assertEqual(finished.document["producer_version"], "t07-validate-v1")

    def test_settlement_refuses_a_result_that_disagrees_with_the_slot(self) -> None:
        """結果身分逐欄對齊槽位與凍結輸入，換 run／候選／切分或驗證計畫一律拒絕落庫。"""
        slot, _created = acquire(self.actor, self.submission, self.frozen)
        cases: dict[str, object] = {"split_role": "DEVELOPMENT", "frozen_candidate_id": str(uuid4()),
            "submission_id": str(uuid4()), "run_id": str(uuid4()), "observation_split_id": str(uuid4()),
            "fit_run_id": str(uuid4()), "verification_plan_hash": "f" * 64, "metric_version": "3.0"}
        for key, value in cases.items():
            with self.subTest(key=key):
                document = self.result(slot)
                document[key] = value
                with self.assertRaises(ApiError) as invalid:
                    settle(self.actor, slot, "COMPLETED", document)
                self.assertEqual(invalid.exception.code, "INVALID_SCHEMA")
                self.assertFalse(ValidationRun.objects.exists())
                self.assertEqual(FinalEvaluationSlot.objects.get(pk=slot.id).status, "PENDING")
        vault, tenant, identity, submission, snapshot = self.exposure()
        self.assertEqual(vault.transition(tenant, identity, "RESERVE", submission, snapshot), "RESERVED")
        settle(self.actor, slot, "COMPLETED", self.result(slot))
        self.assertEqual(vault.transition(tenant, identity, "RESERVE", submission, snapshot), "CONSUMED")

    def test_settlement_refuses_a_stale_evaluation_policy(self) -> None:
        """沿用舊政策雜湊卻想落新結果時回穩定代碼，不建立任何結果列。"""
        slot, _created = acquire(self.actor, self.submission, self.frozen)
        with self.assertRaises(ApiError) as stale:
            settle(self.actor, slot, "COMPLETED", self.result(slot, evaluation_policy_hash="b" * 64))
        self.assertEqual(stale.exception.code, "EVALUATION_POLICY_MISMATCH")
        self.assertFalse(ValidationRun.objects.exists())
        self.assertEqual(FinalEvaluationSlot.objects.get(pk=slot.id).status, "PENDING")

    def test_result_reference_shape_is_enforced(self) -> None:
        slot, _created = acquire(self.actor, self.submission, self.frozen)
        cases: list[tuple[str, JsonObject | None]] = [("COMPLETED", None), ("FAILED", {}), ("DONE", None)]
        for status, result in cases:
            with self.subTest(status=status), self.assertRaises(ApiError) as invalid:
                settle(self.actor, slot, status, result)
            self.assertEqual(invalid.exception.code, "INVALID_SCHEMA")
        self.assertEqual(FinalEvaluationSlot.objects.get(pk=slot.id).status, "PENDING")
        self.assertFalse(ValidationRun.objects.exists())

    def test_failed_settlement_keeps_the_reference_null(self) -> None:
        slot, _created = acquire(self.actor, self.submission, self.frozen)
        settled = settle(self.actor, slot, "FAILED", None)
        self.assertEqual((settled.status, settled.validation_run_id), ("FAILED", None))
        self.assertEqual(FinalEvaluationSlot.objects.get(pk=slot.id).validation_run_id, None)
        self.assertEqual(FrozenSubmission.objects.get(pk=self.submission.id).status, "FAILED")
        self.assertFalse(ValidationRun.objects.exists())
        self.assertFalse(EvidenceBundle.objects.filter(run_id=slot.run_id).exists())
        self.assertEqual([event.document["event_type"] for event in RunEvent.objects.filter(run_id=slot.run_id)], ["RunQueued"])

    def test_completed_settlement_consumes_the_exposure_before_any_final_read(self) -> None:
        """成功結算先消耗曝光才落庫，之後有限資料才第一次可讀且授權僅在讀取前觸發。"""
        slot, _created = acquire(self.actor, self.submission, self.frozen)
        vault, tenant, identity, submission, snapshot = self.exposure()
        authorized: list[int] = []
        with self.assertRaises(SealRejected) as reserved:
            vault.read_final(tenant, identity, submission, snapshot, lambda: authorized.append(1))
        self.assertEqual(reserved.exception.code, "INVALID_TRANSITION")
        settle(self.actor, slot, "COMPLETED", self.result(slot))
        self.assertEqual(authorized, [])
        self.assertEqual(vault.read_final(tenant, identity, submission, snapshot, lambda: authorized.append(1)), b"final-rows")
        self.assertEqual(authorized, [1])
        self.assertEqual(vault.transition(tenant, identity, "RESERVE", submission, snapshot), "CONSUMED")

    def test_failed_settlement_retires_the_exposure_without_resurrection(self) -> None:
        """永久失敗時保守退役：不回 AVAILABLE、不可再讀，也不讓新的預留重新取得資格。"""
        slot, _created = acquire(self.actor, self.submission, self.frozen)
        settle(self.actor, slot, "FAILED", None)
        vault, tenant, identity, submission, snapshot = self.exposure()
        authorized: list[int] = []
        with self.assertRaises(SealRejected) as retired:
            vault.read_final(tenant, identity, submission, snapshot, lambda: authorized.append(1))
        self.assertEqual(retired.exception.code, "INVALID_TRANSITION")
        self.assertEqual(authorized, [])
        with self.assertRaises(SealRejected) as resurrected:
            vault.transition(tenant, identity, "RESERVE", submission, snapshot)
        self.assertEqual(resurrected.exception.code, "TEST_ALREADY_CONSUMED")

    def test_settled_submission_reads_the_result_back_instead_of_dispatching_again(self) -> None:
        slot, _created = acquire(self.actor, self.submission, self.frozen)
        settle(self.actor, slot, "COMPLETED", self.result(slot))
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

    def test_evaluation_view_projects_slot_states_and_the_exposure_budget(self) -> None:
        """公開投影只回固定身分與狀態：預留／消耗／退役計數由槽位推導，總額為凍結候選數。"""
        pair = self.submit([self.frozen, self.outsider])
        first, _first_created = acquire(self.actor, pair, self.frozen)
        second, _second_created = acquire(self.actor, pair, self.outsider)
        settle(self.actor, first, "COMPLETED", self.result(first))
        settle(self.actor, second, "FAILED", None)
        view = evaluation_view(self.actor, pair.id)
        self.assertEqual((view["submission_id"], view["metric_version"]), (str(pair.id), pair.metric_version))
        self.assertEqual(view["status"], "FAILED")
        self.assertEqual(view["exposure"], {"budget": 2, "reserved": 0, "consumed": 1, "retired": 1})
        self.assertEqual({slot["status"] for slot in view["slots"]}, {"COMPLETED", "FAILED"})
        completed = next(slot for slot in view["slots"] if slot["status"] == "COMPLETED")
        failed = next(slot for slot in view["slots"] if slot["status"] == "FAILED")
        self.assertEqual((completed["frozen_candidate_id"], completed["slot_id"], completed["run_id"]),
            (str(self.frozen.id), str(first.id), str(first.run_id)))
        self.assertEqual(completed["validation_run_id"], str(FinalEvaluationSlot.objects.get(pk=first.id).validation_run_id))
        self.assertEqual(failed["frozen_candidate_id"], str(self.outsider.id))
        self.assertIsNone(failed["validation_run_id"])

    def test_evaluation_view_counts_a_pending_dispatch_as_reserved(self) -> None:
        """只派送未結算時只計為預留，提交與槽位狀態都不被投影成已完成。"""
        slot, _created = acquire(self.actor, self.submission, self.frozen)
        view = evaluation_view(self.actor, self.submission.id)
        self.assertEqual((view["status"], view["exposure"]),
            ("EVALUATING", {"budget": 1, "reserved": 1, "consumed": 0, "retired": 0}))
        self.assertEqual(view["slots"], [{"frozen_candidate_id": str(self.frozen.id), "slot_id": str(slot.id),
            "run_id": str(slot.run_id), "validation_run_id": None, "status": "PENDING"}])

    def test_evaluation_view_refuses_foreign_and_unknown_submissions(self) -> None:
        """跨租戶提交與未知 UUID 同回 404：不因槽位存在與否洩漏提交。"""
        with self.assertRaises(ApiError) as foreign:
            evaluation_view(self.other, self.submission.id)
        self.assertEqual(foreign.exception.code, "NOT_FOUND")
        with self.assertRaises(ApiError) as unknown:
            evaluation_view(self.actor, uuid4())
        self.assertEqual(unknown.exception.code, "NOT_FOUND")

    def test_submission_evaluation_endpoint_reads_the_authorized_projection(self) -> None:
        """端點重新驗租戶與研究 owner 後回契約內的投影；跨租戶與未知 UUID 皆 404。"""
        acquire(self.actor, self.submission, self.frozen)
        self.client.force_login(self.actor.user)
        response = self.client.get(f"/api/v2/frozen-submissions/{self.submission.id}/evaluation")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual((body["status"], body["exposure"]["budget"]), ("EVALUATING", 1))
        self.assertEqual(len(body["slots"]), 1)
        self.client.force_login(self.other.user)
        self.assertEqual(self.client.get(f"/api/v2/frozen-submissions/{self.submission.id}/evaluation").status_code, 404)
        self.assertEqual(self.client.get(f"/api/v2/frozen-submissions/{uuid4()}/evaluation").status_code, 404)

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
