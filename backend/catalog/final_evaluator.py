"""隔離 Evaluator 的 FINAL_TEST 執行段：消耗封存曝光、以凍結候選評分並單向結算唯一槽位。

Isolated FINAL_TEST execution: consume the sealed exposure, score the frozen candidate on the
final labels and settle the single forward slot by MAE against the frozen baseline.

本切片只做 A1 最小可執行段：讀 final labels、以固定分母算 MAE／RMSE 與 coverage，再以 MAE 對
`ZERO`／`FIT_MEAN` 判 `SUPPORTED`／`INSUFFICIENT_EVIDENCE`，最後交 `settle()` 落庫。配對 bootstrap、
practical margin 與完整 `AMBIGUOUS` 語意不在本切片。曝光先由讀取端提交消耗，`settle()` 內的重複
消耗因此是純 replay；結帳只走 `runtime.completion.finish`，因為 VALIDATE root 沒有研究帳本列。"""
from fractions import Fraction
import hashlib
import json
from uuid import UUID, uuid4
from django.conf import settings
from django.db import DatabaseError, transaction
from catalog.final_evaluation import settle
from catalog.ingest import Meter
from catalog.models import Account, Artifact, FrozenCandidate, FrozenSubmission, ResearchState
from catalog.sealing import authority, consume
from catalog.validation import ApiError
from mathematics.compiler import Plan, compile_dsl
from mathematics.metrics import score
from mathematics.syntax import DslError
from runtime.budget_types import integer, object_fields
from runtime.completion import confirm_business_stopped, finish
from runtime.contracts import canonical_bytes, validate
from runtime.control import Lease, check_submission, claim, recover
from runtime.models import FinalEvaluationSlot, RuntimeRun
from runtime.records import ControlError, db_now, lock_run, snapshot_for
from sealing.types import SealRejected, sequence, text

FINAL_TEST = "FINAL_TEST"
NO_EVALUABLE_ROWS = "NO_EVALUABLE_ROWS"


def _pairs(blob: bytes) -> list[tuple[float, float]]:
    """final labels 只以 canonical rows 傳遞；每列必須恰有一個輸入與一個目標。

    解析失敗一律收斂成 `INVALID_SCHEMA`，不讓 JSON 解碼例外逃出 worker；不完整的封存包
    等同不可評分，走同一條失敗結算。"""
    try:
        rows = sequence(object_fields(json.loads(blob))["rows"])
        pairs: list[tuple[float, float]] = []
        for value in rows:
            observation = object_fields(object_fields(value)["observation"])
            inputs = sequence(observation["inputs"])
            if len(inputs) != 1:
                raise ValueError("Expected exactly one input per final row")
            pairs.append((float(Fraction(text(inputs[0]))), float(Fraction(text(observation["target"])))))
        return pairs
    except (ValueError, KeyError) as error:
        raise ApiError("INVALID_SCHEMA", 422) from error


def _alias(plan: Plan) -> str:
    """FINAL_TEST 的 payload 只帶單一輸入變數；多變數 DSL 不在此切片評分。"""
    variables = sequence(object_fields(json.loads(plan.canonical))["variables"])
    if len(variables) != 1:
        raise ApiError("INVALID_SCHEMA", 422)
    return text(object_fields(variables[0])["name"])


def _parameters(value: object) -> dict[str, str]:
    """凍結參數是正規十進位字串的完整副本；非字串一律拒收，不代轉型別。"""
    return {name: text(item) for name, item in object_fields(value).items()}


def _target_mean(version_id: UUID, tenant_id: UUID) -> Fraction | None:
    """`FIT_MEAN` 的 fit 目標均值取自版本狀態指向的 QualityReport；缺失即無可比較基準。"""
    state = ResearchState.objects.filter(research_version_id=version_id).first()
    artifact = None if state is None or state.quality_id is None else Artifact.objects.filter(pk=state.quality_id, tenant_id=tenant_id).first()
    if artifact is None or artifact.content is None:
        return None
    try:
        value = object_fields(object_fields(artifact.content)["fit_summary"])["target_mean"]
    except (ValueError, KeyError):
        return None
    if not isinstance(value, str):
        return None
    try:
        return Fraction(value)
    except (ValueError, ZeroDivisionError):
        return None


