"""Authorized local preflight; independent of unavailable PROFILE scheduling."""
import hashlib
import sys
from uuid import UUID, uuid4
from django.conf import settings
from django.db import transaction
from catalog.ingest import Meter
from catalog.ingest_manifest import environment
from catalog.models import Account, Audit, ResearchInspection, ResearchState, ResearchVersion
from catalog.research import available_version, version_for
from catalog.services import actor_for
from catalog.storage import LocalVersionStore, ObjectRef
from catalog.validation import ApiError
from ingestion.limits import ImportLimits, require
from ingestion.research import Inspector, model_for, POLICY, MAX_ROWS
from ingestion.research_protocol import report_check
from ingestion.supervisor import inspect_research
from mathematics.compiler import compile_dsl
from runtime.contracts import JsonObject, identity_hash
from runtime.records import db_now
import json


def current(actor_id: UUID, version_id: UUID, *, allow_validating: bool = False) -> tuple[Account, ResearchVersion, ObjectRef]:
    """可信 CLI 仍須重驗 actor、研究 owner、租戶分區及來源；正式 PROFILE 執行中不得旁路預檢。"""
    account = Account.objects.filter(pk=actor_id).first()
    if account is None:
        raise ApiError("FORBIDDEN", 403)
    actor = actor_for(account.user_id)
    if not actor.user.is_active:
        raise ApiError("FORBIDDEN", 403)
    version = version_for(actor, version_id)
    dataset = available_version(actor, version.dataset_version_id)
    if version.document["status"] != "DRAFT" or (not allow_validating and ResearchState.objects.filter(research_version=version,status="VALIDATING").exists()):
        raise ApiError("INVALID_TRANSITION", 409)
    stored = dataset.raw.object
    if stored is None or stored.sha256 != dataset.sha256:
        raise ApiError("UPLOAD_OBJECT_CHANGED", 409)
    reference = ObjectRef(actor.tenant_id, stored.upload_id, stored.id, stored.sha256, stored.size_bytes)
    return actor, version, reference


def configuration(version: ResearchVersion, limits: ImportLimits, model: bytes | None, parameters: dict[str, str]) -> JsonObject:
    """固定研究配置、限額與已知 DSL 參數；編譯和域／單位檢查在讀觀測前完成。"""
    metadata = version.dataset_version.preview.content
    if metadata is None:
        raise ApiError("ARTIFACT_UNAVAILABLE", 409)
    document: JsonObject = {"policy_version": POLICY, "research": version.document, "metadata": metadata["source_metadata"], "limits": limits.document(),
        "source_sha256": version.dataset_version.sha256, "source_object_version": str(version.dataset_version.raw.object_id), "environment_digest": environment(),
        "model": None if model is None else json.loads(compile_dsl(model).canonical), "parameters": parameters}
    require(sys.platform == "linux", "DEPENDENCY_UNAVAILABLE")
    require(metadata["source_metadata"]["row_count"] <= min(MAX_ROWS, limits.max_rows), "IMPORT_LIMIT_EXCEEDED")
    model_for(document)
    Inspector(document)  # Recheck split and supported dependence policy before reading raw bytes.
    return document


def preflight(actor_id: UUID, version_id: UUID, limits: ImportLimits, model: bytes | None = None, parameters: dict[str, str] | None = None) -> JsonObject:
    """在隔離子程序執行有界品質／已知公式預檢，保存不可變結果並於提交前重驗來源及授權。"""
    with transaction.atomic():
        actor, version, reference = current(actor_id, version_id)
        config = configuration(version, limits, model, parameters or {})
        digest = identity_hash(config)
        store = LocalVersionStore(settings.OBJECT_ROOT)
        store.verify(reference)
        previous = ResearchInspection.objects.filter(research_version=version, request_hash=digest).first()
        if previous is not None:
            return previous.document
        content = store.read_verified(reference)
    meter = Meter()
    result = inspect_research(content, version.dataset_version.document["format"], limits, config)
    if hashlib.sha256(content).hexdigest() != config["source_sha256"]:
        raise ApiError("UPLOAD_OBJECT_CHANGED", 409)
    report_check(result, config)
    usage = meter.usage()
    # Meter excludes source IO and DB commit; it is a CLI execution measurement, not a ledger.
    with transaction.atomic():
        actor, version, reference = current(actor_id, version_id)
        LocalVersionStore(settings.OBJECT_ROOT).verify(reference)
        if environment() != config["environment_digest"]:
            raise ApiError("CHECKPOINT_INCOMPATIBLE", 409)
        identity = uuid4()
        document: JsonObject = {"kind": "ResearchInspection", "schema_version": "1.0", "id": str(identity), "created_at": db_now().isoformat(),
            "tenant_id": str(actor.tenant_id), "research_version_id": str(version.id), "actor_id": str(actor.id), "request_hash": digest,
            "source_sha256": config["source_sha256"], "environment_digest": config["environment_digest"], "result": result,
            "measured_execution_usage": usage, "usage_scope": "LOCAL_PREFLIGHT_EXECUTION_ONLY", "research_status": "DRAFT", "product_gate_status": "NOT_RUN"}
        row, created = ResearchInspection.objects.get_or_create(research_version=version, request_hash=digest,
            defaults={"id": identity, "tenant_id": actor.tenant_id, "actor": actor, "configuration": config, "document": document})
        if created:
            Audit.objects.create(tenant_id=actor.tenant_id, actor_id=actor.id, action="INSPECT_RESEARCH", code=result["quality"])
        return row.document


def parameters_from(value: str) -> dict[str, str]:
    """只解碼十進位參數字串物件，不接受任意 Python 或 shell 表達式。"""
    from catalog.validation import decode
    data = decode(value.encode("utf-8"))
    if len(data) > 128 or any(not isinstance(item, str) for item in data.values()):
        raise ApiError("INVALID_SCHEMA", 422)
    return data


def read_model(path: str | None) -> bytes | None:
    """有界讀取並編譯既有 DSL 檔；模型只作固定已知公式驗證，不在此搜尋或擬合。"""
    if path is None:
        return None
    from pathlib import Path
    with Path(path).open("rb") as source:
        value = source.read(262145)
    if len(value) > 262144:
        raise ApiError("UPLOAD_TOO_LARGE", 413)
    return value
