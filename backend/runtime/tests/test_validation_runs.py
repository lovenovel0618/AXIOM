"""ValidationRun 的契約、唯一鍵、分母一致與不可改刪測試，於真 PostgreSQL 上執行。"""
from collections.abc import Callable
from datetime import datetime, timedelta
from uuid import UUID, uuid4
from django.db import IntegrityError, connection, transaction
from django.test import TransactionTestCase
from runtime.contracts import JsonObject, validate
from runtime.models import RuntimeRun, ValidationRun
from runtime.records import db_now


def run_row(tenant_id: UUID, created: datetime) -> RuntimeRun:
    """最小權威 VALIDATE root；結果列的複合外鍵必須指向真實同租戶 run。"""
    identity = uuid4()
    document: JsonObject = {"kind": "RunRecord", "id": str(identity), "tenant_id": str(tenant_id),
        "root_run_id": str(identity), "type": "VALIDATE", "is_root": True, "parent_run_id": None, "status": "QUEUED"}
    return RuntimeRun.objects.create(id=identity, tenant_id=tenant_id, control_only=False, document=document,
        queue_deadline=created + timedelta(seconds=60), available_at=created)


def result_document(identity: UUID, tenant_id: UUID, run_id: UUID, created: datetime, **overrides: object) -> JsonObject:
    """組出 FINAL_TEST 結果文件；反例測試再逐欄覆寫製造不同步或非法值。"""
    document: JsonObject = {"kind": "ValidationRun", "id": str(identity), "tenant_id": str(tenant_id),
        "schema_version": "2.0", "created_at": created.isoformat(), "run_id": str(run_id), "fit_run_id": str(uuid4()),
        "metric_version": "2.0", "metrics": {"mae": 0.5, "rmse": 0.7}, "valid_coverage": 1.0, "empirical_level": "E1",
        "proof_level": "P1", "outcome_status": "SUPPORTED", "artifact_uri": "objects/final-result", "sha256": "a" * 64,
        "metric_reasons": {}, "artifact_id": str(uuid4()), "observation_split_id": str(uuid4()), "split_role": "FINAL_TEST",
        "frozen_candidate_id": str(uuid4()), "submission_id": str(uuid4()), "evaluation_policy_hash": "b" * 64,
        "selected_count": 4, "valid_count": 4, "failed_count": 0, "verification_plan_artifact_id": str(uuid4()),
        "verification_plan_hash": "c" * 64}
    document.update(overrides)
    return document


def row(document: JsonObject, **columns: object) -> ValidationRun:
    """以文件為權威落庫結果列；測試可逐欄覆寫製造文件與欄位不同步。"""
    split_role = str(document["split_role"])
    final = split_role == "FINAL_TEST"
    submission, candidate = document["submission_id"], document["frozen_candidate_id"]
    values: dict[str, object] = {"id": UUID(str(document["id"])), "tenant_id": UUID(str(document["tenant_id"])),
        "run_id": UUID(str(document["run_id"])), "observation_split_id": UUID(str(document["observation_split_id"])),
        "split_role": split_role, "metric_version": str(document["metric_version"]), "document": document,
        "submission_id": UUID(str(submission)) if final and submission is not None else None,
        "frozen_candidate_id": UUID(str(candidate)) if final and candidate is not None else None,
        "created_at": datetime.fromisoformat(str(document["created_at"]))}
    values.update(columns)
    return ValidationRun.objects.create(**values)


def enforce(action: Callable[[], object]) -> None:
    """在單一交易內執行資料庫變動；觸發器或延遲約束拒絕時拋 IntegrityError。"""
    with transaction.atomic():
        action()
        connection.check_constraints()


class ValidationRunTests(TransactionTestCase):
    def setUp(self) -> None:
        self.now = db_now()
        self.tenant = uuid4()
        self.root = run_row(self.tenant, self.now)

    def final(self, **overrides: object) -> JsonObject:
        document = result_document(uuid4(), self.tenant, self.root.id, self.now)
        document.update(overrides)
        return document

    def test_result_document_matches_contract_and_round_trips(self) -> None:
        document = self.final()
        validate(document, "runtime-v2.schema.json", "ValidationRun")
        stored = ValidationRun.objects.get(pk=row(document).id)
        self.assertEqual(stored.document, document)
        self.assertEqual((stored.split_role, stored.metric_version), ("FINAL_TEST", "2.0"))

    def test_document_identity_must_match_columns(self) -> None:
        document = self.final()
        with self.assertRaises(IntegrityError):
            row(document, submission_id=uuid4())

    def test_denominator_must_add_up(self) -> None:
        document = self.final(selected_count=4, valid_count=3, failed_count=0)
        with self.assertRaises(IntegrityError):
            row(document)

    def test_development_result_is_unique_per_run_and_split(self) -> None:
        split = str(uuid4())
        first = result_document(uuid4(), self.tenant, self.root.id, self.now, split_role="DEVELOPMENT",
            submission_id=None, frozen_candidate_id=None, observation_split_id=split)
        row(first)
        second = uuid4()
        with self.assertRaises(IntegrityError):
            row(dict(first) | {"id": str(second)})

    def test_final_result_is_unique_per_submission_and_candidate(self) -> None:
        submission, candidate = str(uuid4()), str(uuid4())
        row(self.final(submission_id=submission, frozen_candidate_id=candidate))
        with self.assertRaises(IntegrityError):
            row(self.final(submission_id=submission, frozen_candidate_id=candidate))

    def test_final_result_requires_the_submission_and_candidate(self) -> None:
        document = self.final(submission_id=None)
        with self.assertRaises(IntegrityError):
            row(document)

    def test_development_result_rejects_final_references(self) -> None:
        document = result_document(uuid4(), self.tenant, self.root.id, self.now, split_role="DEVELOPMENT")
        with self.assertRaises(IntegrityError):
            row(document, submission_id=UUID(str(document["submission_id"])))

    def test_split_role_and_metric_version_domains_are_enforced(self) -> None:
        holdout = self.final(split_role="HOLDOUT", submission_id=None, frozen_candidate_id=None)
        with self.assertRaises(IntegrityError):
            row(holdout)
        with self.assertRaises(IntegrityError):
            row(self.final(metric_version="1.0"))

    def test_result_must_reference_an_existing_run(self) -> None:
        document = self.final(run_id=str(uuid4()))
        with self.assertRaises(IntegrityError):
            enforce(lambda: row(document))

    def test_result_is_immutable(self) -> None:
        stored = row(self.final())
        document = dict(stored.document) | {"outcome_status": "FALSIFIED"}
        with self.assertRaises(IntegrityError):
            enforce(lambda: ValidationRun.objects.filter(pk=stored.id).update(document=document))
        with self.assertRaises(IntegrityError):
            enforce(lambda: ValidationRun.objects.filter(pk=stored.id).delete())
        self.assertEqual(ValidationRun.objects.count(), 1)
