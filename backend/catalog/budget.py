"""Single authority for atomic research/root reservations and cumulative receipts."""
from uuid import UUID, uuid4
from django.db import transaction
from catalog.models import ResearchBudget, ResearchVersion, Reservation, RootBudget, UsageReceipt
from catalog.validation import ApiError
from runtime.contracts import JsonObject, identity_hash, validate
from runtime.control import Lease
from runtime.models import RuntimeAttempt, RuntimeRun
from runtime.records import ControlError, db_now, detached, lock_run, save_attempt, save_run

RUNTIME_SCHEMA = "runtime-v2.schema.json"
USAGE_KEYS = ("cpu_seconds", "gpu_seconds", "tokens", "peak_memory_bytes", "elapsed_wall_seconds", "candidates_generated", "candidates_accepted")
CUMULATIVE = {"cpu_seconds":"cpu_seconds", "gpu_seconds":"gpu_seconds", "tokens":"tokens", "wall_seconds":"elapsed_wall_seconds", "candidate_limit":"candidates_generated"}


def zero_usage() -> JsonObject:
    return dict.fromkeys(USAGE_KEYS, 0)


def initialize(version: ResearchVersion) -> ResearchBudget:
    identity = uuid4()
    doc: JsonObject = {"kind":"ResearchBudgetAccount", "id":str(identity), "tenant_id":str(version.tenant_id), "schema_version":"2.0", "created_at":db_now().isoformat(),
        "research_version_id":str(version.id), "limit":version.document["budget"], "usage":zero_usage(), "reservations":[], "status":"OPEN"}
    validate(doc,RUNTIME_SCHEMA,"ResearchBudgetAccount")
    return ResearchBudget.objects.create(id=identity,tenant_id=version.tenant_id,research_version=version,document=doc)


def reservation_dto(row: Reservation) -> JsonObject:
    held = row.held
    return {"reservation_id":str(row.id),"run_id":str(row.root.run_id),"cpu_seconds":held["cpu_seconds"],"gpu_seconds":held["gpu_seconds"],"tokens":held["tokens"],
        "memory_bytes":held["memory_bytes"],"candidate_slots":held["candidate_limit"],"state":"HELD" if row.state!="RELEASED" else "RELEASED"}


def persist(research: ResearchBudget, root: RootBudget) -> None:
    loans = list(Reservation.objects.filter(root__research_budget=research).exclude(state="RELEASED").select_related("root").order_by("id"))
    research.document["reservations"] = [reservation_dto(row) for row in loans]
    root.document["reservations"] = [reservation_dto(row) for row in loans if row.root_id==root.id]
    validate(research.document,RUNTIME_SCHEMA,"ResearchBudgetAccount")
    validate(root.document,RUNTIME_SCHEMA,"BudgetAccount")
    research.save(update_fields=["document"])
    root.save(update_fields=["document"])


def capacity(account: ResearchBudget, request: JsonObject) -> None:
    if account.document["status"]!="OPEN":
        raise ApiError("RESEARCH_BUDGET_EXHAUSTED",429)
    loans = list(Reservation.objects.filter(root__research_budget=account).exclude(state="RELEASED"))
    if any(row.state=="UNCERTAIN" for row in loans):
        raise ApiError("RESEARCH_BUDGET_EXHAUSTED",429)
    limit,usage = account.document["limit"],account.document["usage"]
    for resource,counter in CUMULATIVE.items():
        held = sum(row.held[resource] for row in loans)
        if usage[counter]+held+request[resource]>limit[resource]:
            raise ApiError("RESEARCH_BUDGET_EXHAUSTED",429)
    if sum(row.held["memory_bytes"] for row in loans)+request["memory_bytes"]>limit["memory_bytes"]:
        raise ApiError("RESEARCH_BUDGET_EXHAUSTED",429)


def reserve(run: RuntimeRun, root_doc: JsonObject) -> RootBudget:
    # Caller owns the root row lock; never acquire a run lock while holding these accounts.
    research = ResearchBudget.objects.select_for_update().get(pk=UUID(root_doc["research_budget_account_id"]),tenant_id=run.tenant_id)
    capacity(research,root_doc["limit"])
    root = RootBudget.objects.create(id=UUID(root_doc["id"]),tenant_id=run.tenant_id,run=run,research_budget=research,document=detached(root_doc))
    Reservation.objects.create(root=root,requested=detached(root_doc["limit"]),held=detached(root_doc["limit"]))
    persist(research,root)
    run.document["budget_reservations"] = root.document["reservations"]
    save_run(run)
    return root


def remaining(account: ResearchBudget) -> JsonObject:
    if account.document["status"]!="OPEN":
        raise ApiError("RESEARCH_BUDGET_EXHAUSTED",429)
    held = list(Reservation.objects.filter(root__research_budget=account).exclude(state="RELEASED"))
    result = {key:max(0,account.document["limit"][key]-account.document["usage"][value]-sum(row.held[key] for row in held)) for key,value in CUMULATIVE.items()}
    result["memory_bytes"] = max(0,account.document["limit"]["memory_bytes"]-sum(row.held["memory_bytes"] for row in held))
    return result


def owned_attempt(lease: Lease, run: RuntimeRun) -> RuntimeAttempt:
    attempt = RuntimeAttempt.objects.select_for_update().get(pk=lease.attempt_id,run=run)
    if attempt.document["worker_id"]!=lease.worker_id or attempt.generation!=lease.generation or attempt.document["root_epoch_at_dispatch"]!=lease.epoch:
        raise ControlError("STALE_ATTEMPT")
    return attempt


