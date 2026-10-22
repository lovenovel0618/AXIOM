"""最終評估槽位服務層：以業務鍵 insert-on-conflict 固定唯一 VALIDATE run，並單向結算結果。

Service-level FinalEvaluationSlot acquisition and single-forward settlement. The isolated
Evaluator execution, sealed-test reservation and exposure ledger stay out of this slice."""
from datetime import datetime
from uuid import UUID, uuid4
from django.db import IntegrityError, transaction
from catalog.models import Account, FrozenCandidate, FrozenSubmission
from catalog.validation import ApiError
from runtime.contracts import JsonObject, validate
from runtime.models import FinalEvaluationSlot
from runtime.records import db_now

SCHEMA = "runtime-v2.schema.json"
SUBMISSION_SCHEMA = "research-v2.schema.json"
DISPATCHABLE = ("FROZEN", "EVALUATING")
RESULTS = ("COMPLETED", "FAILED")


def _authorized(actor: Account, submission: FrozenSubmission) -> None:
    """槽位只認提交所屬租戶與研究 owner；知道 UUID 不足以放行，也不回傳存在性資訊。"""
    if submission.tenant_id != actor.tenant_id:
        raise ApiError("NOT_FOUND", 404)
    from catalog.research import version_for
    version_for(actor, submission.research_version_id)
    validate(submission.document, SUBMISSION_SCHEMA, "FrozenSubmission")


def _member(submission: FrozenSubmission, candidate: FrozenCandidate) -> None:
    """候選必須是此提交固定排序中的同租戶成員；否則不具盲測資格。"""
    members = {str(item) for item in submission.document["frozen_candidate_ids"]}
    if candidate.tenant_id != submission.tenant_id or str(candidate.id) not in members:
        raise ApiError("BLIND_ELIGIBILITY_DENIED", 409)


def _lookup(tenant_id: UUID, submission_id: UUID, candidate_id: UUID, metric_version: str) -> FinalEvaluationSlot | None:
    """以業務鍵讀既有槽位；含 NULL 的通用唯一索引不能被誤認為已保護最終結果。"""
    return FinalEvaluationSlot.objects.filter(tenant_id=tenant_id, submission_id=submission_id,
        frozen_candidate_id=candidate_id, metric_version=metric_version).first()


def _advance(submission: FrozenSubmission, status: str, now: datetime) -> None:
    """只前進提交狀態；身分與快照仍不可改，guard 會擋下非相鄰轉移。"""
    document = dict(submission.document)
    document["status"] = status
    FrozenSubmission.objects.filter(pk=submission.id).update(status=status, document=document)
    submission.status, submission.document = status, document


def slot_document(identity: UUID, tenant_id: UUID, submission_id: UUID, candidate_id: UUID,
                  run_id: UUID, metric_version: str, created: datetime) -> JsonObject:
    """組出 PENDING 且結果引用為 null 的槽位文件；結算時只改狀態與引用。"""
    return {"kind": "FinalEvaluationSlot", "id": str(identity), "tenant_id": str(tenant_id), "schema_version": "2.0",
        "created_at": created.isoformat(), "submission_id": str(submission_id), "frozen_candidate_id": str(candidate_id),
        "metric_version": metric_version, "run_id": str(run_id), "validation_run_id": None, "status": "PENDING"}


def acquire(actor: Account, submission: FrozenSubmission, candidate: FrozenCandidate,
            run_id: UUID) -> tuple[FinalEvaluationSlot, bool]:
    """在 root lock 內以業務鍵取得槽位，回傳是否由本次建立。

    既有槽位一律讀回原 `run_id`／結果，不另建評估 run；`run_id` 只是本次候選身分，衝突時以既有槽位為準。
    只有需要新建槽位時才檢查提交是否仍在可派送狀態；呼叫端僅在 created 為真時建立 VALIDATE
    run／input manifest／outbox。"""
    _authorized(actor, submission)
    _member(submission, candidate)
    with transaction.atomic():
        now = db_now()
        existing = _lookup(actor.tenant_id, submission.id, candidate.id, submission.metric_version)
        if existing is not None:
            return existing, False
        if submission.status not in DISPATCHABLE:
            raise ApiError("DISPATCH_STAGE_VIOLATION", 409)
        document = slot_document(uuid4(), actor.tenant_id, submission.id, candidate.id, run_id, submission.metric_version, now)
        validate(document, SCHEMA, "FinalEvaluationSlot")
        try:
            with transaction.atomic():
                slot = FinalEvaluationSlot.objects.create(id=UUID(document["id"]), tenant_id=actor.tenant_id,
                    submission_id=submission.id, frozen_candidate_id=candidate.id, metric_version=submission.metric_version,
                    run_id=run_id, validation_run_id=None, status="PENDING", document=document, created_at=now)
        except IntegrityError:
            raced = _lookup(actor.tenant_id, submission.id, candidate.id, submission.metric_version)
            if raced is None:
                raise
            return raced, False
        if submission.status == "FROZEN":
            _advance(submission, "EVALUATING", now)
        return slot, True


def _aggregate(tenant_id: UUID, submission_id: UUID, metric_version: str) -> str:
    """包全部必要結果齊備才 EVALUATED；任一候選失敗即整包 FAILED，其餘維持評估中。"""
    slots = FinalEvaluationSlot.objects.filter(tenant_id=tenant_id, submission_id=submission_id, metric_version=metric_version)
    if slots.filter(status="FAILED").exists():
        return "FAILED"
    return "EVALUATING" if slots.exclude(status="COMPLETED").exists() else "EVALUATED"


def settle(actor: Account, slot: FinalEvaluationSlot, status: str, validation_run_id: UUID | None) -> FinalEvaluationSlot:
    """PENDING → COMPLETED／FAILED 單向結算；重複結算或結果引用形狀不符一律拒絕。

    `COMPLETED` 必須帶最終 `validation_run_id`，`FAILED` 必為 null 且不以新 run 重啟已終止根；
    slot、提交聚合狀態與結果引用在同一交易提交，衝突不能以新 UUID 繞過。"""
    if slot.tenant_id != actor.tenant_id:
        raise ApiError("NOT_FOUND", 404)
    if status not in RESULTS or (status == "COMPLETED") != (validation_run_id is not None):
        raise ApiError("INVALID_SCHEMA", 422)
    with transaction.atomic():
        locked = FinalEvaluationSlot.objects.select_for_update().get(pk=slot.id)
        if locked.status != "PENDING":
            raise ApiError("INVALID_TRANSITION", 409)
        submission = FrozenSubmission.objects.filter(pk=locked.submission_id, tenant_id=actor.tenant_id).first()
        if submission is None:
            raise ApiError("NOT_FOUND", 404)
        _authorized(actor, submission)
        now = db_now()
        document = dict(locked.document)
        document["status"] = status
        document["validation_run_id"] = None if validation_run_id is None else str(validation_run_id)
        validate(document, SCHEMA, "FinalEvaluationSlot")
        FinalEvaluationSlot.objects.filter(pk=locked.id).update(status=status, validation_run_id=validation_run_id, document=document)
        target = _aggregate(actor.tenant_id, locked.submission_id, locked.metric_version)
        if submission.status != target:
            _advance(submission, target, now)
        locked.status, locked.validation_run_id, locked.document = status, validation_run_id, document
        return locked
