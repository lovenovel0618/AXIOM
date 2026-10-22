"""FinalEvaluationSlot 的契約、唯一鍵、狀態與不可改刪測試，於真 PostgreSQL 上執行。"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from uuid import UUID, uuid4
from django.db import IntegrityError, connections
from django.test import TransactionTestCase
from jsonschema.exceptions import ValidationError
from runtime.contracts import JsonObject, validate
from runtime.models import FinalEvaluationSlot
from runtime.records import db_now


def slot_document(identity: UUID, tenant: UUID, submission: UUID, candidate: UUID, run: UUID, created: datetime) -> JsonObject:
    """組出待落庫的槽位文件；反例測試再逐欄覆寫製造不同步或非法值。"""
    return {"kind": "FinalEvaluationSlot", "id": str(identity), "tenant_id": str(tenant), "schema_version": "2.0",
            "created_at": created.isoformat(), "submission_id": str(submission), "frozen_candidate_id": str(candidate),
            "metric_version": "2.0", "run_id": str(run), "validation_run_id": None, "status": "PENDING"}


class FinalSlotTests(TransactionTestCase):
    def setUp(self) -> None:
        self.tenant, self.submission, self.candidate, self.evaluation_run = uuid4(), uuid4(), uuid4(), uuid4()

    def insert(self, *, identity: UUID | None = None, submission: UUID | None = None, candidate: UUID | None = None,
               evaluation_run: UUID | None = None, metric_version: str = "2.0", status: str = "PENDING",
               validation_run_id: UUID | None = None, document: JsonObject | None = None,
               created_at: datetime | None = None) -> FinalEvaluationSlot:
        created = created_at if created_at is not None else db_now()
        slot_id = identity if identity is not None else uuid4()
        payload = document if document is not None else slot_document(
            slot_id, self.tenant, submission if submission is not None else self.submission,
            candidate if candidate is not None else self.candidate,
            evaluation_run if evaluation_run is not None else self.evaluation_run, created)
        return FinalEvaluationSlot.objects.create(
            id=slot_id, tenant_id=self.tenant, submission_id=submission if submission is not None else self.submission,
            frozen_candidate_id=candidate if candidate is not None else self.candidate, metric_version=metric_version,
            run_id=evaluation_run if evaluation_run is not None else self.evaluation_run,
            validation_run_id=validation_run_id, status=status, document=payload, created_at=created)

    def settle(self, slot: FinalEvaluationSlot, status: str, validation_run_id: UUID | None) -> None:
        """以服務層應有的欄位組合更新結果引用，document 同步改寫。"""
        document = dict(slot.document)
        document["status"] = status
        document["validation_run_id"] = None if validation_run_id is None else str(validation_run_id)
        FinalEvaluationSlot.objects.filter(pk=slot.id).update(
            status=status, validation_run_id=validation_run_id, document=document)

    def test_pending_document_matches_contract_and_round_trips(self) -> None:
        slot = self.insert()
        validate(slot.document, "runtime-v2.schema.json", "FinalEvaluationSlot")
        stored = FinalEvaluationSlot.objects.get(pk=slot.id)
        self.assertEqual(stored.document, slot.document)
        self.assertEqual((stored.status, stored.validation_run_id), ("PENDING", None))

    def test_completed_result_slot_requires_reference_in_schema(self) -> None:
        document = slot_document(uuid4(), self.tenant, self.submission, self.candidate, self.evaluation_run, db_now())
        document["status"] = "COMPLETED"
        with self.assertRaises(ValidationError):
            validate(document, "runtime-v2.schema.json", "FinalEvaluationSlot")

    def test_duplicate_business_key_rejected(self) -> None:
        self.insert()
        with self.assertRaises(IntegrityError):
            self.insert()

    def test_parallel_dispatch_keeps_one_slot(self) -> None:
        def compete(_index: int) -> bool:
            try:
                self.insert()
                return True
            except IntegrityError:
                return False
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=4) as pool:
            outcomes = list(pool.map(compete, range(4)))
        self.assertEqual((sum(outcomes), FinalEvaluationSlot.objects.count()), (1, 1))

    def test_metric_version_is_fixed_to_two(self) -> None:
        document = slot_document(uuid4(), self.tenant, self.submission, self.candidate, self.evaluation_run, db_now())
        document["metric_version"] = "1.0"
        with self.assertRaises(IntegrityError):
            self.insert(metric_version="1.0", document=document)

    def test_slot_must_start_pending(self) -> None:
        document = slot_document(uuid4(), self.tenant, self.submission, self.candidate, self.evaluation_run, db_now())
        document["status"] = "COMPLETED"
        document["validation_run_id"] = str(uuid4())
        with self.assertRaises(IntegrityError):
            self.insert(status="COMPLETED", validation_run_id=uuid4(), document=document)

    def test_document_identity_must_match_columns(self) -> None:
        document = slot_document(uuid4(), self.tenant, uuid4(), self.candidate, self.evaluation_run, db_now())
        with self.assertRaises(IntegrityError):
            self.insert(document=document)

    def test_result_reference_is_exclusive(self) -> None:
        first = self.insert()
        with self.assertRaises(IntegrityError):
            self.settle(first, "COMPLETED", None)
        second = self.insert(identity=uuid4(), candidate=uuid4())
        with self.assertRaises(IntegrityError):
            self.settle(second, "FAILED", uuid4())

    def test_settlement_is_single_and_forward_only(self) -> None:
        slot = self.insert()
        result = uuid4()
        self.settle(slot, "COMPLETED", result)
        stored = FinalEvaluationSlot.objects.get(pk=slot.id)
        self.assertEqual((stored.status, stored.validation_run_id), ("COMPLETED", result))
        with self.assertRaises(IntegrityError):
            self.settle(stored, "FAILED", None)

    def test_status_domain_is_enforced(self) -> None:
        slot = self.insert()
        document = dict(slot.document)
        document["status"] = "DONE"
        with self.assertRaises(IntegrityError):
            FinalEvaluationSlot.objects.filter(pk=slot.id).update(status="DONE", document=document)

    def test_run_and_identity_are_immutable(self) -> None:
        slot = self.insert()
        for values in [{"run_id": uuid4()}, {"submission_id": uuid4()}, {"frozen_candidate_id": uuid4()},
                       {"tenant_id": uuid4()}, {"created_at": db_now()}]:
            with self.subTest(column=values):
                with self.assertRaises(IntegrityError):
                    FinalEvaluationSlot.objects.filter(pk=slot.id).update(**values)

    def test_delete_is_blocked(self) -> None:
        slot = self.insert()
        with self.assertRaises(IntegrityError):
            FinalEvaluationSlot.objects.filter(pk=slot.id).delete()
        self.assertEqual(FinalEvaluationSlot.objects.count(), 1)
