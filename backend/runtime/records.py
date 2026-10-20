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
    """Internal domain rejection, not an HTTP error envelope."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def db_now() -> datetime:
    with connection.cursor() as cursor:
        cursor.execute("SELECT clock_timestamp()")
        row = cursor.fetchone()
    if row is None or not isinstance(row[0], datetime):
        raise RuntimeError("Database clock unavailable")
    return row[0]


def lock_run(tenant_id: UUID, run_id: UUID) -> RuntimeRun:
    return RuntimeRun.objects.select_for_update().get(tenant_id=tenant_id, pk=run_id)


def save_run(run: RuntimeRun) -> None:
    validate(run.document, RUNTIME_SCHEMA, "RunRecord")
    run.save()


def save_attempt(attempt: RuntimeAttempt) -> None:
    validate(attempt.document, RUNTIME_SCHEMA, "AttemptRecord")
    attempt.save()


def emit(run: RuntimeRun, event_type: str, payload: JsonObject, now: datetime) -> None:
    cursor = run.document["current_event_cursor"]
    sequence = int(cursor.rsplit(":", 1)[1]) + 1
    event_id = uuid4()
    event: JsonObject = {
        "event_id": str(event_id), "schema_version": "2.0", "event_type": event_type,
        "tenant_id": str(run.tenant_id), "research_version_id": None, "run_id": str(run.id),
        "stream_scope": "RUN", "stream_id": str(run.id), "sequence": sequence,
        "occurred_at": now.isoformat(), "trace_id": str(run.id), "producer_version": "t04-control-v1", "payload": payload,
    }
    validate(event, "event-v2.schema.json")
    RunEvent.objects.create(id=event_id, run=run, sequence=sequence, document=event)
    run.document["current_event_cursor"] = f"RUN:{run.id}:{sequence}"


def state_event(run: RuntimeRun, event_type: str, now: datetime) -> None:
    emit(run, event_type, {key: run.document[key] for key in ["status", "stop_reason", "revision"]}, now)


def validate_bindings(record: JsonObject, task: JsonObject, execution: JsonObject, budget: JsonObject) -> None:
    for document, filename, definition in [(record, RUNTIME_SCHEMA, "RunRecord"), (task, "task-input-v2.schema.json", None), (execution, RUNTIME_SCHEMA, "ExecutionManifest"), (budget, RUNTIME_SCHEMA, "BudgetAccount")]:
        validate(document, filename, definition)
    if record["type"] != "INGEST" or not record["is_root"] or record["parent_run_id"] is not None:
        raise ControlError("FEATURE_DISABLED")
    expected: JsonObject = {
        "root_run_id": record["id"], "research_version_id": None, "research_budget_account_id": None,
        "child_run_ids": [], "budget_reservations": [],
    }
    if any(record[key] != value for key, value in expected.items()):
        raise ValueError("Invalid INGEST root bindings")
    pairs = [(task["run_id"], record["id"]), (task["type"], record["type"]), (execution["id"], record["execution_manifest_id"]), (task["execution_manifest_id"], execution["id"]), (execution["tenant_id"], record["tenant_id"]), (execution["environment_digest"], record["environment_digest"]), (execution["seed"], record["seed"]), (execution["input_hash"], identity_hash(task)), (budget["id"], record["budget_account_id"]), (budget["tenant_id"], record["tenant_id"]), (budget["root_run_id"], record["id"])]
    if any(left != right for left, right in pairs):
        raise ValueError("Input, execution or budget identity mismatch")
    policy = execution["retry_policy"]
    if policy["backoff_max_seconds"] < policy["backoff_initial_seconds"]:
        raise ValueError("Invalid retry backoff bounds")
    for plugin in execution["plugins"]:
        if identity_hash(plugin["config"]) != plugin["config_sha256"]:
            raise ValueError("Plugin config hash mismatch")


def snapshot_for(run: RuntimeRun) -> InputSnapshot:
    snapshot = InputSnapshot.objects.get(run=run)
    validate_bindings(run.document, snapshot.task_input, snapshot.execution, snapshot.budget)
    if snapshot.content_hash != identity_hash([snapshot.task_input, snapshot.execution, snapshot.budget]):
        raise ValueError("Immutable input snapshot checksum mismatch")
    return snapshot


def detached(value: JsonObject) -> JsonObject:
    result: JsonObject = json.loads(canonical_bytes(value))
    return result


def public_run(tenant_id: UUID, run_id: UUID) -> JsonObject:
    row = RuntimeRun.objects.get(tenant_id=tenant_id, pk=run_id)
    return project(row.document, "Run")


def public_attempt(tenant_id: UUID, run_id: UUID, attempt_id: UUID) -> JsonObject:
    row = RuntimeAttempt.objects.get(pk=attempt_id, run_id=run_id, run__tenant_id=tenant_id)
    return project(row.document, "Attempt")
