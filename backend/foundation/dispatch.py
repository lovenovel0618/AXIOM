"""At-least-once dispatch with a database-fenced synthetic effect."""
from collections.abc import Callable
from datetime import timedelta
from uuid import UUID, uuid4
from django.db import transaction
from django.utils import timezone
from foundation.models import DispatchProbe, DONE, PENDING, RUNNING

LEASE_SECONDS = 30


def claim(probe_id: UUID, generation: int) -> UUID | None:
    """原子取得控制探針當期世代，重複派送不能重複完成。"""
    with transaction.atomic():
        row = DispatchProbe.objects.select_for_update().get(pk=probe_id)
        if row.state != PENDING or row.generation != generation:
            return None
        token = uuid4()
        row.state, row.token = RUNNING, token
        row.lease_until = timezone.now() + timedelta(seconds=LEASE_SECONDS)
        row.save(update_fields=["state", "token", "lease_until"])
        return token


def complete(probe_id: UUID, generation: int, token: UUID) -> bool:
    """只有持有當前 claim 的程序可完成，逾期 worker 不得覆蓋結果。"""
    with transaction.atomic():
        row = DispatchProbe.objects.select_for_update().get(pk=probe_id)
        if row.state != RUNNING or row.generation != generation or row.token != token:
            return False
        if row.lease_until is None or row.lease_until <= timezone.now():
            return False
        row.state, row.completions = DONE, 1
        row.token, row.lease_until = None, None
        row.save(update_fields=["state", "completions", "token", "lease_until"])
        return True


def pending_batch() -> list[tuple[UUID, int]]:
    """有界掃描未完成探針，避免 relay 一次無界載入資料庫。"""
    with transaction.atomic():
        expired = DispatchProbe.objects.select_for_update(skip_locked=True).filter(
            state=RUNNING, lease_until__lte=timezone.now()
        ).order_by("id")[:100]
        for row in expired:
            row.state, row.token, row.lease_until = PENDING, None, None
            row.generation += 1
            row.save(update_fields=["state", "token", "lease_until", "generation"])
    return list(DispatchProbe.objects.filter(state=PENDING).order_by("id").values_list("id", "generation")[:100])


def relay(publish: Callable[[str, int], None]) -> int:
    """持久重送待執行探針；broker 暫失不把任務冒充成功。"""
    batch = pending_batch()
    for probe_id, generation in batch:
        publish(str(probe_id), generation)
    return len(batch)
