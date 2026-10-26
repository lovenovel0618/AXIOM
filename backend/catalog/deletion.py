"""來源失效宣告與對外刪除工作：同交易寫入 tombstone 與刪除工作，並讓既有讀取立即失效。

AX-43 在 D-05 未定保留與刪除政策前只允許受控的隔離／tombstone，不提供硬刪除，
因此本模組的對外入口只做三件事：dry-run 依 lineage 列舉影響、受政策閘門的宣告、
以及刪除工作狀態讀回；受影響物件的逐項收斂由 `propagate` 在政策放行後非同步驅動。
本模組不宣稱索引、快取、記憶 embedding 或備份已被抹除，`DONE` 只代表該動作可驗證
的隔離已完成。
"""
from datetime import datetime
from uuid import UUID, uuid4

from django.conf import settings
from django.db import transaction
from django.db.models import Count, Q

from catalog.models import Account, Artifact, DatasetVersion, DeletionRequest, DeletionTarget, EvidenceBundle, ResearchVersion, Tombstone
from catalog.services import dataset_for
from catalog.validation import ApiError
from runtime.contracts import JsonObject

PENDING = "PENDING"
DONE = "DONE"


def is_tombstoned(actor: Account, object_type: str, identity: UUID) -> bool:
    """回查權威有效性；呼叫端不得只信 UUID、舊列表或快取 TTL。"""
    return Tombstone.objects.filter(tenant_id=actor.tenant_id, object_type=object_type, object_id=identity).exists()


def affected(actor: Account, version: DatasetVersion) -> tuple[tuple[str, UUID, str], ...]:
    """依 lineage 列舉受影響物件與動作：來源本身標記，其餘衍生為待清除。
    
    AX-26 所列記憶 embedding／快取、報告、訓練快照與模型版本目前不存在，不為
    它們偽造受影響物件列。
    """
    tenant = actor.tenant_id
    items: list[tuple[str, UUID, str]] = [("DatasetVersion", version.id, "TOMBSTONE")]
    seen: set[tuple[str, UUID]] = {("DatasetVersion", version.id)}
    for identity in (version.raw_id, version.preview_id):
        if ("Artifact", identity) not in seen:
            seen.add(("Artifact", identity))
            items.append(("Artifact", identity, "PURGE_DERIVED"))
    for row in ResearchVersion.objects.filter(dataset_version_id=version.id, tenant_id=tenant):
        seen.add(("ResearchVersion", row.id))
        items.append(("ResearchVersion", row.id, "PURGE_DERIVED"))
        for artifact in Artifact.objects.filter(research_version_id=row.id, tenant_id=tenant):
            if ("Artifact", artifact.id) not in seen:
                seen.add(("Artifact", artifact.id))
                items.append(("Artifact", artifact.id, "PURGE_DERIVED"))
        for bundle in EvidenceBundle.objects.filter(research_version_id=row.id, tenant_id=tenant):
            if ("EvidenceBundle", bundle.id) not in seen:
                seen.add(("EvidenceBundle", bundle.id))
                items.append(("EvidenceBundle", bundle.id, "PURGE_DERIVED"))
    return tuple(items)


def source_for(actor: Account, identity: UUID) -> DatasetVersion:
    """對外入口的來源授權：租戶分區與資料集 owner 皆須相符，否則一律 404。"""
    version = DatasetVersion.objects.filter(pk=identity, tenant_id=actor.tenant_id).first()
    if version is None:
        raise ApiError("NOT_FOUND", 404)
    dataset_for(actor, version.dataset_id)
    return version


def declare(actor: Account, identity: UUID, created: datetime) -> DeletionRequest:
    """以研究來源為根宣告失效；同交易寫 tombstone、刪除工作與逐項受影響物件。

    政策未放行時刪除工作只停在 BLOCKED 並帶 FEATURE_DISABLED；tombstone 仍立即
    生效，因為「立即停止讀取」是最小安全性質，不因後續傳播被阻擋而回退。
    """
    version = source_for(actor, identity)
    if is_tombstoned(actor, "DatasetVersion", version.id):
        raise ApiError("INVALID_TRANSITION", 409)
    active = settings.DELETION_PROPAGATION_ENABLED
    with transaction.atomic():
        request = DeletionRequest.objects.create(id=uuid4(), tenant_id=actor.tenant_id, dataset_version=version, requested_by=actor,
            created_at=created, revision=0, policy_status="ACTIVE" if active else "BLOCKED",
            status="PROPAGATING" if active else "BLOCKED", blocked_code=None if active else "FEATURE_DISABLED")
        for object_type, object_id, action in affected(actor, version):
            Tombstone.objects.create(tenant_id=actor.tenant_id, deletion_request=request, object_type=object_type, object_id=object_id, created_at=created)
            DeletionTarget.objects.create(deletion_request=request, tenant_id=actor.tenant_id, object_type=object_type, object_id=object_id, action=action)
    return request


