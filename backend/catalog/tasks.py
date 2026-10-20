"""Dedicated queue; the foundation worker never receives business file access."""
from django.conf import settings
from django.db.models import F
from config.celery import app
from catalog.ingest import ingest_tick
from runtime.control import recover
from runtime.models import RuntimeRun
from runtime.records import db_now

app.task(name="catalog.ingest_tick", ignore_result=True)(ingest_tick)


def relay_ingest() -> int:
    rows = list(RuntimeRun.objects.filter(control_only=False, document__status__in=["QUEUED", "RUNNING"]).order_by(F("last_polled_at").asc(nulls_first=True), "id")[:100])
    for row in rows:
        recover(row.tenant_id, row.id)
        RuntimeRun.objects.filter(pk=row.id).update(last_polled_at=db_now())
    if settings.INGEST_ENABLED:
        for row in rows:
            row.refresh_from_db()
            if row.document["status"] == "QUEUED":
                app.send_task("catalog.ingest_tick", args=[str(row.tenant_id), str(row.id), row.document["lease_generation"]], queue="ingest", retry=False)
    return len(rows)
