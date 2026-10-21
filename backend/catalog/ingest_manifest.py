"""Real INGEST inputs, environment identities and bounded local configuration."""
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import platform
from uuid import uuid4
from django.conf import settings
from catalog.models import Account, Upload
from catalog.validation import ApiError
from ingestion.limits import ImportLimits
from runtime.contracts import JsonObject, identity_hash
from runtime.records import db_now, task_input_hash


def configured_limits() -> ImportLimits:
    """檢查明確啟用與完整 parser 設定；未設定時拒絕，沒有隱含正式容量。"""
    if not settings.INGEST_ENABLED or platform.system() != "Linux":
        raise ApiError("DEPENDENCY_UNAVAILABLE", 503)
    try:
        return ImportLimits(**json.loads(settings.INGEST_LIMITS_JSON))
    except (TypeError, ValueError) as error:
        raise ApiError("DEPENDENCY_UNAVAILABLE", 503) from error


def code_digest() -> str:
    """雜湊當版 backend 原始碼，讓快照能偵測執行中更換實作。"""
    root = Path(__file__).resolve().parents[1]
    paths = sorted(root.rglob("*.py"))
    result = [{"path": str(path.relative_to(root)), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for path in paths]
    directory = root / "contracts"
    if not directory.is_dir():
        directory = root.parent / "docs/企劃案/contracts"
    for path in sorted(directory.glob("*.json")):
        if path.name.endswith(".schema.json") or path.name == "openapi-v2.json":
            result.append({"path": "contracts/" + path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    return identity_hash(result)


def environment() -> str:
    """固定 Python／平台／套件等執行指紋，防止不同環境沿用舊快照。"""
    root = Path(__file__).resolve().parents[1]
    return identity_hash({"requirements": hashlib.sha256((root / "requirements.lock").read_bytes()).hexdigest(),
                          "python": platform.python_version(), "system": platform.system(), "machine": platform.machine(),
                          "polars": version("polars"), "django": version("Django"), "code": code_digest()})


def documents(actor: Account, upload: Upload, limits: ImportLimits, input_id: str, provenance_id: str) -> tuple[JsonObject, JsonObject, JsonObject, JsonObject]:
    """由真實 upload 產生不可變輸入、執行與資源快照，不使用測試 fixture 冒充任務。"""
    run_id, execution_id, budget_id = (str(uuid4()) for _index in range(3))
    created = db_now().isoformat()
    usage: JsonObject = dict.fromkeys(["cpu_seconds", "gpu_seconds", "tokens", "peak_memory_bytes", "elapsed_wall_seconds", "candidates_generated", "candidates_accepted"], 0)
    task: JsonObject = {"kind": "TaskInput", "schema_version": "2.0", "run_id": run_id, "type": "INGEST", "research_version_id": None,
        "observation_split_id": None, "execution_manifest_id": execution_id,
        "payload": {"upload_session_id": str(upload.id), "object_version": str(upload.object_version), "expected_sha256": upload.sha256, "import_limits": limits.document()}}
    config = {"format": upload.format, "import_limits": limits.document(), "metering": "rounded_cpu_wall_and_process_high_water_sum_upper_bound", "source_policy": "LOCAL_OWN_SYNTHETIC_ONLY"}
    execution: JsonObject = {"kind": "ExecutionManifest", "id": execution_id, "tenant_id": str(actor.tenant_id), "schema_version": "2.0", "created_at": created,
        "environment_digest": environment(), "input_hash": task_input_hash(task), "semantic_profile_hash": identity_hash(None), "seed": 0,
        "plugins": [{"plugin_id": "local-bounded-ingest", "version": "1", "code_sha256": code_digest(), "config": config, "config_sha256": identity_hash(config)}],
        "retry_policy": {"max_attempts": 1, "queue_timeout_seconds": 60, "backoff_initial_seconds": 1, "backoff_max_seconds": 1}}
    budget: JsonObject = {"kind": "BudgetAccount", "id": budget_id, "tenant_id": str(actor.tenant_id), "schema_version": "2.0", "created_at": created,
        "root_run_id": run_id, "limit": {"cpu_seconds": limits.max_parse_seconds + 20, "gpu_seconds": 0, "tokens": 0, "memory_bytes": 2147483648,
        "wall_seconds": limits.max_parse_seconds + 30, "candidate_limit": 0}, "usage": usage.copy(), "reservations": [], "status": "OPEN", "research_budget_account_id": None}
    record: JsonObject = {"kind": "RunRecord", "id": run_id, "tenant_id": str(actor.tenant_id), "schema_version": "2.0", "created_at": created,
        "research_version_id": None, "dataset_id": str(upload.dataset_id), "type": "INGEST", "status": "QUEUED", "revision": 0, "seed": 0,
        "environment_digest": execution["environment_digest"], "active_attempt_id": None, "lease_generation": 0, "current_event_cursor": f"RUN:{run_id}:0",
        "budget_usage": usage.copy(), "phase": None, "stop_reason": None, "evidence_bundle_ids": [], "child_run_ids": [], "is_root": True,
        "budget_reservations": [], "parent_run_id": None, "root_run_id": run_id, "budget_account_id": budget_id, "cancel_requested_at": None,
        "cancellation_epoch": 0, "root_epoch_at_dispatch": 0, "input_artifact_id": input_id, "outcome_status": None, "skipped_phases": [],
        "dispatch_stage": "SEARCH_OPEN", "diagnostic_artifact_ids": [], "research_budget_account_id": None, "provenance_id": provenance_id,
        "execution_manifest_id": execution_id, "research_trace_artifact_ids": []}
    return record, task, execution, budget
