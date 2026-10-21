"""Immutable research drafts with owner and live dataset-grant intersection."""
from collections.abc import Callable
from datetime import datetime
from typing import TypeVar
from uuid import UUID, uuid4
from django.core import signing
from django.db.models import Q, QuerySet
from catalog.models import Account, Audit, DatasetVersion, Grant, Provenance, Research, ResearchVersion
from catalog.research_validation import confirm, require
from catalog.services import dataset_for, provenance
from catalog.validation import ApiError, validate_api
from runtime.contracts import JsonObject, identity_hash
from runtime.records import db_now

T = TypeVar("T", Research, ResearchVersion)


def writable(actor: Account) -> None:
    """全域 VIEWER 不能因資料集 grant 升級為研究寫入者。"""
    if actor.role not in {"RESEARCHER", "ADMIN"}:
        raise ApiError("FORBIDDEN", 403)


def research_for(actor: Account, identity: UUID) -> Research:
    """以 owner／租戶定位並鎖研究容器；ADMIN 沒有隱含讀取他人研究權。"""
    row = Research.objects.select_for_update().filter(pk=identity, tenant_id=actor.tenant_id, owner=actor).first()
    if row is None:
        raise ApiError("NOT_FOUND", 404)
    return row


def version_for(actor: Account, identity: UUID) -> ResearchVersion:
    """版本存取必須同時滿足 owner 與目前 Dataset grant，撤權後立即拒絕。"""
    row = ResearchVersion.objects.filter(pk=identity, tenant_id=actor.tenant_id, research__owner=actor).first()
    if row is None:
        raise ApiError("NOT_FOUND", 404)
    dataset_for(actor, row.dataset_version.dataset_id)
    return row


def research_dto(row: Research) -> JsonObject:
    """只投影已驗 schema 的研究 metadata，不連帶暴露資料或觀測。"""
    result: JsonObject = {"kind": "Research", "id": str(row.id), "tenant_id": str(row.tenant_id), "schema_version": "2.0", "created_at": row.created_at.isoformat(), "name": row.name, "owner_id": str(row.owner_id)}
    validate_api(result, "Research")
    return result


def create_research(actor: Account, data: JsonObject) -> JsonObject:
    """原子建立 owner 私有研究及來源／稽核，不假設資料權隨研究容器存在。"""
    writable(actor)
    require(bool(data["name"].strip()))
    identity, source = uuid4(), uuid4()
    provenance(actor, "Research", identity, source)
    row = Research.objects.create(id=identity, tenant_id=actor.tenant_id, owner=actor, name=data["name"], provenance_id=source)
    Audit.objects.create(tenant_id=actor.tenant_id, actor_id=actor.id, action="CREATE_RESEARCH", code="OK")
    return research_dto(row)


def available_version(actor: Account, identity: UUID) -> DatasetVersion:
    """建立及執行前要求可用版本與現行寫權，避免引用尚未提交或已封鎖的來源。"""
    row = DatasetVersion.objects.filter(pk=identity, tenant_id=actor.tenant_id).first()
    if row is None:
        raise ApiError("NOT_FOUND", 404)
    dataset_for(actor, row.dataset_id, write=True)
    if row.document["status"] != "AVAILABLE" or row.preview.document["status"] != "AVAILABLE":
        raise ApiError("ARTIFACT_UNAVAILABLE", 409)
    return row


