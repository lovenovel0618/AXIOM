"""Immutable registry and authorized metadata-only content projection."""
import hashlib
from typing import Protocol
from uuid import UUID, uuid4
from catalog.models import Account, Artifact, DatasetVersion, IngestBinding, Provenance, ResearchVersion, StoredObject
from catalog.services import dataset_for, provenance
from catalog.validation import ApiError
from runtime.contracts import JsonObject, canonical_bytes, validate
from runtime.records import db_now


class DatasetScope(Protocol):
    """產物所需的最小資料集介面，避免依賴特定 INGEST／PROFILE binding 類別。"""
    dataset_id: UUID


def register(actor: Account, binding: DatasetScope, identity: UUID, content: JsonObject | None, source: Provenance, raw: StoredObject | None = None, *, research_version: ResearchVersion | None = None) -> Artifact:
    """以來源鏈及存取等級註冊不可變 JSON Artifact；私有研究產物另綁 research_version。"""
    data = canonical_bytes(content) if content is not None else b""
    source_id = uuid4()
    provenance(actor, "Artifact", identity, source_id, source)
    document: JsonObject = {"kind": "Artifact", "id": str(identity), "tenant_id": str(actor.tenant_id), "schema_version": "2.0", "created_at": db_now().isoformat(),
        "artifact_uri": f"/api/v2/artifacts/{identity}/content", "sha256": hashlib.sha256(data).hexdigest() if raw is None else raw.sha256,
        "status": "AVAILABLE", "owner_id": str(actor.id), "size_bytes": len(data) if raw is None else raw.size_bytes,
        "media_type": "application/json" if raw is None else "application/octet-stream",
        "access_class": "PROJECT" if content is not None and content.get("kind") in {"StructureAssessment", "ImportDiagnostic", "QualityReport"} else "SEALED_DETAIL"}
    validate(document, "runtime-v2.schema.json", "Artifact")
    return Artifact.objects.create(id=identity, tenant_id=actor.tenant_id, dataset_id=binding.dataset_id, owner=actor, object=raw, content=content, document=document, provenance_id=source_id, research_version=research_version)


def assessment(binding: IngestBinding, version_id: UUID, identity: UUID, metadata: JsonObject, manifest: UUID) -> JsonObject:
    """只從匯入 metadata 建純結構預覽，不推定語意、樣本統計或研究結論。"""
    count = len(metadata["columns"])
    result: JsonObject = {"kind": "StructureAssessment", "id": str(identity), "tenant_id": str(binding.tenant_id), "research_version_id": None,
        "schema_version": "1.0", "created_at": db_now().isoformat(), "artifact_access_class": "PROJECT", "dataset_version_id": str(version_id),
        "observation_dimension": count, "coordinate_dimension": None, "representation_dimension": count, "intrinsic_dimension_estimate": None,
        "structure_candidates": ["UNKNOWN"], "time_basis": "UNKNOWN", "periodicity": "UNKNOWN", "method_manifest_id": str(manifest),
        "fit_rows_hash": None, "uncertainty_reason": "Schema and shape only; semantics and statistical structure require user confirmation and fit-only analysis",
        "analysis_scope": "METADATA_ONLY", "source_metadata": metadata}
    validate(result, "research-learning-v1.schema.json", "StructureAssessment")
    return result


def publish(actor: Account, binding: IngestBinding, metadata: JsonObject, execution_id: UUID) -> None:
    """同交易提交可用 DatasetVersion 與純結構 Artifact；原始物件繼續封存。"""
    upload = binding.upload
    existing = DatasetVersion.objects.filter(dataset_id=binding.dataset_id, sha256=upload.sha256).first()
    if existing is not None:
        if existing.document["format"] != upload.format:
            raise ApiError("INVALID_SCHEMA", 422)
        binding.result = existing
        binding.save(update_fields=["result"])
        return
    source = Provenance.objects.get(resource_type="Run", resource_id=binding.run_id, tenant_id=binding.tenant_id)
    stored = StoredObject.objects.get(pk=upload.object_version, tenant_id=binding.tenant_id)
    identity, raw_id, preview_id, source_id = (uuid4() for _index in range(4))
    raw = register(actor, binding, raw_id, None, source, stored)
    preview = register(actor, binding, preview_id, assessment(binding, identity, preview_id, metadata, execution_id), source)
    provenance(actor, "DatasetVersion", identity, source_id, source)
    created = db_now()
    document: JsonObject = {"kind": "DatasetVersion", "id": str(identity), "tenant_id": str(binding.tenant_id), "schema_version": "2.0", "created_at": created.isoformat(),
        "dataset_id": str(binding.dataset_id), "artifact_uri": raw.document["artifact_uri"], "sha256": upload.sha256, "format": upload.format,
        "row_count": metadata["row_count"], "status": "AVAILABLE", "artifact_id": str(raw_id), "structure_preview_artifact_id": str(preview_id)}
    validate(document, "research-v2.schema.json", "DatasetVersion")
    binding.result = DatasetVersion.objects.create(id=identity, tenant_id=binding.tenant_id, dataset_id=binding.dataset_id, sha256=upload.sha256,
        document=document, raw=raw, preview=preview, provenance_id=source_id, created_at=created)
    binding.save(update_fields=["result"])


def authorized(actor: Account, identity: UUID) -> Artifact:
    """普通讀取同時驗租戶、Dataset grant、研究 owner 及 access class，避免只憑 UUID 下載。"""
    row = Artifact.objects.filter(pk=identity, tenant_id=actor.tenant_id).first()
    if row is None or row.document["access_class"] != "PROJECT":
        raise ApiError("NOT_FOUND", 404)
    dataset_for(actor, row.dataset_id)
    if row.research_version_id is not None:
        from catalog.research import version_for
        version_for(actor,row.research_version_id)
    if row.document["status"] != "AVAILABLE":
        raise ApiError("ARTIFACT_UNAVAILABLE", 409)
    return row
