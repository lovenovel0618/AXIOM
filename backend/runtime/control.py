"""持久 root／attempt 控制：列鎖、lease 世代、取消 epoch、時限與有界恢復。

Transactional root INGEST control; business execution stays disabled."""
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid4
from django.db import transaction
from runtime.contracts import JsonObject, identity_hash
from runtime.models import InputSnapshot, RuntimeAttempt, RuntimeCheckpoint, RuntimeRun
from runtime.records import (
    CANCEL_REQUESTED, CHILD_TYPES, QUEUED, ROOT_TYPES, RUNNING, TERMINAL, ControlError,
    db_now, detached, emit, lock_run, save_attempt, save_run, snapshot_for, state_event,
    validate_bindings,
)

LEASE_SECONDS = 60
HEARTBEAT_SECONDS = 15
CHECKPOINT_PROGRESS = ("dsl_hash", "precision_bits", "rng_state", "strategy_progress")
IMMUTABLE_KEYS = ("id", "tenant_id", "type", "research_version_id", "dataset_id", "seed", "environment_digest", "input_artifact_id", "execution_manifest_id", "budget_account_id", "research_budget_account_id", "provenance_id", "root_run_id", "parent_run_id", "is_root")


@dataclass(frozen=True)
class Lease:
    """一次派送的不可變授權票據；worker、generation 與取消 epoch 共同 fencing。"""
    tenant_id: UUID
    run_id: UUID
    attempt_id: UUID
    generation: int
    epoch: int
    worker_id: str


def root_id_for(tenant_id: UUID, run_id: UUID) -> UUID:
    """以不可變的 `root_run_id` 判定根／子身分，供固定鎖序與帳本回推使用。"""
    document = RuntimeRun.objects.filter(tenant_id=tenant_id, pk=run_id).values_list("document", flat=True).first()
    if document is None:
        raise RuntimeRun.DoesNotExist("Run does not exist")
    return run_id if document["is_root"] else UUID(document["root_run_id"])


def lock_pair(tenant_id: UUID, run_id: UUID) -> tuple[RuntimeRun, RuntimeRun | None]:
    """固定鎖序：先鎖根再鎖自身；根任務回 `None`，子任務同時回根列鎖。"""
    root_id = root_id_for(tenant_id, run_id)
    if root_id == run_id:
        return lock_run(tenant_id, run_id), None
    root = lock_run(tenant_id, root_id)
    return lock_run(tenant_id, run_id), root


def _initial(record: JsonObject, budget: JsonObject) -> None:
    """新 root 必須零用量、無預留且處於 pristine QUEUED；不能挾帶偽造終態入庫。

    起始 `dispatch_stage` 由型別裁決：`VALIDATE` 只以 `FINAL_ONLY` 派送，其餘 root 從
    `SEARCH_OPEN` 開始探索，呼叫端不得自選。"""
    stage = "FINAL_ONLY" if record["type"] == "VALIDATE" else "SEARCH_OPEN"
    required: JsonObject = {"status": QUEUED, "revision": 0, "active_attempt_id": None, "lease_generation": 0, "cancellation_epoch": 0, "root_epoch_at_dispatch": 0, "cancel_requested_at": None, "dispatch_stage": stage, "phase": None, "stop_reason": None, "evidence_bundle_ids": [], "diagnostic_artifact_ids": [], "research_trace_artifact_ids": [], "skipped_phases": [], "outcome_status": None, "current_event_cursor": f"RUN:{record['id']}:0", "budget_reservations": []}
    if any(record[key] != value for key, value in required.items()):
        raise ValueError("New root must have pristine queued state")
    if budget["status"] != "OPEN" or budget["research_budget_account_id"] != record["research_budget_account_id"] or budget["reservations"]:
        raise ValueError("New INGEST budget must be open and unreserved")
    if any(value != 0 for value in budget["usage"].values()) or record["budget_usage"] != budget["usage"]:
        raise ValueError("New root usage must be zero")


