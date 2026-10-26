"""SEARCH 的權威派送、逐族 checkpoint 與 fenced 提交；未知 attempt 成本保留至停止證明到達。"""
from uuid import UUID, uuid4
from django.conf import settings
from django.db import DatabaseError, transaction
from catalog.artifacts import register
from catalog.budget import reserve, release_unstarted, report_usage, usage_report, persist as persist_budget
from catalog.candidates import persist_under
from catalog.ingest import Meter
from catalog.ingest_manifest import environment
from catalog.inspection import current, configuration
from catalog.models import Account, Audit, Provenance, ResearchBudget, ResearchState, ResearchVersion, Reservation, RootBudget, SearchAttemptStop
from catalog.research_state import state_for, transition
from catalog.search_limits import SearchLimits, limits_for
from catalog.search_manifest import documents, limit_for, strategy_ids
from catalog.services import provenance
from catalog.storage import LocalVersionStore, StorageRejected
from catalog.validation import ApiError
from ingestion.limits import ImportRejected
from ingestion.supervisor import inspect_research
from mathematics.search import merge_reports
from mathematics.search_process import run_strategy
from runtime.completion import finish, confirm_business_stopped
from runtime.budget_types import integer, read_usage, read_limit, exceeds
from runtime.control import Lease, claim, check_submission, recover, save_checkpoint, load_checkpoint, heartbeat
from runtime.models import RuntimeRun, RuntimeAttempt, RuntimeCheckpoint, InputSnapshot
from runtime.records import ControlError, lock_run, public_run, snapshot_for, db_now, save_run, save_attempt, state_event


class Scope:
    """產物沿研究版本綁資料集；不建立虛構的 ProfileBinding。"""
    def __init__(self, version: ResearchVersion) -> None:
        self.dataset_id = version.dataset_version.dataset_id


def enqueue_search(actor: Account, version: ResearchVersion, data: dict[str, object], revision: int) -> dict[str, object]:
    """外層 replay 已持授權鎖；新 root→狀態→帳本，revision 衝突使快照與產物全部回滾。"""
    # 先回報控制版本衝突；不能讓另一請求已占用的容量把 fencing 掩蓋成 429。
    observed = ResearchState.objects.filter(research_version=version).first()
    if (0 if observed is None else observed.revision) != revision:
        raise ApiError("REVISION_CONFLICT", 412)
    if observed is None or observed.status != "READY" or observed.active_run_id is not None:
        raise ApiError("INVALID_TRANSITION", 409)
    limits = limits_for(version)
    account = ResearchBudget.objects.get(research_version=version, tenant_id=actor.tenant_id)
    limit = limit_for(account, data.get("run_budget"), limits)
    _actor, _version, reference = current(actor.id, version.id, allow_validating=True)
    LocalVersionStore(settings.OBJECT_ROOT).verify(reference)
    input_id, source_id, projection_id = uuid4(), uuid4(), uuid4()
    seed = data["seed"]
    if type(seed) is not int or not 0 <= seed <= 2**53 - 1:
        raise ApiError("INVALID_SCHEMA", 422)
    record, task, execution, budget = documents(actor, version, account, limit, limits, str(input_id), str(source_id), str(projection_id), seed)
    source = Provenance.objects.get(pk=version.provenance_id, tenant_id=actor.tenant_id)
    provenance(actor, "Run", UUID(str(record["id"])), source_id, source)
    # 投影 artifact 是固定 recipe；只有隔離 worker 能解析原始 bytes，HTTP 不做未入帳的解析。
    split = version.document["observation_split"]
    recipe = {"kind": "SearchProjectionSource", "research_version_id": str(version.id), "dataset_version_id": str(version.dataset_version_id),
        "source_sha256": reference.sha256, "source_object_version": str(reference.version),
        "observation_split_id": split["id"], "fit": split["fit"], "development": split["development"],
        "semantic_profile": version.document["semantic_profile"], "domain": version.document["domain"]}
    register(actor, Scope(version), projection_id, recipe, source, research_version=version)
    register(actor, Scope(version), input_id, task, source, research_version=version)
    from runtime.control import enqueue
    identity = enqueue(actor.tenant_id, record, task, execution, budget, control_only=False)
    run = lock_run(actor.tenant_id, identity)
    state = state_for(version)
    if state.revision != revision:
        raise ApiError("REVISION_CONFLICT", 412)
    if state.active_run_id is not None or state.status != "READY":
        raise ApiError("INVALID_TRANSITION", 409)
    reserve(run, budget)
    state.active_run_id = identity
    transition(state, "QUEUED", "t07-search-v1")
    Audit.objects.create(tenant_id=actor.tenant_id, actor_id=actor.id, action="QUEUE_SEARCH", code="OK")
    return public_run(actor.tenant_id, identity)