def draft_document(actor: Account, research: Research, dataset: DatasetVersion, data: JsonObject, identity: UUID, created: datetime) -> JsonObject:
    """由明確人工設定固定語意／domain／切分；初始 DRAFT 不代表正式封存已登記。"""
    preview = dataset.preview.content
    if preview is None or "source_metadata" not in preview:
        raise ApiError("DEPENDENCY_UNAVAILABLE", 503)
    split = confirm(data, preview["source_metadata"])
    return {
        "kind": "ResearchVersion", "id": str(identity), "tenant_id": str(actor.tenant_id), "schema_version": "2.0", "created_at": created.isoformat(),
        "research_id": str(research.id), "dataset_version_id": str(dataset.id), "semantic_profile": data["semantic_profile"], "budget": data["budget"], "purpose": data["purpose"],
        "status": "DRAFT", "revision": 0, "observation_split": split, "current_event_cursor": f"RESEARCH:{identity}:0",
        "frozen_submission_ids": [], "review_ids": [], "published_artifact_ids": [], "evidence_bundle_ids": [], "released_summary_ids": [],
        "quality_report_id": None, "refit_policy_artifact_id": None, "structure_assessment_artifact_id": None,
        "domain": data["domain"], "evaluation_policy": data["evaluation_policy"], "evaluation_policy_hash": identity_hash(data["evaluation_policy"]),
        "research_budget_usage": {"cpu_seconds": 0, "gpu_seconds": 0, "tokens": 0, "peak_memory_bytes": 0, "elapsed_wall_seconds": 0, "candidates_generated": 0, "candidates_accepted": 0},
    }


def create_version(actor: Account, research: Research, data: JsonObject) -> JsonObject:
    """不可變草稿、來源與零起始研究帳本同交易建立，不能漏建帳本或洗掉歷史用量。"""
    writable(actor)
    dataset = available_version(actor, UUID(data["dataset_version_id"]))
    identity, source, created = uuid4(), uuid4(), db_now()
    document = draft_document(actor, research, dataset, data, identity, created)
    validate_api(document, "ResearchVersion")
    origin = Provenance.objects.get(pk=dataset.provenance_id, tenant_id=actor.tenant_id)
    provenance(actor, "ResearchVersion", identity, source, origin)
    ResearchVersion.objects.create(id=identity, tenant_id=actor.tenant_id, research=research, dataset_version=dataset, document=document, provenance_id=source, created_at=created)
    from catalog.budget import initialize
    initialize(ResearchVersion.objects.get(pk=identity))
    Audit.objects.create(tenant_id=actor.tenant_id, actor_id=actor.id, action="CREATE_RESEARCH_VERSION", code="OK")
    return document


def visible_versions(actor: Account, research: Research) -> QuerySet[ResearchVersion]:
    """只列目前 Dataset grant 仍允許的 owner 版本，不藉列表洩漏已撤權資料。"""
    permitted = Grant.objects.filter(actor=actor, tenant_id=actor.tenant_id).values("dataset_id")
    return ResearchVersion.objects.filter(tenant_id=actor.tenant_id, research=research, dataset_version__dataset_id__in=permitted)


def page(rows: QuerySet[T], actor: Account, scope: str, cursor: str, limit: int, dto: Callable[[T], JsonObject]) -> JsonObject:
    """按建立時間與 UUID 穩定分頁；游標綁 actor／tenant／scope 且 15 分鐘到期。"""
    binding = {"actor": str(actor.id), "tenant": str(actor.tenant_id), "scope": scope}
    rows = rows.order_by("-created_at", "-id")
    if cursor:
        try:
            value = signing.loads(cursor, salt="axiom-research-page-v1", max_age=900)
            if value["binding"] != binding:
                raise ValueError("Cursor scope")
            created, last = datetime.fromisoformat(value["created"]), UUID(value["id"])
            rows = rows.filter(Q(created_at__lt=created) | Q(created_at=created, id__lt=last))
        except (signing.BadSignature, ValueError, TypeError, KeyError) as error:
            raise ApiError("INVALID_CURSOR", 400) from error
    selected = list(rows[:limit + 1])
    cursor_out = None
    if len(selected) > limit:
        last_row = selected[limit - 1]
        cursor_out = signing.dumps({"binding": binding, "created": last_row.created_at.isoformat(), "id": str(last_row.id)}, salt="axiom-research-page-v1")
    return {"items": [dto(row) for row in selected[:limit]], "next_cursor": cursor_out}
