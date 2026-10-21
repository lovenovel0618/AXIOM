"""READY 版本的不變證據包：只引用既有產物，不生成新的科學主張。

本切片以品質報告與結構評估產物作為可引用證據；validation 與 formal proof
尚未存在，因此 validation_ids 一律為空，符合契約「兩者至少一項非空」。
"""
from datetime import datetime
from uuid import UUID, uuid4
from catalog.models import Account, EvidenceBundle, ProfileBinding
from catalog.research import version_for
from catalog.validation import ApiError, validate_api
from runtime.contracts import JsonObject
from runtime.models import RuntimeRun


def bundle_document(identity: UUID, binding: ProfileBinding, proof_artifact_ids: tuple[UUID | None, ...], created: datetime) -> JsonObject:
    """組出契約形狀的證據包；引用集合必須非空，否則投影不出任何證據。"""
    proofs = [str(value) for value in proof_artifact_ids if value is not None]
    if not proofs:
        raise ApiError("DEPENDENCY_UNAVAILABLE", 503)
    document: JsonObject = {"kind": "EvidenceBundle", "id": str(identity), "tenant_id": str(binding.tenant_id), "schema_version": "2.0",
        "created_at": created.isoformat(), "research_version_id": str(binding.research_version_id), "validation_ids": [],
        "proof_artifact_ids": proofs, "status": "ACTIVE", "revision": 0}
    validate_api(document, "EvidenceBundle")
    return document


def register(actor: Account, binding: ProfileBinding, run: RuntimeRun, proof_artifact_ids: tuple[UUID | None, ...], created: datetime) -> EvidenceBundle:
    """登記證據包；建立後不可刪除，身分欄位不可改，狀態改變才動 revision。"""
    identity = uuid4()
    document = bundle_document(identity, binding, proof_artifact_ids, created)
    return EvidenceBundle.objects.create(id=identity,tenant_id=actor.tenant_id,research_version_id=binding.research_version_id,run=run,
        created_at=created,document=document)


def authorized(actor: Account, identity: UUID) -> EvidenceBundle:
    """重新驗租戶與現行研究存取權；不符或已撤權一律 404，不藉 UUID 繞過授權。"""
    row = EvidenceBundle.objects.filter(pk=identity,tenant_id=actor.tenant_id).first()
    if row is None:
        raise ApiError("NOT_FOUND",404)
    version_for(actor,row.research_version_id)
    validate_api(row.document,"EvidenceBundle")
    return row
