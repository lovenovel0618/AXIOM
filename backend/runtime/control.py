"""Transactional root INGEST control; business execution stays disabled."""
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid4
from django.db import transaction
from runtime.contracts import JsonObject, identity_hash
from runtime.models import InputSnapshot, RuntimeAttempt, RuntimeRun
from runtime.records import (
    CANCEL_REQUESTED, QUEUED, RUNNING, TERMINAL, ControlError, db_now, detached, emit,
    lock_run, save_attempt, save_run, snapshot_for, state_event, validate_bindings,
)

LEASE_SECONDS = 60
IMMUTABLE_KEYS = ("id", "tenant_id", "type", "research_version_id", "dataset_id", "seed", "environment_digest", "input_artifact_id", "execution_manifest_id", "budget_account_id", "research_budget_account_id", "provenance_id", "root_run_id", "parent_run_id", "is_root")


@dataclass(frozen=True)
class Lease:
    tenant_id: UUID
    run_id: UUID
    attempt_id: UUID
    generation: int
    epoch: int
    worker_id: str


def _initial(record: JsonObject, budget: JsonObject) -> None:
    required: JsonObject = {"status": QUEUED, "revision": 0, "active_attempt_id": None, "lease_generation": 0, "cancellation_epoch": 0, "root_epoch_at_dispatch": 0, "cancel_requested_at": None, "dispatch_stage": "SEARCH_OPEN", "phase": None, "stop_reason": None, "evidence_bundle_ids": [], "diagnostic_artifact_ids": [], "research_trace_artifact_ids": [], "skipped_phases": [], "outcome_status": None, "current_event_cursor": f"RUN:{record['id']}:0"}
    if any(record[key] != value for key, value in required.items()):
        raise ValueError("New root must have pristine queued state")
    if budget["status"] != "OPEN" or budget["research_budget_account_id"] is not None or budget["reservations"]:
        raise ValueError("New INGEST budget must be open and unreserved")
    if any(value != 0 for value in budget["usage"].values()) or record["budget_usage"] != budget["usage"]:
        raise ValueError("New root usage must be zero")


def enqueue(tenant_id: UUID, record: JsonObject, task: JsonObject, execution: JsonObject, budget: JsonObject) -> UUID:
    record, task, execution, budget = map(detached, [record, task, execution, budget])
    validate_bindings(record, task, execution, budget)
    _initial(record, budget)
    if record["tenant_id"] != str(tenant_id):
        raise ValueError("Tenant binding mismatch")
    digest = identity_hash([task, execution, budget])
    with transaction.atomic():
        now = db_now()
        policy = execution["retry_policy"]
        horizon = budget["limit"]["wall_seconds"] + policy["max_attempts"] * (policy["queue_timeout_seconds"] + policy["backoff_max_seconds"])
        try:
            if timedelta(seconds=horizon) > datetime.max.replace(tzinfo=now.tzinfo) - now:
                raise ValueError("Timing exceeds supported datetime range")
        except OverflowError as error:
            raise ValueError("Timing exceeds supported datetime range") from error
        deadline = now + timedelta(seconds=policy["queue_timeout_seconds"])
        record["created_at"] = now.isoformat()
        run, created = RuntimeRun.objects.get_or_create(id=UUID(record["id"]), defaults={"tenant_id": tenant_id, "document": record, "queue_deadline": deadline, "available_at": now})
        run = lock_run(tenant_id, run.id)
        if not created:
            previous = snapshot_for(run)
            if previous.content_hash != digest or any(run.document[key] != record[key] for key in IMMUTABLE_KEYS):
                raise ValueError("Existing run input conflict")
            return run.id
        InputSnapshot.objects.create(run=run, task_input=task, execution=execution, budget=budget, content_hash=digest)
        emit(run, "RunQueued", {"status": QUEUED, "attempt_id": None, "generation": 0}, now)
        save_run(run)
        return run.id


def _attempt_for(run: RuntimeRun) -> RuntimeAttempt:
    return RuntimeAttempt.objects.select_for_update().get(pk=UUID(run.document["active_attempt_id"]), run=run)