def _baseline(policy: dict[str, object], target_mean: Fraction | None) -> Fraction | None:
    """baseline 只由 fit 建立：`ZERO` 為零，`FIT_MEAN` 取已登記的 fit 目標均值。"""
    return Fraction(0) if policy["baseline"] == "ZERO" else target_mean


def _outcome(policy: dict[str, object], selected: int, valid: int, mae: float | None, baseline: Fraction | None) -> str:
    """政策未定、無可估列、覆蓋不完整或候選未勝過 baseline 時，一律判定證據不足。"""
    if policy["error_model"] == "UNSPECIFIED" or policy["comparison_method"] == "NONE":
        return "INSUFFICIENT_EVIDENCE"
    if mae is None or valid == 0 or valid < selected or baseline is None:
        return "INSUFFICIENT_EVIDENCE"
    return "SUPPORTED" if mae < float(baseline) else "INSUFFICIENT_EVIDENCE"


def _digest(metrics: dict[str, float | None], counts: dict[str, object], outcome: str) -> str:
    """結果摘要以自身可重算的雜湊固定；結果本身只存在 ValidationRun 文件內。

    canonical 身分不收浮點，因此摘要前把數值統一成正規十進位字串，避免二進位浮點漂移影響身分。"""
    view: dict[str, object] = {"metrics": {name: _scalar(value) for name, value in metrics.items()},
        "counts": counts, "outcome_status": outcome}
    return hashlib.sha256(canonical_bytes(view)).hexdigest()


def _scalar(value: float | None) -> str | None:
    """摘要用的數值投影：None 保留為 null，其餘以可回讀的正規十進位字串表示。"""
    return None if value is None else format(value, ".17g")


def _evaluate(actor: Account, slot: FinalEvaluationSlot, submission: FrozenSubmission, lease: Lease) -> dict[str, object]:
    """消耗曝光後才讀 final labels；以凍結 DSL 在 final_test 上評分並判 MAE 對 baseline。

    曝光順序固定為「先消耗、後授權讀取」：`read_final` 只認已 `CONSUMED` 的封存包，授權回呼同時
    重驗 lease，因此崩潰或逾時都不會讓未消耗的 labels 外流。`settle()` 內的重複消耗是純 replay。"""
    frozen = FrozenCandidate.objects.select_related("equation_version").get(pk=slot.frozen_candidate_id, tenant_id=actor.tenant_id)
    consume(submission)
    blob = authority().read_final(str(submission.tenant_id), str(submission.sealed_test_id), str(submission.id),
        submission.snapshot_hash, lambda: check_submission(lease))
    pairs = _pairs(blob)
    plan = compile_dsl(canonical_bytes(frozen.equation_version.document["dsl"]))
    if plan.identity_hash != frozen.document["dsl_identity_hash"]:
        raise ApiError("EQUATION_MISMATCH", 409)
    scored = score(plan, _parameters(frozen.document["parameters"]), _alias(plan), pairs)
    selected, valid, failed = integer(scored["selected_count"]), integer(scored["valid_count"]), integer(scored["failed_count"])
    coverage = scored["coverage"]
    mae = None if scored["mae"] is None else float(scored["mae"])
    rmse = None if scored["rmse"] is None else float(scored["rmse"])
    policy = object_fields(submission.research_version.document["evaluation_policy"])
    baseline = _baseline(policy, _target_mean(submission.research_version_id, actor.tenant_id))
    outcome = _outcome(policy, selected, valid, mae, baseline)
    metrics: dict[str, float | None] = {"mae": mae, "rmse": rmse}
    reasons: dict[str, object] = {}
    if mae is None:
        reasons["mae"] = NO_EVALUABLE_ROWS
    if rmse is None:
        reasons["rmse"] = NO_EVALUABLE_ROWS
    counts: dict[str, object] = {"selected": selected, "valid": valid, "failed": failed}
    payload = object_fields(snapshot_for(RuntimeRun.objects.get(pk=slot.run_id)).task_input["payload"])
    identity = uuid4()
    document: dict[str, object] = {"kind": "ValidationRun", "id": str(identity), "tenant_id": str(actor.tenant_id),
        "schema_version": "2.0", "created_at": db_now().isoformat(), "run_id": str(slot.run_id),
        "fit_run_id": str(payload["fit_run_id"]), "metric_version": slot.metric_version, "metrics": metrics,
        "valid_coverage": 0.0 if coverage is None else float(Fraction(coverage)), "empirical_level": "E2",
        "proof_level": "P0", "outcome_status": outcome, "artifact_uri": f"private://evaluator/final-report/{identity}",
        "sha256": _digest(metrics, counts, outcome), "metric_reasons": reasons, "artifact_id": str(identity),
        "observation_split_id": str(payload["observation_split_id"]), "split_role": FINAL_TEST,
        "frozen_candidate_id": str(slot.frozen_candidate_id), "submission_id": str(slot.submission_id),
        "evaluation_policy_hash": payload["evaluation_policy_hash"], "selected_count": selected,
        "valid_count": valid, "failed_count": failed,
        "verification_plan_artifact_id": str(payload["verification_plan_artifact_id"]),
        "verification_plan_hash": payload["verification_plan_hash"]}
    validate(document, "runtime-v2.schema.json", "ValidationRun")
    return document


