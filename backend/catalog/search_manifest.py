"""固定 SEARCH 輸入、投影 recipe、策略 registry、來源與容量；引用皆有實體產物。"""
from catalog.models import Account, ResearchBudget, ResearchVersion
from catalog.profile_manifest import documents as profile_documents, MEMORY
from catalog.search_limits import SearchLimits
from catalog.budget import remaining
from catalog.validation import ApiError
from mathematics.search import STRATEGIES
from runtime.budget_types import BudgetLimit, read_limit, LIMIT_KEYS
from runtime.records import task_input_hash
from runtime.contracts import identity_hash

def strategy_ids() -> list[str]:
    """從固定 registry 產生新的版本清單，呼叫端不能改寫權威 tuple。"""
    return [strategy.family.lower() + "@1" for strategy in STRATEGIES]


def limit_for(account: ResearchBudget, requested: object, limits: SearchLimits) -> BudgetLimit:
    """預留含解析與三族執行的完整容量；候選額度不可用零預留掩蓋實際搜尋。"""
    available = remaining(account)
    minimum = 30 + 3 * limits.max_strategy_seconds
    limit = read_limit(requested) if requested is not None else read_limit({
        "cpu_seconds": min(available["cpu_seconds"], minimum + 15),
        "wall_seconds": min(available["wall_seconds"], minimum + 30),
        "memory_bytes": MEMORY, "gpu_seconds": 0, "tokens": 0,
        "candidate_limit": min(available["candidate_limit"], limits.max_candidates)})
    configured = read_limit(account.document["limit"])
    if (any(limit[key] > configured[key] for key in LIMIT_KEYS) or limit["memory_bytes"] < MEMORY
            or limit["cpu_seconds"] < minimum or limit["wall_seconds"] < minimum + 10
            or limit["cpu_seconds"] > 300 or limit["wall_seconds"] > 300 or limit["candidate_limit"] < 1):
        raise ApiError("RUN_BUDGET_EXHAUSTED", 429)
    return limit


def documents(actor: Account, version: ResearchVersion, account: ResearchBudget, limit: BudgetLimit,
              limits: SearchLimits, input_id: str, provenance_id: str, projection_id: str,
              seed: int) -> tuple[dict[str, object], dict[str, object], dict[str, object], dict[str, object]]:
    """沿用既有 root 身分生成器，重建 SEARCH payload 與完整快照雜湊。"""
    record, task, execution, budget = profile_documents(actor, version, account, limit, limits.parsing(), input_id, provenance_id)
    record.update(type="SEARCH", seed=seed)
    task.update(type="SEARCH", payload={"observation_split_id": task["observation_split_id"],
        "projection_artifact_id": projection_id, "strategies": strategy_ids()})
    config = execution["plugins"][0]["config"]
    config.update(search_limits=limits.document(), capacity_policy="local-search-v1", actor_id=str(actor.id))
    execution.update(input_hash=task_input_hash(task), seed=seed)
    execution["plugins"][0].update(plugin_id="local-bounded-search", config_sha256=identity_hash(config))
    # 一次崩潰允許續跑；原 attempt 未證明停止的成本仍保留，絕不重置帳本。
    execution["retry_policy"]["max_attempts"] = 2
    return record, task, execution, budget