def _validate_lease(run: RuntimeRun, lease: Lease, now: datetime) -> RuntimeAttempt:
    record = run.document
    if record["cancellation_epoch"] != lease.epoch or record["status"] == CANCEL_REQUESTED:
        raise ControlError("ROOT_CANCELLED")
    if record["status"] != RUNNING or record["active_attempt_id"] != str(lease.attempt_id) or record["lease_generation"] != lease.generation:
        raise ControlError("STALE_ATTEMPT")
    attempt = _attempt_for(run)
    document = attempt.document
    if document["worker_id"] != lease.worker_id or document["root_epoch_at_dispatch"] != lease.epoch or document["status"] != RUNNING:
        raise ControlError("STALE_ATTEMPT")
    if datetime.fromisoformat(document["lease_expires_at"]) <= now:
        raise ControlError("STALE_ATTEMPT")
    return attempt


def _fail(run: RuntimeRun, now: datetime, reason: str) -> None:
    run.document.update(status="FAILED", dispatch_stage="CLOSED", stop_reason=reason)
    run.document["revision"] += 1
    state_event(run, "RunFinished", now)
    save_run(run)


def _deadline_exceeded(run: RuntimeRun, snapshot: InputSnapshot, now: datetime) -> bool:
    if snapshot.budget["limit"]["wall_seconds"] <= 0:
        return True
    if run.first_started_at is None:
        return False
    return now >= run.first_started_at + timedelta(seconds=snapshot.budget["limit"]["wall_seconds"])


def claim(tenant_id: UUID, run_id: UUID, generation: int, worker_id: str) -> Lease | None:
    if not worker_id or len(worker_id) > 200:
        raise ValueError("Invalid worker identity")
    with transaction.atomic():
        run = lock_run(tenant_id, run_id)
        record, now = run.document, db_now()
        if record["status"] != QUEUED or record["lease_generation"] != generation:
            return None
        snapshot = snapshot_for(run)
        if _deadline_exceeded(run, snapshot, now):
            _fail(run, now, "BUDGET_EXHAUSTED")
            return None
        if now >= run.queue_deadline:
            _fail(run, now, "DEPENDENCY_FAILURE")
            return None
        if now < run.available_at:
            return None
        if generation >= snapshot.execution["retry_policy"]["max_attempts"]:
            _fail(run, now, "DEPENDENCY_FAILURE")
            return None
        return _start_attempt(run, worker_id, now)


def _start_attempt(run: RuntimeRun, worker_id: str, now: datetime) -> Lease:
    record = run.document
    generation = record["lease_generation"] + 1
    attempt_id = uuid4()
    document: JsonObject = {
        "kind": "AttemptRecord", "id": str(attempt_id), "tenant_id": str(run.tenant_id), "schema_version": "2.0",
        "created_at": now.isoformat(), "run_id": str(run.id), "generation": generation, "worker_id": worker_id,
        "lease_expires_at": (now + timedelta(seconds=LEASE_SECONDS)).isoformat(), "checkpoint_id": None,
        "status": RUNNING, "heartbeat_at": now.isoformat(), "started_at": now.isoformat(), "finished_at": None,
        "root_epoch_at_dispatch": record["cancellation_epoch"], "usage_sequence": 0, "actual_usage": detached(record["budget_usage"]),
    }
    save_attempt(RuntimeAttempt(id=attempt_id, run=run, generation=generation, document=document))
    record.update(status=RUNNING, active_attempt_id=str(attempt_id), lease_generation=generation)
    record["revision"] += 1
    if run.first_started_at is None:
        run.first_started_at = now
    emit(run, "RunStarted", {"status": RUNNING, "attempt_id": str(attempt_id), "generation": generation}, now)
    save_run(run)
    return Lease(run.tenant_id, run.id, attempt_id, generation, record["cancellation_epoch"], worker_id)


def heartbeat(lease: Lease) -> None:
    with transaction.atomic():
        run = lock_run(lease.tenant_id, lease.run_id)
        now = db_now()
        attempt = _validate_lease(run, lease, now)
        if _deadline_exceeded(run, snapshot_for(run), now):
            raise ControlError("STALE_ATTEMPT")
        attempt.document.update(heartbeat_at=now.isoformat(), lease_expires_at=(now + timedelta(seconds=LEASE_SECONDS)).isoformat())
        save_attempt(attempt)


