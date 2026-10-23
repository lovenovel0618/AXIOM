"""不變證據包：只引用既有產物與已落庫的評估結果，不生成新的科學主張。

READY 版本以品質報告與結構評估產物作為可引用證據；最終評估成功後另立一個只引用 ValidationRun 的
證據包，兩者都符合契約「validation_ids／proof_artifact_ids 至少一項非空」。"""
from datetime import datetime
from uuid import UUID, uuid4
from catalog.deletion import is_tombstoned
from catalog.models import Account, EvidenceBundle, ProfileBinding, ResearchVersion
from catalog.research import version_for
from catalog.validation import ApiError, validate_api
from runtime.contracts import JsonObject
from runtime.models import RuntimeRun


def bundle_document(identity: UUID, tenant_id: UUID, research_version_id: UUID, validation_ids: tuple[UUID, ...],
                    proof_artifact_ids: tuple[UUID | None, ...], created: datetime) -> JsonObject:
    """組出契約形狀的證據包；引用集合必須非空，否則投影不出任何證據。"""
    validations = [str(value) for value in validation_ids]
    proofs = [str(value) for value in proof_artifact_ids if value is not None]
    if not validations and not proofs:
        raise ApiError("DEPENDENCY_UNAVAILABLE", 503)
    document: JsonObject = {"kind": "EvidenceBundle", "id": str(identity), "tenant_id": str(tenant_id), "schema_version": "2.0",
        "created_at": created.isoformat(), "research_version_id": str(research_version_id), "validation_ids": validations,
        "proof_artifact_ids": proofs, "status": "ACTIVE", "revision": 0}
    validate_api(document, "EvidenceBundle")
    return document


def register(actor: Account, binding: ProfileBinding, run: RuntimeRun, proof_artifact_ids: tuple[UUID | None, ...], created: datetime) -> EvidenceBundle:
    """登記證據包；建立後不可刪除，身分欄位不可改，狀態改變才動 revision。"""
    identity = uuid4()
    document = bundle_document(identity, binding.tenant_id, binding.research_version_id, (), proof_artifact_ids, created)
    return EvidenceBundle.objects.create(id=identity,tenant_id=actor.tenant_id,research_version_id=binding.research_version_id,run=run,
        created_at=created,document=document)


def register_validation(actor: Account, version: ResearchVersion, run: RuntimeRun, validation_id: UUID, created: datetime) -> EvidenceBundle:
    """為已落庫的最終評估結果建立證據包；引用的是結果身分，不是可重寫的分數。"""
    identity = uuid4()
    document = bundle_document(identity, actor.tenant_id, version.id, (validation_id,), (), created)
    return EvidenceBundle.objects.create(id=identity,tenant_id=actor.tenant_id,research_version_id=version.id,run=run,
        created_at=created,document=document)


def authorized(actor: Account, identity: UUID) -> EvidenceBundle:
    """重新驗租戶與現行研究 owner；不符一律 404，不藉 UUID 繞過。"""
    row = EvidenceBundle.objects.filter(pk=identity,tenant_id=actor.tenant_id).first()
    if row is None or is_tombstoned(actor,"EvidenceBundle",identity):
        raise ApiError("NOT_FOUND",404)
    version_for(actor,row.research_version_id)
    validate_api(row.document,"EvidenceBundle")
    return row
