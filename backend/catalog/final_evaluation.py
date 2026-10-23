"""最終評估槽位服務層：以業務鍵 insert-on-conflict 固定唯一 VALIDATE run，並單向結算結果。

Service-level FinalEvaluationSlot acquisition and single-forward settlement. The isolated
Evaluator execution, sealed-test reservation and exposure ledger stay out of this slice.

成功結算時，不可變的 `ValidationRun`、只引用該結果的證據包與 `ValidationFinished` outbox 與槽位、
提交聚合狀態同交易提交；結果身分逐欄對齊槽位與凍結輸入，換 UUID 或換政策都無法繞過。"""
from datetime import datetime
from uuid import UUID, uuid4
from django.db import IntegrityError, transaction
from jsonschema.exceptions import ValidationError
from catalog.evidence import register_validation
from catalog.final_manifest import documents, limit_for
from catalog.models import Account, FrozenCandidate, FrozenSubmission, Provenance, ResearchBudget, ResearchVersion
from catalog.services import provenance
from catalog.validation import ApiError
from runtime.budget_types import BudgetLimit
from runtime.contracts import JsonObject, validate
from runtime.control import enqueue
from runtime.models import FinalEvaluationSlot, RuntimeRun, ValidationRun
from runtime.records import db_now, emit, lock_run, save_run, snapshot_for

SCHEMA = "runtime-v2.schema.json"
SUBMISSION_SCHEMA = "research-v2.schema.json"
DISPATCHABLE = ("FROZEN", "EVALUATING")
RESULTS = ("COMPLETED", "FAILED")


def _authorized(actor: Account, submission: FrozenSubmission) -> ResearchVersion:
    """槽位只認提交所屬租戶與研究 owner；知道 UUID 不足以放行，也不回傳存在性資訊。"""
    if submission.tenant_id != actor.tenant_id:
        raise ApiError("NOT_FOUND", 404)
    from catalog.research import version_for
    version = version_for(actor, submission.research_version_id)
    validate(submission.document, SUBMISSION_SCHEMA, "FrozenSubmission")
    return version


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


def _validate_root(actor: Account, version: ResearchVersion, account: ResearchBudget, limit: BudgetLimit,
                   submission: FrozenSubmission, candidate: FrozenCandidate) -> RuntimeRun:
    """建立 FINAL_ONLY 的唯一 VALIDATE root，並同交易固定輸入快照與 RunQueued outbox。

    最小權威 root 只承載身分；最終評估不同：派送前就必須固定 TaskInput／ExecutionManifest／
    BudgetAccount 與 Run 的來源鏈，因此改由 manifest 產生 RunRecord，再交 `enqueue` 一併落庫，
    使 root、輸入快照與 outbox 共用同一交易，且輸入雜湊不符時整批拒絕。"""
    record, task, execution, budget = documents(actor, version, account, limit, submission, candidate)
    source = Provenance.objects.get(pk=version.provenance_id, tenant_id=actor.tenant_id)
    provenance(actor, "Run", UUID(str(record["id"])), UUID(str(record["provenance_id"])), source)
    return RuntimeRun.objects.get(pk=enqueue(actor.tenant_id, record, task, execution, budget, control_only=False))


def acquire(actor: Account, submission: FrozenSubmission, candidate: FrozenCandidate) -> tuple[FinalEvaluationSlot, bool]:
    """在業務鍵上取得槽位，回傳是否由本次建立。

    既有槽位一律讀回原 `run_id`／結果，不另建評估 run；`run_id` 指向本槽位唯一的最終評估 root，
    只在新建時產生。只有需要新建槽位時才檢查提交是否仍在可派送狀態，且槽位與該 root 在同一
    savepoint 內一起成立，輸掉競態的一方整批回滾後讀回既有槽位，不會留下孤兒 run。隔離 Evaluator
    的執行、曝光帳本與結果 outbox 仍待後續切片。"""
    version = _authorized(actor, submission)
    _member(submission, candidate)
    with transaction.atomic():
        now = db_now()
        existing = _lookup(actor.tenant_id, submission.id, candidate.id, submission.metric_version)
        if existing is not None:
            return existing, False
        if submission.status not in DISPATCHABLE:
            raise ApiError("DISPATCH_STAGE_VIOLATION", 409)
        account = ResearchBudget.objects.get(research_version_id=version.id)
        limit = limit_for(account)
        try:
            with transaction.atomic():
                run = _validate_root(actor, version, account, limit, submission, candidate)
                document = slot_document(uuid4(), actor.tenant_id, submission.id, candidate.id, run.id, submission.metric_version, now)
                validate(document, SCHEMA, "FinalEvaluationSlot")
                slot = FinalEvaluationSlot.objects.create(id=UUID(document["id"]), tenant_id=actor.tenant_id,
                    submission_id=submission.id, frozen_candidate_id=candidate.id, metric_version=submission.metric_version,
                    run_id=run.id, validation_run_id=None, status="PENDING", document=document, created_at=now)
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


