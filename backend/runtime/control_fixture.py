"""Fresh synthetic control data; these references never represent real uploads."""
from datetime import datetime, timezone
from uuid import uuid4
from runtime.contracts import JsonObject, identity_hash


def bundle() -> tuple[JsonObject, JsonObject, JsonObject, JsonObject]:
    run_id, tenant_id, execution_id, budget_id = (str(uuid4()) for _ in range(4))
    created_at = datetime.now(timezone.utc).isoformat()
    usage: JsonObject = dict.fromkeys(["cpu_seconds", "gpu_seconds", "tokens", "peak_memory_bytes", "elapsed_wall_seconds", "candidates_generated", "candidates_accepted"], 0)
    task: JsonObject = {
        "kind": "TaskInput", "schema_version": "2.0", "run_id": run_id, "type": "INGEST", "research_version_id": None,
        "observation_split_id": None, "execution_manifest_id": execution_id,
        "payload": {"upload_session_id": str(uuid4()), "object_version": "synthetic-control-only", "expected_sha256": "0" * 64,
                    "import_limits": {"max_rows": 10, "max_columns": 2, "max_cell_utf8_bytes": 64, "max_decoded_bytes": 1024, "max_parse_seconds": 5}},
    }
    execution: JsonObject = {
        "kind": "ExecutionManifest", "id": execution_id, "tenant_id": tenant_id, "schema_version": "2.0", "created_at": created_at,
        "environment_digest": "0" * 64, "input_hash": identity_hash(task), "semantic_profile_hash": "0" * 64, "seed": 0,
        "plugins": [{"plugin_id": "t04-control-only", "version": "1", "code_sha256": "0" * 64, "config": {}, "config_sha256": identity_hash({})}],
        "retry_policy": {"max_attempts": 3, "queue_timeout_seconds": 30, "backoff_initial_seconds": 1, "backoff_max_seconds": 4},
    }
    budget: JsonObject = {
        "kind": "BudgetAccount", "id": budget_id, "tenant_id": tenant_id, "schema_version": "2.0", "created_at": created_at, "root_run_id": run_id,
        "limit": {"cpu_seconds": 10, "gpu_seconds": 0, "tokens": 0, "memory_bytes": 67108864, "wall_seconds": 300, "candidate_limit": 0},
        "usage": usage.copy(), "reservations": [], "status": "OPEN", "research_budget_account_id": None,
    }
    record: JsonObject = {
        "kind": "RunRecord", "id": run_id, "tenant_id": tenant_id, "schema_version": "2.0", "created_at": created_at,
        "research_version_id": None, "dataset_id": str(uuid4()), "type": "INGEST", "status": "QUEUED", "revision": 0, "seed": 0,
        "environment_digest": execution["environment_digest"], "active_attempt_id": None, "lease_generation": 0, "current_event_cursor": f"RUN:{run_id}:0",
        "budget_usage": usage.copy(), "phase": None, "stop_reason": None, "evidence_bundle_ids": [], "child_run_ids": [], "is_root": True,
        "budget_reservations": [], "parent_run_id": None, "root_run_id": run_id, "budget_account_id": budget_id, "cancel_requested_at": None,
        "cancellation_epoch": 0, "root_epoch_at_dispatch": 0, "input_artifact_id": str(uuid4()), "outcome_status": None, "skipped_phases": [],
        "dispatch_stage": "SEARCH_OPEN", "diagnostic_artifact_ids": [], "research_budget_account_id": None, "provenance_id": str(uuid4()),
        "execution_manifest_id": execution_id, "research_trace_artifact_ids": [],
    }
    return record, task, execution, budget