def enqueue(tenant_id: UUID, record: JsonObject, task: JsonObject, execution: JsonObject, budget: JsonObject, *, control_only: bool = True) -> UUID:
    """固定輸入與預算快照並原子建立 root；相同 ID 僅接受相同快照，時限須在可表示範圍。"""
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
        run, created = RuntimeRun.objects.get_or_create(id=UUID(record["id"]), defaults={"tenant_id": tenant_id, "control_only": control_only, "document": record, "queue_deadline": deadline, "available_at": now})
        run = lock_run(tenant_id, run.id)
        if not created:
            previous = snapshot_for(run)
            if run.control_only != control_only or previous.content_hash != digest or any(run.document[key] != record[key] for key in IMMUTABLE_KEYS):
                raise ValueError("Existing run input conflict")
            return run.id
        InputSnapshot.objects.create(run=run, task_input=task, execution=execution, budget=budget, content_hash=digest)
        emit(run, "RunQueued", {"status": QUEUED, "attempt_id": None, "generation": 0}, now)
        save_run(run)
        return run.id


def _pristine_child(record: JsonObject, stage: str) -> None:
    """研究子任務必須 pristine QUEUED，且沿用根的派送階段，不能自選或挾帶終態入庫。"""
    required: JsonObject = {"status": QUEUED, "revision": 0, "active_attempt_id": None, "lease_generation": 0, "cancellation_epoch": 0, "root_epoch_at_dispatch": 0, "cancel_requested_at": None, "dispatch_stage": stage, "phase": None, "stop_reason": None, "evidence_bundle_ids": [], "child_run_ids": [], "diagnostic_artifact_ids": [], "research_trace_artifact_ids": [], "skipped_phases": [], "outcome_status": None, "current_event_cursor": f"RUN:{record['id']}:0", "budget_reservations": []}
    if any(record[key] != value for key, value in required.items()):
        raise ValueError("New child must have pristine queued state")
    if any(value != 0 for value in record["budget_usage"].values()):
        raise ValueError("New child usage must be zero")


def enqueue_child(tenant_id: UUID, record: JsonObject, task: JsonObject, execution: JsonObject, budget: JsonObject) -> UUID:
    """在根鎖內驗親代鏈、派送階段與共用帳本身分後，原子建立研究子任務。

    子任務與根共用同一 BudgetAccount 與研究帳本，因此不新增預留、不改寫根的公開用量口徑；
    只有根的 RUNNING 且未關閉派送時可新增，且親代必須屬於同一個根（禁止循環與跨 root）。"""
    record, task, execution, budget = map(detached, [record, task, execution, budget])
    if record["is_root"] or record["type"] not in CHILD_TYPES or record["parent_run_id"] is None or record["root_run_id"] == record["id"]:
        raise ValueError("Child identity required")
    validate_bindings(record, task, execution, budget)
    if record["tenant_id"] != str(tenant_id):
        raise ValueError("Tenant binding mismatch")
    digest = identity_hash([task, execution, budget])
    root_id, parent_id = UUID(record["root_run_id"]), UUID(record["parent_run_id"])
    with transaction.atomic():
        root = lock_run(tenant_id, root_id)
        if root.control_only or root.document["type"] not in ROOT_TYPES or root.document["type"] == "INGEST":
            raise ValueError("Child root must be a research root")
        parent = lock_run(tenant_id, parent_id)
        research_version, account = root.document["research_version_id"], root.document["budget_account_id"]
        if (root.document["status"] != RUNNING or root.document["dispatch_stage"] == "CLOSED"
                or parent.document["root_run_id"] != str(root_id)
                or research_version != record["research_version_id"]
                or account != record["budget_account_id"] or budget["id"] != account
                or root.document["research_budget_account_id"] != record["research_budget_account_id"]):
            raise ControlError("DISPATCH_STAGE_VIOLATION")
        _pristine_child(record, root.document["dispatch_stage"])
        now = db_now()
        record["created_at"] = now.isoformat()
        deadline = now + timedelta(seconds=execution["retry_policy"]["queue_timeout_seconds"])
        run, created = RuntimeRun.objects.get_or_create(id=UUID(record["id"]), defaults={"tenant_id": tenant_id, "control_only": False, "document": record, "queue_deadline": deadline, "available_at": now})
        run = lock_run(tenant_id, run.id)
        if not created:
            previous = snapshot_for(run)
            if run.control_only or previous.content_hash != digest or any(run.document[key] != record[key] for key in IMMUTABLE_KEYS):
                raise ValueError("Existing run input conflict")
            return run.id
        InputSnapshot.objects.create(run=run, task_input=task, execution=execution, budget=budget, content_hash=digest)
        root.document["child_run_ids"] = sorted({*root.document["child_run_ids"], str(run.id)})
        save_run(root)
        emit(run, "RunQueued", {"status": QUEUED, "attempt_id": None, "generation": 0}, now)
        save_run(run)
        return run.id