def close_search(run: RuntimeRun, version: ResearchVersion) -> None:
    """根終態後收斂版本與研究帳本；未知成本只能 CLOSING，不可假報 CLOSED。"""
    state = state_for(version)
    if state.active_run_id == run.id and run.document["status"] in {"SUCCEEDED", "FAILED", "CANCELLED"}:
        state.active_run_id = None
        target = "READY" if state.seal_id is not None else "DRAFT"
        if run.document["status"] != "SUCCEEDED":
            target = "CANCELLED" if run.document["status"] == "CANCELLED" else "FAILED"
        transition(state, target, "t07-search-v1")
    account = ResearchBudget.objects.select_for_update().get(research_version=version)
    root = RootBudget.objects.select_for_update().get(run=run)
    if account.document["status"] == "CLOSED":
        return
    account.document["status"] = "CLOSING"
    if run.document["status"] != "SUCCEEDED" and not Reservation.objects.filter(root__research_budget=account).exclude(state="RELEASED").exists():
        account.document["status"] = "CLOSED"
    persist_budget(account, root)


def recover_search(tenant: UUID, identity: UUID) -> None:
    """只處理有 SEARCH 快照的 root；失聯可由 checkpoint 續跑，未停止 attempt 預留仍保留。"""
    with transaction.atomic():
        run = lock_run(tenant, identity)
        if run.document["type"] != "SEARCH" or not run.document["is_root"] or not InputSnapshot.objects.filter(run=run).exists():
            return
        version = ResearchVersion.objects.get(pk=UUID(run.document["research_version_id"]))
        recover(tenant, identity)
        run.refresh_from_db()
        if RuntimeAttempt.objects.filter(run=run, document__status="EXPIRED").exclude(pk__in=SearchAttemptStop.objects.values("attempt_id")).exists():
            release_unstarted(run)
        if run.document["status"] in {"FAILED", "CANCELLED"}:
            release_unstarted(run)
            close_search(run, version)
        elif run.document["status"] == "CANCEL_REQUESTED":
            if run.first_started_at is None or not RuntimeAttempt.objects.filter(run=run).exclude(pk__in=SearchAttemptStop.objects.values("attempt_id")).exists():
                if run.document["active_attempt_id"] is not None:
                    attempt = RuntimeAttempt.objects.select_for_update().get(pk=UUID(run.document["active_attempt_id"]))
                    attempt.document.update(status="CANCELLED", finished_at=db_now().isoformat())
                    save_attempt(attempt)
                run.document.update(status="CANCELLED", stop_reason="USER_CANCELLED", dispatch_stage="CLOSED")
                run.document["revision"] += 1
                state_event(run, "RunCancelled", db_now())
                save_run(run)
                release_unstarted(run)
                close_search(run, version)


def search_inputs(actor: Account, version: ResearchVersion, row: RuntimeRun, lease: Lease) -> tuple[Account, ResearchVersion, SearchLimits, list[dict[str, object]], dict[str, object]]:
    """領取後重驗授權、固定來源及環境；checkpoint 只有當期 lease 可讀，觀測不進公有 DTO。"""
    snapshot = snapshot_for(row)
    plugin = snapshot.execution["plugins"][0]["config"]
    reports: list[dict[str, object]] = []
    check_submission(lease)
    with transaction.atomic():
        actor, version, reference = current(actor.id, version.id, allow_validating=True)
        limits = SearchLimits(**plugin["search_limits"])
        if (row.document["environment_digest"] != environment() or plugin["source_sha256"] != reference.sha256
                or plugin["source_object_version"] != str(reference.version)
                or snapshot.task_input["payload"]["strategies"] != strategy_ids()):
            raise ApiError("CHECKPOINT_INCOMPATIBLE", 409)
        content = LocalVersionStore(settings.OBJECT_ROOT).read_verified(reference)
        config = configuration(version, limits.parsing(), None, {})
        config["mode"] = "SEARCH_PROJECTION"
    previous = RuntimeCheckpoint.objects.filter(run=row).order_by("-created_at", "-id").first()
    if previous is not None:
        checkpoint = load_checkpoint(lease, previous.id)
        progress = checkpoint["strategy_progress"]
        if progress["completed"] != strategy_ids()[:len(progress["reports"])]:
            raise ApiError("CHECKPOINT_INCOMPATIBLE", 409)
        reports = progress["reports"]
        projection = progress["projection"]
    else:
        projection = inspect_research(content, version.dataset_version.document["format"], limits.parsing(), config)
        if projection.get("kind") != "SearchProjection":
            raise ApiError("DATA_QUALITY_BLOCKED", 409)
    return actor, version, limits, reports, projection


