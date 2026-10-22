"""Shared record persistence, input binding and database clock helpers."""
from datetime import datetime
import json
from uuid import UUID, uuid4
from django.db import connection
from runtime.contracts import JsonObject, canonical_bytes, identity_hash, project, validate
from runtime.models import InputSnapshot, RunEvent, RuntimeAttempt, RuntimeRun

RUNTIME_SCHEMA = "runtime-v2.schema.json"
QUEUED = "QUEUED"
RUNNING = "RUNNING"
CANCEL_REQUESTED = "CANCEL_REQUESTED"
TERMINAL = {"SUCCEEDED", "FAILED", "CANCELLED"}


class ControlError(ValueError):
    """控制協定錯誤只攜穩定代碼，避免洩漏內部例外。"""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def db_now() -> datetime:
    """以資料庫時鐘裁決 lease 與事件，避免不同程序本機時鐘不一致。"""
    with connection.cursor() as cursor:
        cursor.execute("SELECT clock_timestamp()")
        row = cursor.fetchone()
    if row is None or not isinstance(row[0], datetime):
        raise RuntimeError("Database clock unavailable")
    return row[0]


def lock_run(tenant_id: UUID, run_id: UUID) -> RuntimeRun:
    """以租戶及 root ID 取得列鎖；所有狀態與帳本操作遵守此入口的鎖順序。"""
    return RuntimeRun.objects.select_for_update().get(tenant_id=tenant_id, pk=run_id)


def save_run(run: RuntimeRun) -> None:
    """保存前驗公開／內部契約，資料庫 guard 再保護不可變身分與合法變動。"""
    validate(run.document, RUNTIME_SCHEMA, "RunRecord")
    run.save()


def save_attempt(attempt: RuntimeAttempt) -> None:
    """保存前驗 attempt 契約，避免持久化半份 lease 或不一致用量。"""
    validate(attempt.document, RUNTIME_SCHEMA, "AttemptRecord")
    attempt.save()


def producer_for(run: RuntimeRun) -> str:
    """按實際業務選事件 producer，不把 PROFILE 標成 INGEST 或控制探針。"""
    if run.control_only:
        return "t04-control-v1"
    if run.document["type"]=="PROFILE":
        return "t07-profile-v1"
    if run.document["type"]=="REVOKE":
        return "t07-revoke-v1"
    return "t07-ingest-v1"


def emit(run: RuntimeRun, event_type: str, payload: JsonObject, now: datetime) -> None:
    """依 stream 單調序號寫不可變事件，與狀態變動共用交易。"""
    cursor = run.document["current_event_cursor"]
    sequence = int(cursor.rsplit(":", 1)[1]) + 1
    event_id = uuid4()
    event: JsonObject = {
        "event_id": str(event_id), "schema_version": "2.0", "event_type": event_type,
        "tenant_id": str(run.tenant_id), "research_version_id": run.document["research_version_id"], "run_id": str(run.id),
        "stream_scope": "RUN", "stream_id": str(run.id), "sequence": sequence,
        "occurred_at": now.isoformat(), "trace_id": str(run.id), "producer_version": producer_for(run), "payload": payload,
    }
    validate(event, "event-v2.schema.json")
    RunEvent.objects.create(id=event_id, run=run, sequence=sequence, document=event)
    run.document["current_event_cursor"] = f"RUN:{run.id}:{sequence}"


def state_event(run: RuntimeRun, event_type: str, now: datetime) -> None:
    """以最新狀態與 revision 產生 Run 事件，避免事件與快照不一致。"""
    emit(run, event_type, {key: run.document[key] for key in ["status", "stop_reason", "revision"]}, now)


def task_input_hash(task: JsonObject) -> str:
    """計算輸入的 canonical 身分；非安全整數與非 JSON 值一律拒絕。"""
    return identity_hash({key: value for key, value in task.items() if key != "execution_manifest_id"})


