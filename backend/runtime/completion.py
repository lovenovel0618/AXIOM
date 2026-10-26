"""固定業務 handler 的終態提交：拒絕晚到產物，保留超支與已停止的實際用量。

Fenced terminal submission for the fixed business INGEST handler."""
from collections.abc import Callable
from datetime import timedelta
from django.db import transaction
from runtime.budget_types import read_usage, read_limit, exceeds, USAGE_KEYS
from runtime.control import Lease, validate_lease
from runtime.models import RuntimeRun
from runtime.records import ControlError, db_now, lock_run, save_attempt, save_run, snapshot_for, state_event


def finish(lease: Lease, usage: object, commit: Callable[[], None], failure: Callable[[RuntimeRun, str], None], error_code: str | None = None) -> None:
    """對固定業務 handler 做終態提交；重新驗 lease 與實耗，超支拒收產物但保留真實用量。"""
    usage = read_usage(usage)
    with transaction.atomic():
        run = lock_run(lease.tenant_id, lease.run_id)
        if run.control_only:
            raise ControlError("FEATURE_DISABLED")
        now = db_now()
        attempt = validate_lease(run, lease, now)
        limit = read_limit(snapshot_for(run).budget["limit"])
        effective = dict(usage)
        if run.document["type"] == "SEARCH":
            previous = read_usage(attempt.document["actual_usage"])
            total = read_usage(run.document["budget_usage"])
            effective = {key: max(total[key], usage[key]) if key == "peak_memory_bytes" else total[key] - previous[key] + usage[key] for key in USAGE_KEYS}
        exceeded = (exceeds(read_usage(effective), limit) or usage["cpu_seconds"] > limit["cpu_seconds"] or usage["peak_memory_bytes"] > limit["memory_bytes"] or
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
        # 回呼可能已就同一 root 寫入事件（如最終評估結果）；只補回最新游標，保留回呼在記憶體的其他變動。
        run.document["current_event_cursor"] = lock_run(lease.tenant_id, lease.run_id).document["current_event_cursor"]
        attempt.document.update(status=status, finished_at=now.isoformat(), actual_usage=usage, usage_sequence=max(1, attempt.document["usage_sequence"]))
        run.document.update(status=status, stop_reason=reason, dispatch_stage="CLOSED", budget_usage=effective)
        run.document["revision"] += 1
        save_attempt(attempt)
        state_event(run, "RunFinished", now)
        save_run(run)


def confirm_business_stopped(lease: Lease, usage: object) -> bool:
    """只能由原 owning handler 在 parser 已退出並回收後確認取消，不能由 lease 到期推定已停。"""
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
        usage = read_usage(usage)
        now = db_now()
        attempt.document.update(status="CANCELLED", finished_at=now.isoformat(), actual_usage=usage, usage_sequence=max(1, attempt.document["usage_sequence"]))
        run.document.update(status="CANCELLED", stop_reason="USER_CANCELLED", dispatch_stage="CLOSED",
            budget_usage=run.document["budget_usage"] if run.document["type"] == "SEARCH" else usage)
        run.document["revision"] += 1
        save_attempt(attempt)
        state_event(run, "RunCancelled", now)
        save_run(run)
        return True
