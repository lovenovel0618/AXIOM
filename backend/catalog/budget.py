"""研究與 root 帳本的唯一扣帳入口：持久去重、預留、增量結算與失聯保守處理。

Single authority for atomic research/root reservations and cumulative receipts."""
from uuid import UUID, uuid4
from django.db import transaction
from catalog.models import SearchAttemptStop, ResearchBudget, ResearchVersion, Reservation, RootBudget, UsageReceipt
from catalog.validation import ApiError
from runtime.contracts import JsonObject, identity_hash, validate
from runtime.budget_types import COUNTERS as CUMULATIVE, BudgetLimit, UsageReport, accumulated, exceeds, read_limit, read_report, read_usage, zero_usage
from runtime.control import Lease, lock_pair
from runtime.models import RuntimeAttempt, RuntimeRun
from runtime.records import ControlError, db_now, detached, save_attempt, save_run

RUNTIME_SCHEMA = "runtime-v2.schema.json"

def initialize(version: ResearchVersion) -> ResearchBudget:
    """在建立研究版本的同一交易建立零用量帳本，固定限額不能被後續 root 重置。"""
    identity = uuid4()
    doc: JsonObject = {"kind":"ResearchBudgetAccount", "id":str(identity), "tenant_id":str(version.tenant_id), "schema_version":"2.0", "created_at":db_now().isoformat(),
        "research_version_id":str(version.id), "limit":version.document["budget"], "usage":zero_usage(), "reservations":[], "status":"OPEN"}
    validate(doc,RUNTIME_SCHEMA,"ResearchBudgetAccount")
    return ResearchBudget.objects.create(id=identity,tenant_id=version.tenant_id,research_version=version,document=doc)


def reservation_dto(row: Reservation) -> JsonObject:
    """投影剩餘預留至公開契約；內部 UNCERTAIN 仍保守視為 HELD，另由用量狀態標示未知。"""
    held = row.held
    return {"reservation_id":str(row.id),"run_id":str(row.root.run_id),"cpu_seconds":held["cpu_seconds"],"gpu_seconds":held["gpu_seconds"],"tokens":held["tokens"],
        "memory_bytes":held["memory_bytes"],"candidate_slots":held["candidate_limit"],"state":"HELD" if row.state!="RELEASED" else "RELEASED"}


def persist(research: ResearchBudget, root: RootBudget) -> None:
    """由 Reservation 權威列重建兩層預留投影並驗 schema；呼叫端須已持研究及 root 帳本鎖。"""
    loans = list(Reservation.objects.filter(root__research_budget=research).exclude(state="RELEASED").select_related("root").order_by("id"))
    research.document["reservations"] = [reservation_dto(row) for row in loans]
    root.document["reservations"] = [reservation_dto(row) for row in loans if row.root_id==root.id]
    validate(research.document,RUNTIME_SCHEMA,"ResearchBudgetAccount")
    validate(root.document,RUNTIME_SCHEMA,"BudgetAccount")
    research.save(update_fields=["document"])
    root.save(update_fields=["document"])


def capacity(account: ResearchBudget, request: object) -> None:
    """將實耗與所有未釋放預留一起檢查；未知成本拒絕新任務，記憶體不再加歷史 peak。"""
    if account.document["status"]!="OPEN":
        raise ApiError("RESEARCH_BUDGET_EXHAUSTED",429)
    loans = list(Reservation.objects.filter(root__research_budget=account).exclude(state="RELEASED"))
    if any(row.state=="UNCERTAIN" for row in loans):
        raise ApiError("RESEARCH_BUDGET_EXHAUSTED",429)
    request = read_limit(request)
    limit,usage = read_limit(account.document["limit"]),read_usage(account.document["usage"])
    held_limits = [read_limit(row.held) for row in loans]
    for resource,counter in CUMULATIVE.items():
        held = sum(held[resource] for held in held_limits)
        if usage[counter]+held+request[resource]>limit[resource]:
            raise ApiError("RESEARCH_BUDGET_EXHAUSTED",429)
    if sum(held["memory_bytes"] for held in held_limits)+request["memory_bytes"]>limit["memory_bytes"]:
        raise ApiError("RESEARCH_BUDGET_EXHAUSTED",429)


def reserve(run: RuntimeRun, root_doc: JsonObject) -> RootBudget:
    # Caller owns the root row lock; never acquire a run lock while holding these accounts.
    """呼叫端先持 root 鎖，再鎖研究帳本；原子建立 root 帳本及共用預留，額度不足整筆回滾。"""
    research = ResearchBudget.objects.select_for_update().get(pk=UUID(root_doc["research_budget_account_id"]),tenant_id=run.tenant_id)
    capacity(research,root_doc["limit"])
    root = RootBudget.objects.create(id=UUID(root_doc["id"]),tenant_id=run.tenant_id,run=run,research_budget=research,document=detached(root_doc))
    Reservation.objects.create(root=root,requested=detached(root_doc["limit"]),held=detached(root_doc["limit"]))
    persist(research,root)
    run.document["budget_reservations"] = root.document["reservations"]
    save_run(run)
    return root