def research_bindings(record: JsonObject, task: JsonObject, execution: JsonObject, budget: JsonObject) -> None:
    """核對 PROFILE 的版本、語意、切分及研究帳本引用；INGEST 不得偽裝成研究 root。"""
    if record["type"] == "INGEST" and (record["research_version_id"] is not None or record["research_budget_account_id"] is not None):
        raise ValueError("Invalid INGEST research binding")
    if task["research_version_id"] != record["research_version_id"] or budget["research_budget_account_id"] != record["research_budget_account_id"]:
        raise ValueError("Research account/input mismatch")
    if record["type"] == "PROFILE":
        if execution["retry_policy"]["max_attempts"] != 1:
            raise ValueError("PROFILE retry policy must preserve unknown-cost fencing")
        if task["observation_split_id"] != task["payload"]["observation_split"]["id"] or execution["semantic_profile_hash"] != identity_hash(task["payload"]["semantic_profile"]):
            raise ValueError("PROFILE semantic/split binding mismatch")


def validate_bindings(record: JsonObject, task: JsonObject, execution: JsonObject, budget: JsonObject) -> None:
    """驗 root、task、manifest、budget 的交叉身分與雜湊，僅放行目前已實作的根任務。"""
    for document, filename, definition in [(record, RUNTIME_SCHEMA, "RunRecord"), (task, "task-input-v2.schema.json", None), (execution, RUNTIME_SCHEMA, "ExecutionManifest"), (budget, RUNTIME_SCHEMA, "BudgetAccount")]:
        validate(document, filename, definition)
    if record["type"] not in {"INGEST", "PROFILE", "REVOKE"} or not record["is_root"] or record["parent_run_id"] is not None:
        raise ControlError("FEATURE_DISABLED")
    expected: JsonObject = {
        "root_run_id": record["id"], "child_run_ids": [],
    }
    if any(record[key] != value for key, value in expected.items()):
        raise ValueError("Invalid root bindings")
    research_bindings(record,task,execution,budget)
    input_digest = identity_hash(task) if all(plugin["plugin_id"] == "t04-control-only" for plugin in execution["plugins"]) else task_input_hash(task)
    pairs = [(task["run_id"], record["id"]), (task["type"], record["type"]), (execution["id"], record["execution_manifest_id"]), (task["execution_manifest_id"], execution["id"]), (execution["tenant_id"], record["tenant_id"]), (execution["environment_digest"], record["environment_digest"]), (execution["seed"], record["seed"]), (execution["input_hash"], input_digest), (budget["id"], record["budget_account_id"]), (budget["tenant_id"], record["tenant_id"]), (budget["root_run_id"], record["id"])]
    if any(left != right for left, right in pairs):
        raise ValueError("Input, execution or budget identity mismatch")
    policy = execution["retry_policy"]
    if policy["backoff_max_seconds"] < policy["backoff_initial_seconds"]:
        raise ValueError("Invalid retry backoff bounds")
    for plugin in execution["plugins"]:
        if identity_hash(plugin["config"]) != plugin["config_sha256"]:
            raise ValueError("Plugin config hash mismatch")


def snapshot_for(run: RuntimeRun) -> InputSnapshot:
    """讀固定輸入快照並驗完整身分，不能用可變配置覆蓋已派送任務。"""
    snapshot = InputSnapshot.objects.get(run=run)
    validate_bindings(run.document, snapshot.task_input, snapshot.execution, snapshot.budget)
    if snapshot.content_hash != identity_hash([snapshot.task_input, snapshot.execution, snapshot.budget]):
        raise ValueError("Immutable input snapshot checksum mismatch")
    return snapshot


def detached(value: JsonObject) -> JsonObject:
    """以 JSON 深拷貝斷開可變引用，避免修改公開投影時連帶改動權威快照。"""
    result: JsonObject = json.loads(canonical_bytes(value))
    return result


def public_run(tenant_id: UUID, run_id: UUID) -> JsonObject:
    """只投影 Run 公開欄位，保留內部 fencing／輸入快照的存取邊界。"""
    row = RuntimeRun.objects.get(tenant_id=tenant_id, pk=run_id)
    return project(row.document, "Run")


def public_attempt(tenant_id: UUID, run_id: UUID, attempt_id: UUID) -> JsonObject:
    """只回公開 attempt 投影，不讓內部控制資料流至一般讀取。"""
    row = RuntimeAttempt.objects.get(pk=attempt_id, run_id=run_id, run__tenant_id=tenant_id)
    return project(row.document, "Attempt")