def _attempt_for(run: RuntimeRun) -> RuntimeAttempt:
    """依 root 活躍引用取 attempt，避免任意 attempt UUID 取代本次派送。"""
    return RuntimeAttempt.objects.select_for_update().get(pk=UUID(run.document["active_attempt_id"]), run=run)


def validate_lease(run: RuntimeRun, lease: Lease, now: datetime, root: RuntimeRun | None = None) -> RuntimeAttempt:
    """提交時驗 worker／世代／取消 epoch 與時限，舊 worker 不能覆蓋新狀態。

    子任務以根的取消 epoch 與終態共同 fencing，因此祖先取消立即阻擋遲到提交，子任務本身
    無法自行解除祖先取消。"""
    record = run.document
    epoch = record["cancellation_epoch"] if root is None else root.document["cancellation_epoch"]
    cancelled = record["status"] == CANCEL_REQUESTED or (root is not None and root.document["status"] in TERMINAL | {CANCEL_REQUESTED})
    if epoch != lease.epoch or cancelled:
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


def _fail(run: RuntimeRun, now: datetime, reason: str, root: RuntimeRun | None = None) -> None:
    """在持鎖交易內收斂失敗狀態與事件，不讓半份 attempt／Run 終態流出。

    `dispatch_stage` 只由根權威裁決，子任務失敗不自行關閉派的階段。"""
    run.document.update(status="FAILED", stop_reason=reason)
    if root is None:
        run.document["dispatch_stage"] = "CLOSED"
    run.document["revision"] += 1
    state_event(run, "RunFinished", now)
    save_run(run)


def _stop_child(run: RuntimeRun, now: datetime, root: RuntimeRun) -> None:
    """祖先終態時收斂子任務：根取消收斂為 CANCELLED／USER_CANCELLED，其餘終態標 FAILED。

    子任務不得自行改寫根的 `dispatch_stage`；`ROOT_CANCELLED` 只是提交拒絕碼，不是公開
    `stop_reason` 的合法值，故取消情境以公開 DTO 認可的 USER_CANCELLED 收斂。"""
    if root.document["status"] in {"CANCELLED", CANCEL_REQUESTED}:
        run.document.update(status="CANCELLED", stop_reason="USER_CANCELLED")
        run.document["revision"] += 1
        state_event(run, "RunCancelled", now)
        save_run(run)
        return
    _fail(run, now, "DEPENDENCY_FAILURE", root)


def _deadline_exceeded(run: RuntimeRun, snapshot: InputSnapshot, now: datetime) -> bool:
    """以首次啟動與固定 wall 限額判斷 deadline，不因重試重新起算。"""
    if snapshot.budget["limit"]["wall_seconds"] <= 0:
        return True
    if run.first_started_at is None:
        return False
    return now >= run.first_started_at + timedelta(seconds=snapshot.budget["limit"]["wall_seconds"])


def claim(tenant_id: UUID, run_id: UUID, generation: int, worker_id: str) -> Lease | None:
    """以 root 列鎖排除重複派送；只有當期 QUEUED 世代可建立新 attempt。

    子任務另要求根仍在 RUNNING 且未關閉派送，並以根的取消 epoch 作為票據世代。"""
    if not worker_id or len(worker_id) > 200:
        raise ValueError("Invalid worker identity")
    with transaction.atomic():
        run, root = lock_pair(tenant_id, run_id)
        record, now = run.document, db_now()
        if record["status"] != QUEUED or record["lease_generation"] != generation:
            return None
        if root is not None and (root.document["status"] != RUNNING or root.document["dispatch_stage"] == "CLOSED"):
            return None
        snapshot = snapshot_for(run)
        if _deadline_exceeded(run, snapshot, now):
            _fail(run, now, "BUDGET_EXHAUSTED", root)
            return None
        if now >= run.queue_deadline:
            _fail(run, now, "DEPENDENCY_FAILURE", root)
            return None
        if now < run.available_at:
            return None
        if generation >= snapshot.execution["retry_policy"]["max_attempts"]:
            _fail(run, now, "DEPENDENCY_FAILURE", root)
            return None
        epoch = record["cancellation_epoch"] if root is None else root.document["cancellation_epoch"]
        return _start_attempt(run, worker_id, now, epoch)


