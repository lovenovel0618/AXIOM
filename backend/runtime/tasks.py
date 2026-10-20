"""Control-only Celery integration. No upload read or domain result is executed."""
import os
from uuid import UUID
from config.celery import app
from django.db.models import F
from runtime.control import Lease, claim, confirm_control_stopped, heartbeat, recover
from runtime.models import RuntimeAttempt, RuntimeRun
from runtime.records import CANCEL_REQUESTED, QUEUED, RUNNING, ControlError, db_now


def control_tick(tenant_id: str, run_id: str, generation: int) -> bool:
    tenant, identity = UUID(tenant_id), UUID(run_id)
    worker = f"control:{os.environ.get('HOSTNAME', 'local')}:{os.getpid()}"
    try:
        run = RuntimeRun.objects.get(pk=identity, tenant_id=tenant, control_only=True)
        if run.document["status"] == CANCEL_REQUESTED:
            confirm_control_stopped(tenant, identity)
        elif run.document["status"] == QUEUED:
            claim(tenant, identity, generation, worker)
        elif run.document["status"] == RUNNING:
            attempt = RuntimeAttempt.objects.get(pk=UUID(run.document["active_attempt_id"]), run=run)
            if attempt.document["worker_id"] != worker or attempt.generation != generation:
                return False
            heartbeat(Lease(tenant, identity, attempt.id, generation, attempt.document["root_epoch_at_dispatch"], worker))
        return True
    except (RuntimeRun.DoesNotExist, ControlError):
        return False


app.task(name="runtime.control_tick", ignore_result=True)(control_tick)


def relay_control() -> int:
    rows = list(RuntimeRun.objects.filter(document__status__in=[QUEUED, RUNNING, CANCEL_REQUESTED], control_only=True).order_by(F("last_polled_at").asc(nulls_first=True), "id")[:100])
    # Recover every selected row before publishing so broker failure cannot skip deadlines.
    for row in rows:
        recover(row.tenant_id, row.id)
        RuntimeRun.objects.filter(pk=row.id).update(last_polled_at=db_now())
    for row in rows:
        row.refresh_from_db()
        if row.document["status"] == QUEUED and row.available_at > db_now():
            continue
        if row.document["status"] in {QUEUED, RUNNING, CANCEL_REQUESTED}:
            app.send_task("runtime.control_tick", args=[str(row.tenant_id), str(row.id), row.document["lease_generation"]], retry=False)
    return len(rows)
