"""資源帳本的具體型別與驗證邊界，避免 JSON 的 Any 滲入扣帳算術。

資料庫與 HTTP 雖以 JSON 傳輸，核心運算只接收七種整數用量與六種整數限額。
讀取時逐欄檢查，特別排除 Python 中屬於 int 子類別的 bool；不靠 cast 冒充驗證。
"""
from collections.abc import Mapping
from typing import Literal, TypedDict, cast
from runtime.contracts import validate

UsageKey = Literal["cpu_seconds", "gpu_seconds", "tokens", "peak_memory_bytes", "elapsed_wall_seconds", "candidates_generated", "candidates_accepted"]
LimitKey = Literal["cpu_seconds", "gpu_seconds", "tokens", "memory_bytes", "wall_seconds", "candidate_limit"]
USAGE_KEYS: tuple[UsageKey, ...] = ("cpu_seconds", "gpu_seconds", "tokens", "peak_memory_bytes", "elapsed_wall_seconds", "candidates_generated", "candidates_accepted")
LIMIT_KEYS: tuple[LimitKey, ...] = ("cpu_seconds", "gpu_seconds", "tokens", "memory_bytes", "wall_seconds", "candidate_limit")
COUNTERS: Mapping[LimitKey, UsageKey] = {"cpu_seconds":"cpu_seconds", "gpu_seconds":"gpu_seconds", "tokens":"tokens", "wall_seconds":"elapsed_wall_seconds", "candidate_limit":"candidates_generated"}


class BudgetUsage(TypedDict):
    """實際累計用量；peak 是歷史最大值，其餘欄位為累計量。"""
    cpu_seconds: int
    gpu_seconds: int
    tokens: int
    peak_memory_bytes: int
    elapsed_wall_seconds: int
    candidates_generated: int
    candidates_accepted: int


class BudgetLimit(TypedDict):
    """根任務與研究版本的資源上限，欄位名稱沿用已凍結契約。"""
    cpu_seconds: int
    gpu_seconds: int
    tokens: int
    memory_bytes: int
    wall_seconds: int
    candidate_limit: int


class UsageReport(TypedDict):
    """不可變回報信封；event 去重鍵與 attempt 序號都有具體型別。"""
    kind: Literal["UsageReport"]
    id: str
    usage_event_id: str
    tenant_id: str
    schema_version: Literal["2.0"]
    created_at: str
    run_id: str
    attempt_id: str
    sequence: int
    cumulative_usage: BudgetUsage


def object_fields(value: object) -> dict[str, object]:
    """將未知 JSON 物件收斂為字串鍵；cast 僅描述已檢查的容器形狀。"""
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object")
    result: dict[str, object] = {}
    for key, item in cast(dict[object, object], value).items():
        if not isinstance(key, str):
            raise ValueError("Expected string keys")
        result[key] = item
    return result


def integer(value: object) -> int:
    """只允許契約可精確表示的非負整數，不把 bool／浮點／字串當用量。"""
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 2**53-1:
        raise ValueError("Expected a nonnegative safe integer")
    return value


def read_usage(value: object) -> BudgetUsage:
    """驗完完整鍵集合才建立 TypedDict，阻擋漏欄、錯字及非法候選分母。"""
    row = object_fields(value)
    if set(row) != set(USAGE_KEYS):
        raise ValueError("Invalid usage fields")
    result: BudgetUsage = {"cpu_seconds":integer(row["cpu_seconds"]), "gpu_seconds":integer(row["gpu_seconds"]), "tokens":integer(row["tokens"]),
        "peak_memory_bytes":integer(row["peak_memory_bytes"]), "elapsed_wall_seconds":integer(row["elapsed_wall_seconds"]),
        "candidates_generated":integer(row["candidates_generated"]), "candidates_accepted":integer(row["candidates_accepted"])}
    if result["candidates_accepted"] > result["candidates_generated"]:
        raise ValueError("Accepted candidates exceed generated candidates")
    return result


def read_limit(value: object) -> BudgetLimit:
    """讀取六種限額；執行所需的正值與容量政策另由派送層檢查。"""
    row = object_fields(value)
    if set(row) != set(LIMIT_KEYS):
        raise ValueError("Invalid limit fields")
    return {"cpu_seconds":integer(row["cpu_seconds"]), "gpu_seconds":integer(row["gpu_seconds"]), "tokens":integer(row["tokens"]),
        "memory_bytes":integer(row["memory_bytes"]), "wall_seconds":integer(row["wall_seconds"]), "candidate_limit":integer(row["candidate_limit"])}


def read_report(value: object) -> UsageReport:
    """先驗完整離線 schema，再轉具體信封；UUID／日期格式由 schema 拒絕。"""
    validate(value, "runtime-v2.schema.json", "UsageReport")
    row = object_fields(value)
    return {"kind":"UsageReport", "id":str(row["id"]), "usage_event_id":str(row["usage_event_id"]), "tenant_id":str(row["tenant_id"]),
        "schema_version":"2.0", "created_at":str(row["created_at"]), "run_id":str(row["run_id"]), "attempt_id":str(row["attempt_id"]),
        "sequence":integer(row["sequence"]), "cumulative_usage":read_usage(row["cumulative_usage"])}


def zero_usage() -> BudgetUsage:
    """建立獨立的七欄零用量，避免共享可變預設值。"""
    return {"cpu_seconds":0, "gpu_seconds":0, "tokens":0, "peak_memory_bytes":0, "elapsed_wall_seconds":0, "candidates_generated":0, "candidates_accepted":0}


def accumulated(account: BudgetUsage, previous: BudgetUsage, current: BudgetUsage) -> BudgetUsage:
    """只加入新累計回報的增量；歷史 peak 取 max，倒退必須拒絕而非歸零。"""
    result = account.copy()
    for key in USAGE_KEYS:
        if current[key] < previous[key]:
            raise ValueError("Usage cannot decrease")
        result[key] = max(account[key],current[key]) if key == "peak_memory_bytes" else account[key]+current[key]-previous[key]
        integer(result[key])
    return result


def exceeds(usage: BudgetUsage, limit: BudgetLimit) -> bool:
    """實耗可以超支並須保留；本函式只判斷是否應阻擋後續派送。"""
    return any(usage[counter] > limit[key] for key,counter in COUNTERS.items()) or usage["peak_memory_bytes"] > limit["memory_bytes"]