def _verified(actor: Account, slot: FinalEvaluationSlot, submission: FrozenSubmission,
              payload: JsonObject, result: JsonObject) -> JsonObject:
    """把呼叫端的最終結果逐欄對齊槽位與凍結輸入；身分、政策或驗證計畫不符即拒絕落庫。

    結果列的唯一鍵與不可變欄位只取自本函式核對過的欄位，因此知道 UUID 或換一份政策雜湊都不能
    讓同一份最終評估重複生效。"""
    try:
        validate(result, SCHEMA, "ValidationRun")
    except ValidationError as error:
        raise ApiError("INVALID_SCHEMA", 422) from error
    policy = submission.document["evaluation_policy_hash"]
    if result["evaluation_policy_hash"] != policy or payload["evaluation_policy_hash"] != policy:
        raise ApiError("EVALUATION_POLICY_MISMATCH", 409)
    expected = {"tenant_id": str(actor.tenant_id), "run_id": str(slot.run_id), "split_role": "FINAL_TEST",
        "metric_version": slot.metric_version, "submission_id": str(slot.submission_id),
        "frozen_candidate_id": str(slot.frozen_candidate_id), "fit_run_id": str(payload["fit_run_id"]),
        "observation_split_id": str(payload["observation_split_id"]),
        "verification_plan_artifact_id": str(payload["verification_plan_artifact_id"]),
        "verification_plan_hash": payload["verification_plan_hash"]}
    if any(result[key] != value for key, value in expected.items()):
        raise ApiError("INVALID_SCHEMA", 422)
    return result


def _record(actor: Account, slot: FinalEvaluationSlot, submission: FrozenSubmission,
            payload: JsonObject, result: JsonObject) -> ValidationRun:
    """核對後落庫不可變結果列；欄位只承載固定身分，結果本身只存在 document。"""
    document = _verified(actor, slot, submission, payload, result)
    return ValidationRun.objects.create(id=UUID(str(document["id"])), tenant_id=actor.tenant_id,
        run_id=slot.run_id, observation_split_id=UUID(str(document["observation_split_id"])),
        split_role=str(document["split_role"]), metric_version=str(document["metric_version"]),
        submission_id=UUID(str(document["submission_id"])), frozen_candidate_id=UUID(str(document["frozen_candidate_id"])),
        document=document, created_at=datetime.fromisoformat(str(document["created_at"])))


def settle(actor: Account, slot: FinalEvaluationSlot, status: str, result: JsonObject | None) -> FinalEvaluationSlot:
    """PENDING → COMPLETED／FAILED 單向結算；重複結算或結果引用形狀不符一律拒絕。

    `COMPLETED` 必須帶完整的最終結果文件並與槽位、凍結輸入同交易落庫；`FAILED` 必為 null 且不以新
    run 重啟已終止根。結果列、證據包、結果 outbox、槽位引用與提交聚合狀態在同一交易提交，衝突不能
    以新 UUID 繞過。"""
    if slot.tenant_id != actor.tenant_id:
        raise ApiError("NOT_FOUND", 404)
    if status not in RESULTS or (status == "COMPLETED") != (result is not None):
        raise ApiError("INVALID_SCHEMA", 422)
    with transaction.atomic():
        run = lock_run(actor.tenant_id, slot.run_id)
        locked = FinalEvaluationSlot.objects.select_for_update().get(pk=slot.id)
        if locked.status != "PENDING":
            raise ApiError("INVALID_TRANSITION", 409)
        submission = FrozenSubmission.objects.filter(pk=locked.submission_id, tenant_id=actor.tenant_id).first()
        if submission is None:
            raise ApiError("NOT_FOUND", 404)
        version = _authorized(actor, submission)
        now = db_now()
        reference: UUID | None = None
        if result is not None:
            payload = snapshot_for(run).task_input["payload"]
            validation = _record(actor, locked, submission, payload, result)
            bundle = register_validation(actor, version, run, validation.id, now)
            emit(run, "ValidationFinished", {"validation_run_id": str(validation.id),
                "evidence_bundle_id": str(bundle.id), "outcome_status": str(validation.document["outcome_status"])}, now)
            save_run(run)
            reference = validation.id
        document = dict(locked.document)
        document["status"] = status
        document["validation_run_id"] = None if reference is None else str(reference)
        validate(document, SCHEMA, "FinalEvaluationSlot")
        FinalEvaluationSlot.objects.filter(pk=locked.id).update(status=status, validation_run_id=reference, document=document)
        target = _aggregate(actor.tenant_id, locked.submission_id, locked.metric_version)
        if submission.status != target:
            _advance(submission, target, now)
        locked.status, locked.validation_run_id, locked.document = status, reference, document
        return locked