def checked_receipt(root: RootBudget, attempt: RuntimeAttempt, report: JsonObject) -> tuple[UsageReceipt | None, UsageReceipt | None]:
    digest = identity_hash(report)
    event = UsageReceipt.objects.filter(pk=UUID(report["usage_event_id"])).first()
    sequence = UsageReceipt.objects.filter(attempt=attempt,sequence=report["sequence"]).first()
    previous = UsageReceipt.objects.filter(attempt=attempt).order_by("-sequence").first()
    for row in (event,sequence):
        if row is not None and (row.root_id!=root.id or row.content_hash!=digest):
            raise ControlError("USAGE_REPORT_CONFLICT")
    return event or sequence,previous


def apply_delta(account: JsonObject, previous: JsonObject, current: JsonObject) -> None:
    for key in USAGE_KEYS:
        if current[key]<previous[key]:
            raise ControlError("USAGE_REPORT_CONFLICT")
        if key=="peak_memory_bytes":
            account["usage"][key] = max(account["usage"][key],current[key])
        else:
            account["usage"][key] += current[key]-previous[key]


def exhausted(document: JsonObject) -> bool:
    return any(document["usage"][counter]>document["limit"][key] for key,counter in CUMULATIVE.items()) or document["usage"]["peak_memory_bytes"]>document["limit"]["memory_bytes"]


def settle_locked(run: RuntimeRun, research: ResearchBudget, root: RootBudget, stopped: bool) -> None:
    loan = Reservation.objects.select_for_update().get(root=root)
    for resource,counter in CUMULATIVE.items():
        loan.held[resource] = max(0,loan.requested[resource]-root.document["usage"][counter])
    if stopped or loan.state=="RELEASED":
        loan.held = dict.fromkeys(loan.requested,0)
        loan.state = "RELEASED"
        root.document["status"] = "CLOSED"
    loan.save(update_fields=["held","state"])
    if exhausted(research.document):
        research.document["status"] = "CLOSING"
    if exhausted(root.document) and loan.state!="RELEASED":
        root.document["status"] = "CLOSING"
        run.document["dispatch_stage"] = "CLOSED"
    persist(research,root)
    run.document["budget_usage"] = root.document["usage"]
    run.document["budget_reservations"] = root.document["reservations"]
    save_run(run)


def report_usage(lease: Lease, report: JsonObject, *, stopped: bool = False) -> bool:
    validate(report,RUNTIME_SCHEMA,"UsageReport")
    if report["tenant_id"]!=str(lease.tenant_id) or report["run_id"]!=str(lease.run_id) or report["attempt_id"]!=str(lease.attempt_id):
        raise ControlError("USAGE_REPORT_CONFLICT")
    usage = report["cumulative_usage"]
    if usage["candidates_accepted"]>usage["candidates_generated"]:
        raise ControlError("USAGE_REPORT_CONFLICT")
    with transaction.atomic():
        run = lock_run(lease.tenant_id,lease.run_id)
        attempt = owned_attempt(lease,run)
        identity = RootBudget.objects.get(run=run).research_budget_id
        research = ResearchBudget.objects.select_for_update().get(pk=identity)
        root = RootBudget.objects.select_for_update().get(run=run)
        existing,latest = checked_receipt(root,attempt,report)
        current_sequence = 0 if latest is None else latest.sequence
        if report["sequence"]<current_sequence:
            if existing is None:
                UsageReceipt.objects.create(id=UUID(report["usage_event_id"]),root=root,attempt=attempt,sequence=report["sequence"],document=report,content_hash=identity_hash(report))
            return False
        if existing is not None:
            if stopped:
                settle_locked(run,research,root,True)
            return False
        previous = zero_usage() if latest is None else latest.document["cumulative_usage"]
        apply_delta(research.document,previous,usage)
        apply_delta(root.document,previous,usage)
        UsageReceipt.objects.create(id=UUID(report["usage_event_id"]),root=root,attempt=attempt,sequence=report["sequence"],document=report,content_hash=identity_hash(report))
        attempt.document.update(usage_sequence=report["sequence"],actual_usage=usage)
        save_attempt(attempt)
        settle_locked(run,research,root,stopped)
        return True


def release_unstarted(run: RuntimeRun) -> None:
    root = RootBudget.objects.get(run=run)
    research = ResearchBudget.objects.select_for_update().get(pk=root.research_budget_id)
    root = RootBudget.objects.select_for_update().get(pk=root.id)
    if run.first_started_at is None:
        settle_locked(run,research,root,True)
    elif Reservation.objects.get(root=root).state!="RELEASED":
        Reservation.objects.filter(root=root).update(state="UNCERTAIN")
        root.document["status"] = "CLOSING"
        persist(research,root)


def usage_report(lease: Lease, usage: JsonObject, sequence: int = 1) -> JsonObject:
    identity = str(uuid4())
    return {"kind":"UsageReport","id":identity,"usage_event_id":identity,"tenant_id":str(lease.tenant_id),"schema_version":"2.0","created_at":db_now().isoformat(),
        "run_id":str(lease.run_id),"attempt_id":str(lease.attempt_id),"sequence":sequence,"cumulative_usage":usage}