def remaining(account: ResearchBudget, *, allow_closing: bool = False) -> BudgetLimit:
    """計算新 root 可用餘額；累計資源扣實耗與 held，記憶體只扣活躍預留。"""
    if account.document["status"] != "OPEN" and not (allow_closing and account.document["status"] == "CLOSING"):
        raise ApiError("RESEARCH_BUDGET_EXHAUSTED",429)
    loans = Reservation.objects.filter(root__research_budget=account).exclude(state="RELEASED")
    if loans.filter(state="UNCERTAIN").exists():
        raise ApiError("RESEARCH_BUDGET_EXHAUSTED", 429)
    held = [read_limit(row.held) for row in loans]
    limit,usage = read_limit(account.document["limit"]),read_usage(account.document["usage"])
    result = {key:max(0,limit[key]-usage[counter]-sum(row[key] for row in held)) for key,counter in CUMULATIVE.items()}
    result["memory_bytes"] = max(0,limit["memory_bytes"]-sum(row["memory_bytes"] for row in held))
    return read_limit(result)


def owned_attempt(lease: Lease, run: RuntimeRun) -> RuntimeAttempt:
    """確認原 worker／世代／epoch 的身分；遲到成本可入帳，但不能因此授權提交產物。"""
    attempt = RuntimeAttempt.objects.select_for_update().get(pk=lease.attempt_id,run=run)
    if attempt.document["worker_id"]!=lease.worker_id or attempt.generation!=lease.generation or attempt.document["root_epoch_at_dispatch"]!=lease.epoch:
        raise ControlError("STALE_ATTEMPT")
    return attempt


def checked_receipt(root: RootBudget, attempt: RuntimeAttempt, report: UsageReport) -> tuple[UsageReceipt | None, UsageReceipt | None]:
    """同時核對全域 event ID 與 attempt 序號；內容不一致拒絕，相同重送不重複扣款。"""
    digest = identity_hash(report)
    event = UsageReceipt.objects.filter(pk=UUID(report["usage_event_id"])).first()
    sequence = UsageReceipt.objects.filter(attempt=attempt,sequence=report["sequence"]).first()
    previous = UsageReceipt.objects.filter(attempt=attempt).order_by("-sequence").first()
    for row in (event,sequence):
        if row is not None and (row.root_id!=root.id or row.content_hash!=digest):
            raise ControlError("USAGE_REPORT_CONFLICT")
    return event or sequence,previous


def apply_delta(account: JsonObject, previous: object, current: object) -> None:
    """跨過 JSON 邊界後使用具體整數型別計算；倒退或溢位轉成控制衝突，不能留下部分投影。"""
    try:
        account["usage"] = accumulated(read_usage(account["usage"]),read_usage(previous),read_usage(current))
    except ValueError as error:
        raise ControlError("USAGE_REPORT_CONFLICT") from error


def exhausted(document: JsonObject) -> bool:
    """用具體限額與用量判斷超支；不裁切真實消耗，也不把超額值改成零。"""
    return exceeds(read_usage(document["usage"]),read_limit(document["limit"]))


def settle_locked(run: RuntimeRun, research: ResearchBudget, root: RootBudget, stopped: bool) -> None:
    """消耗從 held 移至實耗；只有停止證明才釋放剩餘預留，超支會關閉後續派送。

    `dispatch_stage` 與公開用量口徑只由根權威裁決，子任務僅繼承根的彙總而不覆寫。"""
    loan = Reservation.objects.select_for_update().get(root=root)
    held,requested = read_limit(loan.held),read_limit(loan.requested)
    usage = read_usage(root.document["usage"])
    for resource,counter in CUMULATIVE.items():
        held[resource] = max(0,requested[resource]-usage[counter])
    loan.held = dict(held)
    if stopped and run.document["type"] == "SEARCH" and run.document["is_root"]:
        stopped = run.document["status"] in {"SUCCEEDED", "FAILED", "CANCELLED", "CANCEL_REQUESTED"} and not RuntimeAttempt.objects.filter(run=run).exclude(pk__in=SearchAttemptStop.objects.values("attempt_id")).exists()
    if stopped or loan.state=="RELEASED":
        loan.held = dict.fromkeys(loan.requested,0)
        loan.state = "RELEASED"
        root.document["status"] = "CLOSED"
    loan.save(update_fields=["held","state"])
    if exhausted(research.document) and research.document["status"] != "CLOSED":
        research.document["status"] = "CLOSING"
    if exhausted(root.document) and loan.state!="RELEASED":
        root.document["status"] = "CLOSING"
        if run.document["is_root"]:
            run.document["dispatch_stage"] = "CLOSED"
    persist(research,root)
    if run.document["is_root"]:
        run.document["budget_usage"] = root.document["usage"]
        run.document["budget_reservations"] = root.document["reservations"]
        save_run(run)