def outstanding(request: DeletionRequest) -> int:
    """尚未完成的受影響物件數；部分清理失敗不得顯示 COMPLETED。"""
    return DeletionTarget.objects.filter(deletion_request=request).exclude(outcome=DONE).count()


def preview(actor: Account, identity: UUID) -> JsonObject:
    """dry-run：只依 lineage 列舉影響，不寫任何列、不改任何狀態。

    AX-43 要求在宣告前先算出受影響的原始檔、projection、報告與其他衍生物件的
    lineage 影響；本函式因此是唯讀的，重複呼叫不產生副作用。"""
    version = source_for(actor, identity)
    return {"dataset_version_id": str(version.id), "propagation_enabled": settings.DELETION_PROPAGATION_ENABLED,
            "affected": [{"object_type": object_type, "object_id": str(object_id), "action": action}
                         for object_type, object_id, action in affected(actor, version)]}


def latest(actor: Account, identity: UUID) -> DeletionRequest:
    """讀回該來源最新一筆刪除工作；尚未宣告時回 404，不以空集合假裝已刪除。"""
    source_for(actor, identity)
    row = DeletionRequest.objects.filter(tenant_id=actor.tenant_id, dataset_version_id=identity).order_by("-created_at", "-id").first()
    if row is None:
        raise ApiError("NOT_FOUND", 404)
    return row


def serialize(request: DeletionRequest) -> JsonObject:
    """把刪除工作投影成對外視圖：狀態、政策閘門與逐項結果，不彙總成單一結論。"""
    targets = [{"object_type": target.object_type, "object_id": str(target.object_id), "action": target.action,
                "outcome": target.outcome, "attempts": target.attempts, "last_error": target.last_error}
               for target in DeletionTarget.objects.filter(deletion_request=request).order_by("object_type", "object_id", "action")]
    return {"deletion_request_id": str(request.id), "dataset_version_id": str(request.dataset_version_id),
            "status": request.status, "policy_status": request.policy_status, "blocked_code": request.blocked_code,
            "revision": request.revision, "created_at": request.created_at.isoformat(),
            "propagation_enabled": settings.DELETION_PROPAGATION_ENABLED, "outstanding": outstanding(request),
            "targets": targets}


def due(limit: int) -> list[tuple[str, str]]:
    """列出政策已放行且仍有待處理受影響物件的刪除工作，供 relay 公平輪詢。"""
    if not settings.DELETION_PROPAGATION_ENABLED:
        return []
    rows = (DeletionRequest.objects.filter(status="PROPAGATING", policy_status="ACTIVE")
            .annotate(pending=Count("deletiontarget", filter=Q(deletiontarget__outcome=PENDING))).filter(pending__gt=0)
            .order_by("created_at", "id")[:limit])
    return [(str(row.tenant_id), str(row.id)) for row in rows]


def propagate(tenant_id: UUID, identity: UUID) -> bool:
    """把單一 PROPAGATING 工作的待處理物件收斂為終態，全部完成才推進 COMPLETED。

    政策未放行即拒絕，不因 relay 誤呼叫就繞過 D-05 閘門。逐項只驗證隔離已生效
    （tombstone 存在）後才記 `DONE`；失敗保留原狀並記 `FAILED` 與錯誤碼，部分失敗
    不得讓整筆工作顯示 COMPLETED。"""
    if not settings.DELETION_PROPAGATION_ENABLED:
        raise ApiError("FEATURE_DISABLED", 503)
    with transaction.atomic():
        request = DeletionRequest.objects.select_for_update().filter(pk=identity, tenant_id=tenant_id).first()
        if request is None or request.status != "PROPAGATING" or request.policy_status != "ACTIVE":
            return False
        targets = list(DeletionTarget.objects.select_for_update().filter(deletion_request=request).order_by("id"))
        for target in targets:
            if target.outcome == DONE:
                continue
            if not Tombstone.objects.filter(tenant_id=request.tenant_id, object_type=target.object_type, object_id=target.object_id).exists():
                DeletionTarget.objects.filter(pk=target.id).update(outcome="BLOCKED", attempts=target.attempts + 1, last_error="INVALID_TRANSITION")
                return False
            DeletionTarget.objects.filter(pk=target.id).update(outcome=DONE, attempts=target.attempts + 1, last_error=None)
        if outstanding(request) == 0:
            request.status, request.revision, request.blocked_code = "COMPLETED", request.revision + 1, None
            request.save(update_fields=["status", "revision", "blocked_code"])
            return True
        return False