def reject_search(lease: Lease, version: ResearchVersion, meter: Meter, sequence: int, generated: int, code: str) -> None:
    """先記已停止 attempt 的實耗；裁決 root 後才歸還預留，QUEUED 重試仍持有剩額。"""
    tenant, identity = lease.tenant_id, lease.run_id
    with transaction.atomic():
        run = lock_run(tenant, identity)
        state_for(version)
        usage = meter.usage()
        previous = read_usage(RuntimeAttempt.objects.get(pk=lease.attempt_id).document["actual_usage"])
        usage.update(candidates_generated=max(previous["candidates_generated"], generated),
            candidates_accepted=previous["candidates_accepted"])
        SearchAttemptStop.objects.get_or_create(attempt_id=lease.attempt_id)
        report = usage_report(lease, usage, sequence + 1)
        report_usage(lease, report)
        run.refresh_from_db()
        if run.document["status"] == "CANCEL_REQUESTED":
            confirm_business_stopped(lease, usage)
        elif run.document["status"] not in {"SUCCEEDED", "FAILED", "CANCELLED"}:
            try:
                finish(lease, usage, lambda: None, lambda _run, _code: None, code)
            except ControlError:
                recover(tenant, identity)
        report_usage(lease, report, stopped=True)
        run.refresh_from_db()
        if run.document["status"] in {"SUCCEEDED", "FAILED", "CANCELLED"}:
            close_search(run, version)


def search_tick(tenant_id: str, run_id: str, generation: int) -> bool:
    """每族隔離程序停止後保存 receipt 與 checkpoint；只接受當期 lease，FIT 永遠不能進入。"""
    if not settings.SEARCH_ENABLED:
        return False
    tenant, identity = UUID(tenant_id), UUID(run_id)
    row = RuntimeRun.objects.filter(pk=identity, tenant_id=tenant, control_only=False, document__type="SEARCH", document__is_root=True, rootbudget__isnull=False).first()
    if row is None or not InputSnapshot.objects.filter(run=row).exists():
        return False
    with transaction.atomic():
        lease = claim(tenant, identity, generation, "search:" + str(uuid4()))
        if lease is None:
            recover_search(tenant, identity)
            return False
        version = ResearchVersion.objects.get(pk=UUID(row.document["research_version_id"]))
        state = state_for(version)
        if state.active_run_id == identity and state.status == "QUEUED":
            transition(state, "RUNNING", "t07-search-v1")
    meter = Meter()
    generated, accepted, sequence = 0, 0, 0
    generated_base, accepted_base = 0, 0
    strategies = strategy_ids()
    version = ResearchVersion.objects.get(pk=UUID(row.document["research_version_id"]))
    snapshot = snapshot_for(row)
    plugin = snapshot.execution["plugins"][0]["config"]
    actor = Account.objects.get(pk=UUID(plugin["actor_id"]))
    reports: list[dict[str, object]] = []
    try:
        actor, version, limits, reports, projection = search_inputs(actor, version, row, lease)
        if reports:
            restored = merge_reports(reports)
            generated_base = integer(restored["proposed_count"])
            accepted_base = generated_base - integer(restored["duplicate_count"])
        for index in range(len(reports), len(strategies)):
            heartbeat(lease)
            report = run_strategy(version.document, projection, index, limits.max_strategy_seconds)
            reports.append(report)
            combined = merge_reports(reports)
            generated = integer(combined["proposed_count"])
            accepted = generated - integer(combined["duplicate_count"])
            with transaction.atomic():
                run = lock_run(tenant, identity)
                check_submission(lease)
                sequence += 1
                usage = meter.usage()
                usage.update(candidates_generated=generated - generated_base, candidates_accepted=accepted - accepted_base)
                report_usage(lease, usage_report(lease, usage, sequence))
                save_checkpoint(lease, {"dsl_hash": None, "precision_bits": 53, "rng_state": None,
                    "strategy_progress": {"completed": strategies[:len(reports)], "reports": reports, "projection": projection}})
                run.refresh_from_db()
                if exceeds(read_usage(run.document["budget_usage"]), read_limit(snapshot.budget["limit"])):
                    raise ApiError("RUN_BUDGET_EXHAUSTED", 429)
        combined = merge_reports(reports)
        with transaction.atomic():
            run = lock_run(tenant, identity)
            state_for(version)
            actor, version, reference = current(actor.id, version.id, allow_validating=True)
            LocalVersionStore(settings.OBJECT_ROOT).verify(reference)
            usage = meter.usage()
            # 計數已逐族按去重增量入帳；終態只提交候選，不再次累加計數。
            previous_usage = read_usage(RuntimeAttempt.objects.get(pk=lease.attempt_id).document["actual_usage"])
            usage.update(candidates_generated=previous_usage["candidates_generated"], candidates_accepted=previous_usage["candidates_accepted"])
            def commit() -> None:
                persist_under(actor, version, ResearchBudget.objects.get(research_version=version), run, combined)
            finish(lease, usage, commit, lambda _run, _code: None)
            SearchAttemptStop.objects.get_or_create(attempt_id=lease.attempt_id)
            report_usage(lease, usage_report(lease, usage, sequence + 1), stopped=True)
            run.refresh_from_db()
            close_search(run, version)
    except (ApiError, ImportRejected, StorageRejected, ControlError, OSError, DatabaseError) as error:
        reject_search(lease, version, meter, sequence, generated - generated_base, getattr(error, "code", "DEPENDENCY_UNAVAILABLE"))
    return True
