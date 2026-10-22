"""來源失效宣告：同交易寫入 tombstone 與刪除工作，並讓既有讀取立即失效。

AX-43 在 D-05 未定保留與刪除政策前只允許受控的隔離／tombstone，且不提供硬刪除
API，因此本模組只走服務層：宣告來源失效、依 lineage 列舉受影響物件、寫入
tombstone，不開啟對外端點，也不宣稱索引或快取已被清除。
"""
from datetime import datetime
from uuid import UUID, uuid4

from django.conf import settings
from django.db import transaction

from catalog.models import Account, Artifact, DatasetVersion, DeletionRequest, DeletionTarget, EvidenceBundle, ResearchVersion, Tombstone
from catalog.services import dataset_for
from catalog.validation import ApiError


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


def declare(actor: Account, identity: UUID, created: datetime) -> DeletionRequest:
    """以研究來源為根宣告失效；同交易寫 tombstone、刪除工作與逐項受影響物件。

    政策未放行時刪除工作只停在 BLOCKED 並帶 FEATURE_DISABLED；tombstone 仍立即
    生效，因為「立即停止讀取」是最小安全性質，不因後續傳播被阻擋而回退。
    """
    version = DatasetVersion.objects.filter(pk=identity, tenant_id=actor.tenant_id).first()
    if version is None:
        raise ApiError("NOT_FOUND", 404)
    dataset_for(actor, version.dataset_id)
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
    return DeletionTarget.objects.filter(deletion_request=request).exclude(outcome="DONE").count()