def report_usage(lease: Lease, report: object, *, stopped: bool = False) -> bool:
    """原子記錄不可變 receipt，並由同一增量更新研究與 root 帳本。

    鎖順序為 root→run→attempt→研究帳本→root 帳本；較舊序號保存但不覆蓋最新用量。
    子任務與根共用同一 BudgetAccount 與研究帳本，因此同一增量只入帳一次；子 Run 的公開
    用量只反映自身 Attempts，不把根的彙總再加回。stopped 只供原 owning handler 在 child
    已退出／回收後使用，終態遲到結算不補 Run 事件。"""
    report = read_report(report)
    if report["tenant_id"]!=str(lease.tenant_id) or report["run_id"]!=str(lease.run_id) or report["attempt_id"]!=str(lease.attempt_id):
        raise ControlError("USAGE_REPORT_CONFLICT")
    usage = report["cumulative_usage"]
    if usage["candidates_accepted"]>usage["candidates_generated"]:
        raise ControlError("USAGE_REPORT_CONFLICT")
    with transaction.atomic():
        run, _root = lock_pair(lease.tenant_id,lease.run_id)
        attempt = owned_attempt(lease,run)
        account = UUID(run.document["budget_account_id"])
        identity = RootBudget.objects.values_list("research_budget_id",flat=True).get(pk=account)
        research = ResearchBudget.objects.select_for_update().get(pk=identity)
        root = RootBudget.objects.select_for_update().get(pk=account)
        existing,latest = checked_receipt(root,attempt,report)
        current_sequence = 0 if latest is None else latest.sequence
        if report["sequence"]<current_sequence:
            if existing is None:
                UsageReceipt.objects.create(id=UUID(report["usage_event_id"]),root=root,attempt=attempt,sequence=report["sequence"],document=report,content_hash=identity_hash(report))
            return False
        if existing is not None:
            if stopped:
                settle_locked(run,research,root,True)
                _project_child_usage(run,usage)
            return False
        previous = zero_usage() if latest is None else latest.document["cumulative_usage"]
        apply_delta(research.document,previous,usage)
        apply_delta(root.document,previous,usage)
        UsageReceipt.objects.create(id=UUID(report["usage_event_id"]),root=root,attempt=attempt,sequence=report["sequence"],document=report,content_hash=identity_hash(report))
        attempt.document.update(usage_sequence=report["sequence"],actual_usage=usage)
        save_attempt(attempt)
        settle_locked(run,research,root,stopped)
        _project_child_usage(run,usage)
        return True


def _project_child_usage(run: RuntimeRun, usage: object) -> None:
    """子 Run 只報自身 Attempts 的累計用量；根仍保有整份 BudgetAccount 彙總。"""
    if run.document["is_root"]:
        return
    run.document["budget_usage"] = dict(read_usage(usage))
    save_run(run)


def release_unstarted(run: RuntimeRun) -> None:
    """從未啟動可證明零成本；已啟動卻無停止證明則保留 UNCERTAIN，不能直接歸還預留。

    子任務不持有自身預留，因此不在此釋放根的額度。"""
    if not run.document["is_root"]:
        return
    root = RootBudget.objects.get(run=run)
    research = ResearchBudget.objects.select_for_update().get(pk=root.research_budget_id)
    root = RootBudget.objects.select_for_update().get(pk=root.id)
    known_stopped = (run.document["type"] == "SEARCH" and run.document["status"] in {"SUCCEEDED", "FAILED", "CANCELLED"}
        and not RuntimeAttempt.objects.filter(run=run).exclude(pk__in=SearchAttemptStop.objects.values("attempt_id")).exists())
    if run.first_started_at is None or known_stopped:
        settle_locked(run,research,root,True)
    elif Reservation.objects.get(root=root).state!="RELEASED":
        Reservation.objects.filter(root=root).update(state="UNCERTAIN")
        root.document["status"] = "CLOSING"
        persist(research,root)


def usage_report(lease: Lease, usage: object, sequence: int = 1) -> UsageReport:
    """由可信 handler 建立單次回報信封；先驗具體整數欄位，再交不可變 receipt 去重。"""
    identity = str(uuid4())
    return {"kind":"UsageReport","id":identity,"usage_event_id":identity,"tenant_id":str(lease.tenant_id),"schema_version":"2.0","created_at":db_now().isoformat(),
        "run_id":str(lease.run_id),"attempt_id":str(lease.attempt_id),"sequence":sequence,"cumulative_usage":read_usage(usage)}
