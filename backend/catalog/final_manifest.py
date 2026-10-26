"""FINAL_TEST VALIDATE 的固定輸入：凍結提交、驗證計畫與評估政策成為不可變任務身分。

Explicit FINAL_TEST TaskInput／ExecutionManifest／BudgetAccount snapshots for the isolated final
evaluation root. The evaluator execution, the exposure ledger and the final ValidationRun stay out
of this slice."""
from uuid import uuid4
from catalog.budget import remaining, zero_usage
from catalog.ingest_manifest import code_digest, environment
from catalog.models import Account, FrozenCandidate, FrozenSubmission, ResearchBudget, ResearchVersion
from catalog.validation import ApiError
from runtime.budget_types import LIMIT_KEYS, BudgetLimit, read_limit
from runtime.models import RuntimeRun
from runtime.contracts import JsonObject, identity_hash
from runtime.records import db_now, task_input_hash

PLUGIN = "isolated-final-evaluator"
MEMORY = 2 * 1024**3
REQUEST: BudgetLimit = {"cpu_seconds": 60, "gpu_seconds": 0, "tokens": 0,
    "memory_bytes": MEMORY, "wall_seconds": 300, "candidate_limit": 0}


def limit_for(account: ResearchBudget) -> BudgetLimit:
    """最終評估的固定預留需求；研究設定限額或剩餘不足以涵蓋即拒絕，不以較小假預留超賣容量。"""
    # 搜尋完成後研究為 CLOSING；僅既定最終評估可繼續，絕不重新 OPEN 或放行 CLOSED。
    finishing = RuntimeRun.objects.filter(document__type="SEARCH", document__status="SUCCEEDED",
        rootbudget__research_budget=account).exists()
    available = remaining(account, allow_closing=finishing)
    configured = read_limit(account.document["limit"])
    if any(REQUEST[key] > configured[key] for key in LIMIT_KEYS):
        raise ApiError("RUN_BUDGET_EXHAUSTED", 429)
    if any(REQUEST[key] > available[key] for key in LIMIT_KEYS):
        raise ApiError("RESEARCH_BUDGET_EXHAUSTED", 429)
    return read_limit(REQUEST)


def documents(actor: Account, version: ResearchVersion, account: ResearchBudget, limit: BudgetLimit,
              submission: FrozenSubmission, candidate: FrozenCandidate) -> tuple[JsonObject, JsonObject, JsonObject, JsonObject]:
    """產生 FINAL_TEST 的真實輸入、執行與資源快照；任一凍結引用不符即 Fail-Closed 拒絕。

    最終評估固定「同提交、同候選、同觀測切分」：`payload` 只承載凍結提交已固定的 fit run、
    切分、評估政策與驗證計畫，`split_role` 固定 `FINAL_TEST`，因此不可能在派送時換公式或換資料。"""
    split_id = str(version.document["observation_split"]["id"])
    if (submission.tenant_id != actor.tenant_id or candidate.tenant_id != actor.tenant_id
            or submission.research_version_id != version.id or candidate.dataset_version_id != version.dataset_version_id
            or str(candidate.observation_split_id) != split_id
            or str(candidate.id) not in submission.document["frozen_candidate_ids"]):
        raise ApiError("FIT_REFERENCE_MISMATCH", 409)
    policy_hash = str(submission.document["evaluation_policy_hash"])
    if policy_hash != version.document["evaluation_policy_hash"]:
        raise ApiError("EVALUATION_POLICY_MISMATCH", 409)
    run_id, execution_id, budget_id = (str(uuid4()) for _index in range(3))
    created = db_now().isoformat()
    payload: JsonObject = {"fit_run_id": str(candidate.fit_run_id), "split_role": "FINAL_TEST",
        "observation_split_id": split_id, "frozen_candidate_id": str(candidate.id), "submission_id": str(submission.id),
        "evaluation_policy_hash": policy_hash,
        "verification_plan_artifact_id": str(submission.document["verification_plan_artifact_id"]),
        "verification_plan_hash": str(submission.document["verification_plan_hash"])}
    task: JsonObject = {"kind": "TaskInput", "schema_version": "2.0", "run_id": run_id, "type": "VALIDATE",
        "research_version_id": str(version.id), "observation_split_id": split_id,
        "execution_manifest_id": execution_id, "payload": payload}
    config: JsonObject = {"capacity_policy": "isolated-final-evaluator-v1", "source_policy": "LOCAL_OWN_SYNTHETIC_ONLY",
        "sealed_test_id": str(submission.sealed_test_id), "metric_version": submission.metric_version,
        "source_sha256": version.dataset_version.sha256}
    execution: JsonObject = {"kind": "ExecutionManifest", "id": execution_id, "tenant_id": str(actor.tenant_id),
        "schema_version": "2.0", "created_at": created, "environment_digest": environment(), "input_hash": task_input_hash(task),
        "semantic_profile_hash": identity_hash(version.document["semantic_profile"]),
        "seed": version.document["observation_split"]["seed"],
        "plugins": [{"plugin_id": PLUGIN, "version": "1", "code_sha256": code_digest(), "config": config, "config_sha256": identity_hash(config)}],
        "retry_policy": {"max_attempts": 1, "queue_timeout_seconds": 60, "backoff_initial_seconds": 1, "backoff_max_seconds": 1}}
    budget: JsonObject = {"kind": "BudgetAccount", "id": budget_id, "tenant_id": str(actor.tenant_id), "schema_version": "2.0",
        "created_at": created, "root_run_id": run_id, "research_budget_account_id": str(account.id), "limit": limit,
        "usage": zero_usage(), "reservations": [], "status": "OPEN"}
    record: JsonObject = {"kind": "RunRecord", "id": run_id, "tenant_id": str(actor.tenant_id), "schema_version": "2.0",
        "created_at": created, "research_version_id": str(version.id), "dataset_id": None, "type": "VALIDATE",
        "status": "QUEUED", "revision": 0, "seed": execution["seed"], "environment_digest": execution["environment_digest"],
        "active_attempt_id": None, "lease_generation": 0, "current_event_cursor": f"RUN:{run_id}:0", "budget_usage": zero_usage(),
        "equation_version_id": str(candidate.equation_version_id), "phase": None, "stop_reason": None, "evidence_bundle_ids": [],
        "child_run_ids": [], "is_root": True, "budget_reservations": [], "parent_run_id": None, "root_run_id": run_id,
        "budget_account_id": budget_id, "cancel_requested_at": None, "cancellation_epoch": 0, "root_epoch_at_dispatch": 0,
        "input_artifact_id": execution_id, "outcome_status": None, "skipped_phases": [], "dispatch_stage": "FINAL_ONLY",
        "diagnostic_artifact_ids": [], "research_budget_account_id": str(account.id), "provenance_id": str(uuid4()),
        "execution_manifest_id": execution_id, "research_trace_artifact_ids": []}
    return record, task, execution, budget