def _start_attempt(run: RuntimeRun, worker_id: str, now: datetime, epoch: int) -> Lease:
    """固定一次 attempt 的開始、lease 與工作階段，再同交易投影 Run。"""
    record = run.document
    generation = record["lease_generation"] + 1
    attempt_id = uuid4()
    document: JsonObject = {
        "kind": "AttemptRecord", "id": str(attempt_id), "tenant_id": str(run.tenant_id), "schema_version": "2.0",
        "created_at": now.isoformat(), "run_id": str(run.id), "generation": generation, "worker_id": worker_id,
        "lease_expires_at": (now + timedelta(seconds=LEASE_SECONDS)).isoformat(), "checkpoint_id": None,
        "status": RUNNING, "heartbeat_at": now.isoformat(), "started_at": now.isoformat(), "finished_at": None,
        "root_epoch_at_dispatch": epoch, "usage_sequence": 0, "actual_usage": detached(record["budget_usage"]),
    }
    save_attempt(RuntimeAttempt(id=attempt_id, run=run, generation=generation, document=document))
    record.update(status=RUNNING, active_attempt_id=str(attempt_id), lease_generation=generation)
    if record["type"]=="PROFILE":
        record["phase"] = "PROFILING"
    record["revision"] += 1
    if run.first_started_at is None:
        run.first_started_at = now
    emit(run, "RunStarted", {"status": RUNNING, "attempt_id": str(attempt_id), "generation": generation}, now)
    save_run(run)
    return Lease(run.tenant_id, run.id, attempt_id, generation, epoch, worker_id)


def heartbeat(lease: Lease) -> None:
    """只延長當前有效 lease 並累計用量；取消或過時世代不得復活。"""
    with transaction.atomic():
        run, root = lock_pair(lease.tenant_id, lease.run_id)
        now = db_now()
        attempt = validate_lease(run, lease, now, root)
        if _deadline_exceeded(run, snapshot_for(run), now):
            raise ControlError("STALE_ATTEMPT")
        attempt.document.update(heartbeat_at=now.isoformat(), lease_expires_at=(now + timedelta(seconds=LEASE_SECONDS)).isoformat())
        save_attempt(attempt)


def check_submission(lease: Lease) -> None:
    """在業務讀值／提交前檢查當前 fencing，晚到與取消均拒絕。"""
    with transaction.atomic():
        run, root = lock_pair(lease.tenant_id, lease.run_id)
        now = db_now()
        validate_lease(run, lease, now, root)
        if _deadline_exceeded(run, snapshot_for(run), now):
            raise ControlError("STALE_ATTEMPT")


def cancel(tenant_id: UUID, run_id: UUID, expected_revision: int) -> None:
    """先增加取消 epoch 並關派送，再等待停止證明；不能把請求取消直接當作已停。

    公開取消只接受根任務，子任務必須由根的世代與終態阻擋，不能自行解除祖先取消。"""
    with transaction.atomic():
        run, root = lock_pair(tenant_id, run_id)
        if root is not None:
            raise ControlError("CHILD_RUN_NOT_CANCELLABLE")
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
    """僅供沒有業務子程序的控制探針確認停止；真 INGEST／PROFILE 必須走 owning handler。"""
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
    """持久裁決排隊、lease、wall 超時；未知業務成本不自動重跑。

    子任務在根已終態或已取消時一併收斂，不再重領，避免祖先停止後仍有新派送。"""
    with transaction.atomic():
        run, root = lock_pair(tenant_id, run_id)
        now = db_now()
        if run.document["status"] in TERMINAL or run.document["status"] == CANCEL_REQUESTED:
            return
        if root is not None and root.document["status"] in TERMINAL | {CANCEL_REQUESTED}:
            _stop_child(run, now, root)
            return
        snapshot = snapshot_for(run)
        if run.document["status"] == QUEUED:
            if _deadline_exceeded(run, snapshot, now):
                _fail(run, now, "BUDGET_EXHAUSTED", root)
            elif now >= run.queue_deadline:
                _fail(run, now, "DEPENDENCY_FAILURE", root)
            return
        attempt = _attempt_for(run)
        if _deadline_exceeded(run, snapshot, now):
            attempt.document.update(status="FAILED", finished_at=now.isoformat())
            save_attempt(attempt)
            _fail(run, now, "BUDGET_EXHAUSTED", root)
            return
        if datetime.fromisoformat(attempt.document["lease_expires_at"]) > now:
            return
        attempt.document.update(status="EXPIRED", finished_at=now.isoformat())
        save_attempt(attempt)
        policy = snapshot.execution["retry_policy"]
        if _deadline_exceeded(run, snapshot, now):
            _fail(run, now, "BUDGET_EXHAUSTED", root)
        elif run.document["lease_generation"] >= policy["max_attempts"]:
            _fail(run, now, "DEPENDENCY_FAILURE", root)
        else:
            _requeue(run, policy, now)


