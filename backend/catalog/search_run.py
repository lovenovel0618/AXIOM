"""最小權威 SEARCH／FIT root run：只承載身分，不派送、不建快照、不建帳本列。

Minimal authoritative SEARCH/FIT roots; identity only, excluded from every relay."""
from datetime import timedelta
from uuid import uuid4
from catalog.ingest_manifest import environment
from catalog.models import Account, EquationVersion, Provenance, ResearchBudget, ResearchVersion
from catalog.services import provenance
from runtime.budget_types import zero_usage
from runtime.contracts import JsonObject, validate
from runtime.models import RuntimeRun
from runtime.records import db_now

QUEUE_SECONDS = 60
KINDS = ("SEARCH", "FIT")


def create(actor: Account, version: ResearchVersion, account: ResearchBudget, kind: str, equation_version: EquationVersion | None = None) -> RuntimeRun:
    """建立最小權威 root run 列；呼叫端須自行開啟交易。

    `SEARCH`／`FIT` 不走 `runtime.control.enqueue`（該入口只放行 INGEST／PROFILE），而是直接建立
    `control_only=False`、狀態停在 `QUEUED` 的 root 列：不建 attempt、不建 InputSnapshot、不建
    RootBudget／Reservation，`catalog.tasks` 的兩個 relay 也都不掃這些型別，故不會被派送。
    `budget_account_id`／`input_artifact_id`／`execution_manifest_id` 是 schema 必填的身分欄位，
    本批刻意不建立對應的帳本、快照與 manifest 列，因此保留為未落庫的 UUID，代表「沒有預留、
    沒有固定輸入、沒有可派送 manifest」，而不是宣稱它們存在。"""
    if kind not in KINDS:
        raise ValueError("Invalid SEARCH/FIT root kind")
    if (equation_version is None) != (kind == "SEARCH"):
        raise ValueError("Only FIT roots bind an equation version")
    now = db_now()
    run_id, provenance_id, budget_id, input_id, execution_id = (uuid4() for _index in range(5))
    record: JsonObject = {"kind": "RunRecord", "id": str(run_id), "tenant_id": str(actor.tenant_id), "schema_version": "2.0", "created_at": now.isoformat(),
        "research_version_id": str(version.id), "dataset_id": None, "type": kind, "status": "QUEUED", "revision": 0,
        "seed": version.document["observation_split"]["seed"], "environment_digest": environment(), "active_attempt_id": None, "lease_generation": 0,
        "current_event_cursor": f"RUN:{run_id}:0", "budget_usage": zero_usage(), "phase": None, "stop_reason": None, "evidence_bundle_ids": [], "child_run_ids": [],
        "is_root": True, "budget_reservations": [], "parent_run_id": None, "root_run_id": str(run_id), "budget_account_id": str(budget_id), "cancel_requested_at": None,
        "cancellation_epoch": 0, "root_epoch_at_dispatch": 0, "input_artifact_id": str(input_id), "outcome_status": None, "skipped_phases": [],
        "dispatch_stage": "SEARCH_OPEN", "diagnostic_artifact_ids": [], "research_budget_account_id": str(account.id), "provenance_id": str(provenance_id),
        "execution_manifest_id": str(execution_id), "research_trace_artifact_ids": []}
    if equation_version is not None:
        record["equation_version_id"] = str(equation_version.id)
    validate(record, "runtime-v2.schema.json", "RunRecord")
    source = Provenance.objects.get(pk=version.provenance_id, tenant_id=actor.tenant_id)
    provenance(actor, "Run", run_id, provenance_id, source)
    return RuntimeRun.objects.create(id=run_id, tenant_id=actor.tenant_id, document=record, control_only=False,
        queue_deadline=now + timedelta(seconds=QUEUE_SECONDS), available_at=now)
