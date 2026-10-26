"""Dedicated queue; the foundation worker never receives business file access."""
from django.conf import settings
from django.db.models import F, Q
from config.celery import app
from catalog.ingest import ingest_tick
from catalog.profile import profile_tick, recover_profile
from catalog.final_evaluator import validate_tick
from catalog.search import search_tick, recover_search
from catalog.models import ProfileBinding
from runtime.control import recover
from runtime.models import RuntimeRun
from runtime.records import db_now

app.task(name="catalog.ingest_tick", ignore_result=True)(ingest_tick)
app.task(name="catalog.profile_tick", ignore_result=True)(profile_tick)
app.task(name="catalog.validate_tick", ignore_result=True)(validate_tick)
app.task(name="catalog.search_tick", ignore_result=True)(search_tick)


def relay_ingest() -> int:
    """有界且公平地恢復／重送 INGEST；不得把 PROFILE 誤派至匯入 handler。"""
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
    """掃描未收斂的 PROFILE／未知預留，持久恢復後只派仍 QUEUED 且已啟用的任務。"""
    bindings = list(ProfileBinding.objects.filter(Q(root_budget__document__status__in=["OPEN","CLOSING"]) | Q(run__document__status__in=["QUEUED","RUNNING","CANCEL_REQUESTED"])).select_related("run").order_by(F("run__last_polled_at").asc(nulls_first=True),"run_id")[:100])
    for binding in bindings:
        recover_profile(binding.tenant_id,binding.run_id)
        RuntimeRun.objects.filter(pk=binding.run_id).update(last_polled_at=db_now())
        binding.run.refresh_from_db()
        if settings.PROFILE_ENABLED and binding.run.document["status"]=="QUEUED":
            app.send_task("catalog.profile_tick",args=[str(binding.tenant_id),str(binding.run_id),binding.run.document["lease_generation"]],queue="profile",retry=False)
    return len(bindings)


def relay_validate() -> int:
    """掃描未收斂的 VALIDATE；持久恢復後只派仍 QUEUED 且評估器已啟用的任務。"""
    rows = list(RuntimeRun.objects.filter(control_only=False, document__type="VALIDATE", document__status__in=["QUEUED", "RUNNING"]).order_by(F("last_polled_at").asc(nulls_first=True), "id")[:100])
    for row in rows:
        recover(row.tenant_id, row.id)
        RuntimeRun.objects.filter(pk=row.id).update(last_polled_at=db_now())
    if settings.VALIDATE_ENABLED:
        for row in rows:
            row.refresh_from_db()
            if row.document["status"] == "QUEUED":
                app.send_task("catalog.validate_tick", args=[str(row.tenant_id), str(row.id), row.document["lease_generation"]], queue="validate", retry=False)
    return len(rows)


def relay_search() -> int:
    """只掃有快照的 SEARCH root，公平輪詢並先恢復；離線 root 與 FIT 均不派送。"""
    rows = list(RuntimeRun.objects.filter(control_only=False, document__type="SEARCH", document__is_root=True,
        inputsnapshot__isnull=False, rootbudget__isnull=False).filter(Q(document__status__in=["QUEUED", "RUNNING", "CANCEL_REQUESTED"])
        | Q(rootbudget__document__status="CLOSING")).order_by(F("last_polled_at").asc(nulls_first=True), "id")[:100])
    for row in rows:
        recover_search(row.tenant_id, row.id)
        RuntimeRun.objects.filter(pk=row.id).update(last_polled_at=db_now())
        row.refresh_from_db()
        if settings.SEARCH_ENABLED and row.document["status"] == "QUEUED" and row.available_at <= db_now():
            app.send_task("catalog.search_tick", args=[str(row.tenant_id), str(row.id), row.document["lease_generation"]], queue="search", retry=False)
    return len(rows)