def _requeue(run: RuntimeRun, policy: JsonObject, now: datetime) -> None:
    """控制探針有限重試延續原限額與歷史消耗，不建立新 root 洗掉成本。"""
    delay = min(policy["backoff_initial_seconds"] * 2 ** (run.document["lease_generation"] - 1), policy["backoff_max_seconds"])
    run.available_at = now + timedelta(seconds=delay)
    run.queue_deadline = run.available_at + timedelta(seconds=policy["queue_timeout_seconds"])
    run.document.update(status=QUEUED, active_attempt_id=None)
    run.document["revision"] += 1
    emit(run, "RunQueued", {"status": QUEUED, "attempt_id": None, "generation": run.document["lease_generation"]}, now)
    save_run(run)


def _plugin_hashes(snapshot: InputSnapshot) -> JsonObject:
    """以插件身分與程式碼雜湊固定執行環境，重試時據此判斷 checkpoint 相容性。"""
    return {plugin["plugin_id"]: plugin["code_sha256"] for plugin in snapshot.execution["plugins"]}


def save_checkpoint(lease: Lease, progress: JsonObject) -> UUID:
    """持有有效租約時保存不可變 checkpoint；只記錄進度，不結算帳本，因此重試不重置用量。"""
    with transaction.atomic():
        run, root = lock_pair(lease.tenant_id, lease.run_id)
        now = db_now()
        attempt = validate_lease(run, lease, now, root)
        snapshot = snapshot_for(run)
        missing = [key for key in CHECKPOINT_PROGRESS if key not in progress]
        if missing:
            raise ControlError("CHECKPOINT_INCOMPLETE")
        identity = uuid4()
        body = {"kind": "CheckpointRecord", "schema_version": "2.0", "id": str(identity),
            "tenant_id": str(run.tenant_id), "run_id": str(run.id), "attempt_id": str(attempt.id),
            "generation": lease.generation, "created_at": now.isoformat(), "root_epoch": lease.epoch,
            "input_hash": snapshot.content_hash, "dataset_version_id": run.document["dataset_id"],
            "environment_digest": run.document["environment_digest"], "plugin_hashes": _plugin_hashes(snapshot),
            "cumulative_usage": detached(run.document["budget_usage"]),
            "dsl_hash": progress["dsl_hash"], "precision_bits": progress["precision_bits"],
            "rng_state": progress["rng_state"], "strategy_progress": progress["strategy_progress"]}
        document = body | {"checksum": identity_hash(body)}
        RuntimeCheckpoint.objects.create(id=identity, run=run, tenant_id=run.tenant_id,
            attempt_id=attempt.id, document=document, created_at=now)
        attempt.document["checkpoint_id"] = str(identity)
        save_attempt(attempt)
        return identity


def load_checkpoint(lease: Lease, checkpoint_id: UUID) -> JsonObject:
    """取得新租約後才可讀回已驗證 checkpoint；資料／環境／插件不符一律回 CHECKPOINT_INCOMPATIBLE。

    讀取前先通過當期租約 fencing，因此不會恢復被取消的 root，也不會由過時 attempt 讀取；
    checksum 不一致代表文件被改寫，同樣拒絕，且只解碼受控 JSON、永不載入 pickle。"""
    with transaction.atomic():
        run, root = lock_pair(lease.tenant_id, lease.run_id)
        now = db_now()
        validate_lease(run, lease, now, root)
        snapshot = snapshot_for(run)
        row = RuntimeCheckpoint.objects.filter(pk=checkpoint_id, run=run, tenant_id=lease.tenant_id).first()
        if row is None:
            raise ControlError("CHECKPOINT_NOT_FOUND")
        document = row.document
        body = {key: value for key, value in document.items() if key != "checksum"}
        compatible = {"input_hash": snapshot.content_hash, "dataset_version_id": run.document["dataset_id"],
            "environment_digest": run.document["environment_digest"], "plugin_hashes": _plugin_hashes(snapshot)}
        if document.get("checksum") != identity_hash(body) or any(document.get(key) != value for key, value in compatible.items()):
            raise ControlError("CHECKPOINT_INCOMPATIBLE")
        return body