def _complete(actor: Account, slot: FinalEvaluationSlot, lease: Lease, meter: Meter, document: dict[str, object]) -> None:
    """終態提交與單向結算共用同一交易，且結算只在 `finish` 的 commit 回呼內執行。

    `finish` 直到回呼返回後才把 root 轉終態並改 `dispatch_stage`，因此結算仍看得到 `FINAL_ONLY`；
    資源超支時 `finish` 改走 failure 回呼，槽位與 root 的終態因此永遠一致。"""
    def commit() -> None:
        settle(actor, slot, "COMPLETED", document)

    def failure(_row: RuntimeRun, _code: str) -> None:
        settle(actor, slot, "FAILED", None)

    with transaction.atomic():
        finish(lease, meter.usage(), commit, failure)


def _reject(actor: Account, slot: FinalEvaluationSlot, lease: Lease, meter: Meter, code: str) -> None:
    """讀取或評分失敗時以失敗結算；曝光保守關閉，用量如實保留但不動研究帳本列。"""
    def failure(_row: RuntimeRun, _error: str) -> None:
        settle(actor, slot, "FAILED", None)

    try:
        with transaction.atomic():
            finish(lease, meter.usage(), lambda: None, failure, code)
    except ControlError:
        if not confirm_business_stopped(lease, meter.usage()):
            recover(lease.tenant_id, lease.run_id)


def validate_tick(tenant_id: str, run_id: str, generation: int) -> bool:
    """專用 evaluator worker 的唯一 VALIDATE 入口；重複派送由 claim 拒絕，失敗走一致結算。"""
    if not settings.VALIDATE_ENABLED:
        return False
    tenant, identity = UUID(tenant_id), UUID(run_id)
    slot = FinalEvaluationSlot.objects.filter(run_id=identity, tenant_id=tenant).first()
    if slot is None:
        return False
    submission = FrozenSubmission.objects.select_related("research_version__research__owner").filter(pk=slot.submission_id, tenant_id=tenant).first()
    if submission is None:
        return False
    actor = submission.research_version.research.owner
    with transaction.atomic():
        lock_run(tenant, identity)
        lease = claim(tenant, identity, generation, "validate:" + str(uuid4()))
        if lease is None:
            recover(tenant, identity)
            return False
    meter = Meter()
    try:
        document = _evaluate(actor, slot, submission, lease)
    except (ApiError, SealRejected, DslError) as error:
        _reject(actor, slot, lease, meter, error.code)
        return True
    except (OSError, DatabaseError):
        _reject(actor, slot, lease, meter, "DEPENDENCY_UNAVAILABLE")
        return True
    except ControlError:
        _reject(actor, slot, lease, meter, "STALE_ATTEMPT")
        return True
    _complete(actor, slot, lease, meter, document)
    return True
