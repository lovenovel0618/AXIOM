"""隔離 Evaluator 的 FINAL_TEST 執行段：曝光順序、分母與拒答、單向結算的端到端回歸。

End-to-end regression for the isolated FINAL_TEST evaluator: consume-then-read exposure
ordering, denominator reporting and one-way settlement of the single forward slot.

本檔以真實 `Vault`、真實 SEARCH／凍結鏈與真實匯入建立情境，不以偽造登記冒充已封存；final labels
只存在私有封存包內，評分與結算則以公開資料庫的槽位、結果列、事件與曝光狀態交叉核對。"""
from fractions import Fraction
import hashlib
from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import UUID, uuid4
from django.contrib.auth.models import User
from django.db import transaction
from django.test import TransactionTestCase, override_settings
from catalog.artifacts import register as register_artifact
from catalog.candidates import persist
from catalog.final_evaluation import acquire
from catalog.final_evaluator import validate_tick
from catalog.freezing import frozen_candidate, frozen_submission
from catalog.ingest import complete_upload, ingest_tick
from catalog.models import (Account, Artifact, Candidate, Dataset, DatasetVersion, EvidenceBundle, FitRun,
    FrozenCandidate, FrozenSubmission, Provenance, RepresentationSpec, ResearchBudget, ResearchState,
    ResearchVersion, SealRegistration, Tenant, Upload)
from catalog.research import create_research, create_version, research_for
from catalog.sealing import authority
from catalog.services import actor_for, create_dataset, create_upload, put_upload
from catalog.tasks import relay_ingest, relay_profile, relay_validate
from catalog.tests.test_research import CONTENT, LIMITS, draft_data
from catalog.tests.test_sealing import sealed_authority
from mathematics.search import Domain, Request, Variable, search
from runtime.contracts import JsonObject, canonical_bytes, identity_hash, validate
from runtime.models import FinalEvaluationSlot, RunEvent, RuntimeRun, ValidationRun
from runtime.records import db_now
from sealing.types import SealRejected
from sealing.vault import Vault

DIMENSIONLESS = (0,) * 7
FINAL_INDICES = (8, 9)
TARGET_MEAN = "6"
FINAL_BUDGET = {"cpu_seconds": 120, "gpu_seconds": 0, "wall_seconds": 600, "tokens": 0,
    "candidate_limit": 10, "memory_bytes": 4 * 1024**3}
UNREADABLE_PAYLOAD = b"final-rows"


def final_payload(indices: tuple[int, ...] = FINAL_INDICES) -> bytes:
    """以 `sealing/prepare.py` 的 canonical rows 形狀組出 final labels：每列一個輸入與一個目標。"""
    rows: list[JsonObject] = [{"row_id": index, "observation": {"inputs": [f"{index}/1"], "target": f"{2 * index + 1}/1",
        "input_unit": list(DIMENSIONLESS), "target_unit": list(DIMENSIONLESS), "time": None, "group": None}} for index in indices]
    return canonical_bytes({"rows": rows})


def request(fit: list[tuple[float, float]], development: list[tuple[float, float]]) -> Request:
    """固定域與無量綱單位的離線請求；評估器測試只用到 fit／development。"""
    return Request(Variable("x", DIMENSIONLESS), DIMENSIONLESS, Domain(Fraction(-1000), Fraction(1000), True, True),
        tuple(fit), tuple(development))