def check_submission(lease: Lease) -> None:
    """Fence a future submission; this entry point writes no business result."""
    with transaction.atomic():
        run = lock_run(lease.tenant_id, lease.run_id)
        now = db_now()
        _validate_lease(run, lease, now)
        if _deadline_exceeded(run, snapshot_for(run), now):
            raise ControlError("STALE_ATTEMPT")


def cancel(tenant_id: UUID, run_id: UUID, expected_revision: int) -> None:
    with transaction.atomic():
        run = lock_run(tenant_id, run_id)
        record = run.document
        if record["status"] in TERMINAL:
            raise ControlError("RUN_ALREADY_TERMINAL")
        if record["revision"] != expected_revision:
            raise ValueError("Run revision mismatch")
        if record["status"] == CANCEL_REQUESTED:
            return
        now = db_now()
        record.update(status=CANCEL_REQUESTED, cancel_requested_at=now.isoformat(), dispatch_stage="CLOSED", stop_reason="USER_CANCELLED")
        record["cancellation_epoch"] += 1
        record["revision"] += 1
        state_event(run, "RunCancelRequested", now)
        save_run(run)


def confirm_control_stopped(tenant_id: UUID, run_id: UUID) -> None:
    """Only for control_only records: no external process has ever been started."""
    with transaction.atomic():
        run = lock_run(tenant_id, run_id)
        if not run.control_only or run.document["status"] != CANCEL_REQUESTED:
            raise ControlError("FEATURE_DISABLED")
        now = db_now()
        if run.document["active_attempt_id"] is not None:
            attempt = _attempt_for(run)
            attempt.document.update(status="CANCELLED", finished_at=now.isoformat())
            save_attempt(attempt)
        run.document.update(status="CANCELLED", dispatch_stage="CLOSED")
        run.document["revision"] += 1
        state_event(run, "RunCancelled", now)
        save_run(run)


def recover(tenant_id: UUID, run_id: UUID) -> None:
    with transaction.atomic():
        run = lock_run(tenant_id, run_id)
        now = db_now()
        if run.document["status"] in TERMINAL or run.document["status"] == CANCEL_REQUESTED:
            return
        snapshot = snapshot_for(run)
        if run.document["status"] == QUEUED:
            if _deadline_exceeded(run, snapshot, now):
                _fail(run, now, "BUDGET_EXHAUSTED")
            elif now >= run.queue_deadline:
                _fail(run, now, "DEPENDENCY_FAILURE")
            return
        attempt = _attempt_for(run)
        if _deadline_exceeded(run, snapshot, now):
            attempt.document.update(status="FAILED", finished_at=now.isoformat())
            save_attempt(attempt)
            _fail(run, now, "BUDGET_EXHAUSTED")
            return
        if datetime.fromisoformat(attempt.document["lease_expires_at"]) > now:
            return
        attempt.document.update(status="EXPIRED", finished_at=now.isoformat())
        save_attempt(attempt)
        policy = snapshot.execution["retry_policy"]
        if _deadline_exceeded(run, snapshot, now):
            _fail(run, now, "BUDGET_EXHAUSTED")
        elif run.document["lease_generation"] >= policy["max_attempts"]:
            _fail(run, now, "DEPENDENCY_FAILURE")
        else:
            _requeue(run, policy, now)


def _requeue(run: RuntimeRun, policy: JsonObject, now: datetime) -> None:
    delay = min(policy["backoff_initial_seconds"] * 2 ** (run.document["lease_generation"] - 1), policy["backoff_max_seconds"])
    run.available_at = now + timedelta(seconds=delay)
    run.queue_deadline = run.available_at + timedelta(seconds=policy["queue_timeout_seconds"])
    run.document.update(status=QUEUED, active_attempt_id=None)
    run.document["revision"] += 1
    emit(run, "RunQueued", {"status": QUEUED, "attempt_id": None, "generation": run.document["lease_generation"]}, now)
    save_run(run)
