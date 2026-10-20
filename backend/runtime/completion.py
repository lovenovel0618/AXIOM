"""Fenced terminal submission for the fixed business INGEST handler."""
from collections.abc import Callable
from datetime import timedelta
from django.db import transaction
from runtime.contracts import JsonObject, validate
from runtime.control import Lease, validate_lease
from runtime.models import RuntimeRun
from runtime.records import ControlError, db_now, lock_run, save_attempt, save_run, snapshot_for, state_event


def finish(lease: Lease, usage: JsonObject, commit: Callable[[], None], failure: Callable[[RuntimeRun, str], None], error_code: str | None = None) -> None:
    validate(usage, "research-v2.schema.json", "BudgetUsage")
    with transaction.atomic():
        run = lock_run(lease.tenant_id, lease.run_id)
        if run.control_only:
            raise ControlError("FEATURE_DISABLED")
        now = db_now()
        attempt = validate_lease(run, lease, now)
        limit = snapshot_for(run).budget["limit"]
        exceeded = (usage["cpu_seconds"] > limit["cpu_seconds"] or usage["peak_memory_bytes"] > limit["memory_bytes"] or
                    usage["elapsed_wall_seconds"] > limit["wall_seconds"] or run.first_started_at is None or
                    now >= run.first_started_at + timedelta(seconds=limit["wall_seconds"]))
        code = "BUDGET_EXHAUSTED" if exceeded else error_code
        if code is None:
            commit()
            status, reason = "SUCCEEDED", "COMPLETED"
        else:
            failure(run, code)
            status = "FAILED"
            reason = "BUDGET_EXHAUSTED" if exceeded else "DEPENDENCY_FAILURE"
        attempt.document.update(status=status, finished_at=now.isoformat(), actual_usage=usage, usage_sequence=1)
        run.document.update(status=status, stop_reason=reason, dispatch_stage="CLOSED", budget_usage=usage)
        run.document["revision"] += 1
        save_attempt(attempt)
        state_event(run, "RunFinished", now)
        save_run(run)


def confirm_business_stopped(lease: Lease, usage: JsonObject) -> bool:
    """Only the owning handler calls this after its parser has exited/reaped."""
    from runtime.models import RuntimeAttempt
    with transaction.atomic():
        run = lock_run(lease.tenant_id, lease.run_id)
        if run.control_only or run.document["status"] != "CANCEL_REQUESTED":
            return False
        if run.document["active_attempt_id"] != str(lease.attempt_id) or run.document["lease_generation"] != lease.generation:
            raise ControlError("STALE_ATTEMPT")
        attempt = RuntimeAttempt.objects.select_for_update().get(pk=lease.attempt_id, run=run)
        if attempt.document["worker_id"] != lease.worker_id or attempt.document["root_epoch_at_dispatch"] != lease.epoch:
            raise ControlError("STALE_ATTEMPT")
        validate(usage, "research-v2.schema.json", "BudgetUsage")
        now = db_now()
        attempt.document.update(status="CANCELLED", finished_at=now.isoformat(), actual_usage=usage, usage_sequence=1)
        run.document.update(status="CANCELLED", stop_reason="USER_CANCELLED", dispatch_stage="CLOSED", budget_usage=usage)
        run.document["revision"] += 1
        save_attempt(attempt)
        state_event(run, "RunCancelled", now)
        save_run(run)
        return True