@override_settings(INGEST_ENABLED=True, INGEST_LIMITS_JSON=json.dumps(LIMITS), PROFILE_ENABLED=False, VALIDATE_ENABLED=True)
class FinalEvaluatorTests(TransactionTestCase):
    def setUp(self) -> None:
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        override = self.settings(OBJECT_ROOT=Path(directory.name))
        override.enable()
        self.addCleanup(override.disable)
        self.enterContext(sealed_authority())
        self.actor = self.account(Tenant.objects.create(name="final-evaluator"))
        self.other = self.account(Tenant.objects.create(name="final-evaluator-other"))
        self.version = self.fixture()
        self.budget = ResearchBudget.objects.get(research_version=self.version)
        self.candidates = self.store()
        self.frozen = self.freeze_one(self.candidates[0])
        self.outsider = self.freeze_one(self.candidates[1])

    def account(self, tenant: Tenant) -> Account:
        user = User.objects.create(username=uuid4().hex, password="!")
        return Account.objects.create(user=user, tenant=tenant)

    def fixture(self) -> ResearchVersion:
        """以真實匯入建立資料與研究版本，不以偽造 fixture 代替來源鏈。"""
        with transaction.atomic():
            actor = actor_for(self.actor.user_id)
            dataset = Dataset.objects.get(pk=UUID(create_dataset(actor, {"name": "final-evaluator"})["id"]))
            upload = create_upload(actor, dataset, {"filename": "synthetic", "format": "CSV", "size_bytes": len(CONTENT),
                "sha256": hashlib.sha256(CONTENT).hexdigest()}, "http://localhost")
            row = Upload.objects.get(pk=UUID(upload["id"]))
            put_upload(actor, row, upload["required_headers"]["X-Upload-Token"], BytesIO(CONTENT))
            run = complete_upload(actor, row, row.sha256, "complete")
        self.assertTrue(ingest_tick(str(actor.tenant_id), run["id"], 0))
        version_row = DatasetVersion.objects.get(dataset=dataset)
        with transaction.atomic():
            actor = actor_for(self.actor.user_id)
            research = research_for(actor, UUID(create_research(actor, {"name": "final-evaluator"})["id"]))
            data = draft_data(version_row.id)
            data["budget"] = dict(FINAL_BUDGET)
            document = create_version(actor, research, data)
        return ResearchVersion.objects.get(pk=UUID(document["id"]))

    def store(self) -> list[Candidate]:
        """精確線性資料（y = 2x + 1）的離線報告，只含 fit／development。"""
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

    def register_seal(self, payload: bytes) -> SealRegistration:
        """以真實 `Vault` 登記指定 payload 的封存包；登記身分即凍結提交所引用的 `sealed_test_id`。"""
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
            "final_rows_hash": identity_hash(list(FINAL_INDICES)), "protocol_hash": identity_hash(["final-evaluator-protocol"]),
            "state": "AVAILABLE", "submission_id": None, "source_content_sha256": source,
            "final_observation_tokens": sorted(vault.token(tenant, "CONTENT", {"row": index}) for index in FINAL_INDICES),
            "final_lineage_tokens": sorted(vault.token(tenant, "LINEAGE", ["LOCAL_UNTRUSTED_SOURCE", source, index]) for index in FINAL_INDICES),
            "exposure_fingerprint_version": "1.0"}
        attestation = vault.register(document, payload)
        return SealRegistration.objects.create(tenant_id=self.version.tenant_id, research_version=self.version, run=run,
            sealed_test_id=UUID(attestation.sealed_test_id), source_sha256=attestation.source_sha256, protocol_hash=attestation.protocol_hash,
            authority_epoch=UUID(attestation.authority_epoch), authority_sequence=attestation.authority_sequence,
            attestation_hash=attestation.attestation_hash, available=True)

    def quality_report(self, seal: SealRegistration) -> Artifact:
        """登記品質報告並把版本狀態指向它；`baseline=FIT_MEAN` 的 fit 均值只由此取得。

        就緒保證要求 READY 品質報告指向同一筆可用封存登記的 run，因此 run_id 只能取自該登記。"""
        content: JsonObject = {"kind": "QualityReport", "schema_version": "1.0", "research_version_id": str(self.version.id),
            "run_id": str(seal.run_id), "quality": "PASS", "blocking_code": None, "readiness": "READY", "remaining": [],
            "precision_bits": 53, "fit_summary": {"selected_count": 6, "unique_x": 6, "target_min": "1", "target_max": "11",
                "target_mean": TARGET_MEAN, "target_iqr": "5"}}
        source = Provenance.objects.get(pk=self.version.provenance_id, tenant_id=self.version.tenant_id)
        artifact = register_artifact(self.actor, self.version.dataset_version, uuid4(), content, source, research_version=self.version)
        ResearchState.objects.create(research_version=self.version, tenant_id=self.version.tenant_id, quality_id=artifact.id)
        return artifact

    def dispatch(self, payload: bytes = final_payload()) -> tuple[FinalEvaluationSlot, FrozenSubmission]:
        """以指定 final payload 登記封存包、建立凍結提交並派送唯一槽位；回傳槽位與提交。"""
        artifact = self.register_plan()
        self.register_seal(payload)
        with transaction.atomic():
            submission = frozen_submission(self.actor, self.version, [self.frozen], artifact)
        slot, created = acquire(self.actor, submission, self.frozen)
        self.assertTrue(created)
        return slot, submission

    def exposure(self, submission: FrozenSubmission) -> tuple[Vault, str, str, str, str]:
        """回權威、租戶、封存身分、提交與快照；五者即曝光狀態機的完整輸入。"""
        return (authority(), str(submission.tenant_id), str(submission.sealed_test_id),
            str(submission.id), submission.snapshot_hash)

    def settled(self, slot: FinalEvaluationSlot) -> ValidationRun:
        """讀回槽位唯一引用的結果列；未結算即為測試前提失敗。"""
        return ValidationRun.objects.get(pk=FinalEvaluationSlot.objects.get(pk=slot.id).validation_run_id)

    def tick(self, slot: FinalEvaluationSlot, generation: int = 0) -> bool:
        return validate_tick(str(slot.tenant_id), str(slot.run_id), generation)

    def test_validate_tick_is_disabled_until_the_evaluator_is_enabled(self) -> None:
        """未啟用時不取得槽位、不動用曝光也不改狀態，重送仍可恢復。"""
        slot, submission = self.dispatch()
        with self.settings(VALIDATE_ENABLED=False):
            self.assertFalse(self.tick(slot))
        self.assertEqual(FinalEvaluationSlot.objects.get(pk=slot.id).status, "PENDING")
        self.assertEqual(RuntimeRun.objects.get(pk=slot.run_id).document["status"], "QUEUED")
        self.assertFalse(ValidationRun.objects.exists())
        vault, tenant, identity, selected, snapshot = self.exposure(submission)
        self.assertEqual(vault.transition(tenant, identity, "RESERVE", selected, snapshot), "RESERVED")

    def test_validate_tick_scores_the_frozen_candidate_on_the_final_test(self) -> None:
        """成功路徑：先消耗曝光才讀 labels，以凍結公式評分並把唯一槽位單向結算為 COMPLETED。"""
        self.quality_report(self.register_seal(final_payload()))
        slot, submission = self.dispatch()
        self.assertTrue(self.tick(slot))
        stored = FinalEvaluationSlot.objects.get(pk=slot.id)
        result = ValidationRun.objects.get(pk=stored.validation_run_id)
        self.assertEqual((stored.status, result.split_role), ("COMPLETED", "FINAL_TEST"))
        validate(result.document, "runtime-v2.schema.json", "ValidationRun")
        self.assertEqual(result.document["metrics"], {"mae": 0.0, "rmse": 0.0})
        self.assertEqual((result.document["valid_coverage"], result.document["metric_reasons"]), (1.0, {}))
        self.assertEqual((result.document["selected_count"], result.document["valid_count"], result.document["failed_count"]), (2, 2, 0))
        self.assertEqual((result.document["empirical_level"], result.document["proof_level"]), ("E2", "P0"))
        self.assertEqual(result.document["outcome_status"], "SUPPORTED")
        self.assertEqual(result.document["artifact_uri"], f"private://evaluator/final-report/{result.id}")
        self.assertEqual(result.document["sha256"], hashlib.sha256(canonical_bytes({"metrics": {"mae": "0", "rmse": "0"},
            "counts": {"selected": 2, "valid": 2, "failed": 0}, "outcome_status": "SUPPORTED"})).hexdigest())
        self.assertEqual((result.submission_id, result.frozen_candidate_id), (submission.id, self.frozen.id))
        run = RuntimeRun.objects.get(pk=slot.run_id)
        self.assertEqual((run.document["status"], run.document["stop_reason"], run.document["dispatch_stage"]),
            ("SUCCEEDED", "COMPLETED", "CLOSED"))
        events = [event.document for event in RunEvent.objects.filter(run=run).order_by("sequence")]
        self.assertEqual([event["event_type"] for event in events], ["RunQueued", "RunStarted", "ValidationFinished", "RunFinished"])
        self.assertEqual(events[2]["payload"]["outcome_status"], "SUPPORTED")
        self.assertEqual(events[2]["producer_version"], "t07-validate-v1")
        bundle = EvidenceBundle.objects.get(run_id=slot.run_id)
        self.assertEqual(bundle.document["validation_ids"], [str(result.id)])
        self.assertEqual(FrozenSubmission.objects.get(pk=submission.id).status, "EVALUATED")
        vault, tenant, identity, selected, snapshot = self.exposure(submission)
        authorized: list[int] = []
        self.assertEqual(vault.read_final(tenant, identity, selected, snapshot, lambda: authorized.append(1)), final_payload())
        self.assertEqual((authorized, vault.transition(tenant, identity, "RESERVE", selected, snapshot)), ([1], "CONSUMED"))

    def test_validate_tick_reports_insufficient_evidence_without_a_frozen_baseline_mean(self) -> None:
        """缺 `FIT_MEAN` 來源時不臆測基準：照實回報分母仍判 INSUFFICIENT_EVIDENCE，不假報 SUPPORTED。"""
        slot, _submission = self.dispatch()
        self.assertFalse(ResearchState.objects.exists())
        self.assertTrue(self.tick(slot))
        result = self.settled(slot)
        self.assertEqual(result.document["metrics"], {"mae": 0.0, "rmse": 0.0})
        self.assertEqual(result.document["outcome_status"], "INSUFFICIENT_EVIDENCE")

    def test_validate_tick_retires_the_exposure_when_the_payload_cannot_be_read(self) -> None:
        """不可解析的封存包等同不可評分：以失敗結算、不落任何結果列，曝光保守退役且不可復活。"""
        slot, submission = self.dispatch(UNREADABLE_PAYLOAD)
        self.assertTrue(self.tick(slot))
        stored = FinalEvaluationSlot.objects.get(pk=slot.id)
        self.assertEqual((stored.status, stored.validation_run_id), ("FAILED", None))
        self.assertFalse(ValidationRun.objects.exists())
        run = RuntimeRun.objects.get(pk=slot.run_id)
        self.assertEqual((run.document["status"], run.document["dispatch_stage"]), ("FAILED", "CLOSED"))
        self.assertEqual(FrozenSubmission.objects.get(pk=submission.id).status, "FAILED")
        vault, tenant, identity, selected, snapshot = self.exposure(submission)
        authorized: list[int] = []
        with self.assertRaises(SealRejected) as retired:
            vault.read_final(tenant, identity, selected, snapshot, lambda: authorized.append(1))
        self.assertEqual((retired.exception.code, authorized), ("INVALID_TRANSITION", []))
        with self.assertRaises(SealRejected) as resurrected:
            vault.transition(tenant, identity, "RESERVE", selected, snapshot)
        self.assertEqual(resurrected.exception.code, "TEST_ALREADY_CONSUMED")

    def test_validate_tick_is_single_forward_after_settlement(self) -> None:
        """已結算的槽位不得重評：重送只讀回原結果，不產生第二份結果列。"""
        self.quality_report(self.register_seal(final_payload()))
        slot, _submission = self.dispatch()
        self.assertTrue(self.tick(slot))
        reference = FinalEvaluationSlot.objects.get(pk=slot.id).validation_run_id
        self.assertFalse(self.tick(slot))
        self.assertEqual(FinalEvaluationSlot.objects.get(pk=slot.id).validation_run_id, reference)
        self.assertEqual(ValidationRun.objects.count(), 1)

    def test_relay_validate_dispatches_only_the_queued_validate_root(self) -> None:
        """relay 只認 QUEUED 的 VALIDATE root 並派到專用佇列；INGEST／PROFILE 不得誤派。"""
        slot, _submission = self.dispatch()
        with patch("catalog.tasks.app.send_task") as send:
            self.assertEqual((relay_ingest(), relay_profile(), relay_validate()), (0, 0, 1))
        send.assert_called_once_with("catalog.validate_tick",
            args=[str(slot.tenant_id), str(slot.run_id), 0], queue="validate", retry=False)
        self.assertIsNotNone(RuntimeRun.objects.get(pk=slot.run_id).last_polled_at)
