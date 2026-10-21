"""Dedicated queue; the foundation worker never receives business file access."""
from django.conf import settings
from django.db.models import F, Q
from config.celery import app
from catalog.ingest import ingest_tick
from catalog.profile import profile_tick, recover_profile
from catalog.models import ProfileBinding
from runtime.control import recover
from runtime.models import RuntimeRun
from runtime.records import db_now

app.task(name="catalog.ingest_tick", ignore_result=True)(ingest_tick)
app.task(name="catalog.profile_tick", ignore_result=True)(profile_tick)


def relay_ingest() -> int:
    rows = list(RuntimeRun.objects.filter(control_only=False, document__type="INGEST", document__status__in=["QUEUED", "RUNNING"]).order_by(F("last_polled_at").asc(nulls_first=True), "id")[:100])
    for row in rows:
        recover(row.tenant_id, row.id)
        RuntimeRun.objects.filter(pk=row.id).update(last_polled_at=db_now())
    if settings.INGEST_ENABLED:
        for row in rows:
            row.refresh_from_db()
            if row.document["status"] == "QUEUED":
                app.send_task("catalog.ingest_tick", args=[str(row.tenant_id), str(row.id), row.document["lease_generation"]], queue="ingest", retry=False)
    return len(rows)


def relay_profile() -> int:
    bindings = list(ProfileBinding.objects.filter(Q(root_budget__document__status__in=["OPEN","CLOSING"]) | Q(run__document__status__in=["QUEUED","RUNNING","CANCEL_REQUESTED"])).select_related("run").order_by(F("run__last_polled_at").asc(nulls_first=True),"run_id")[:100])
    for binding in bindings:
        recover_profile(binding.tenant_id,binding.run_id)
        RuntimeRun.objects.filter(pk=binding.run_id).update(last_polled_at=db_now())
        binding.run.refresh_from_db()
        if settings.PROFILE_ENABLED and binding.run.document["status"]=="QUEUED":
            app.send_task("catalog.profile_tick",args=[str(binding.tenant_id),str(binding.run_id),binding.run.document["lease_generation"]],queue="profile",retry=False)
    return len(bindings)
