"""候選公式的權威落庫：以 canonical DSL 身分登記 EquationVersion，重複擬合讀回同一列。

本切片只保存不可變的公式身分，不建立 Candidate／FitRun，也不評分或引用 final_test；
同租戶同身分只有一列，跨租戶互不可見，登記後不可改寫也不可刪除。
"""
from datetime import datetime
from uuid import UUID, uuid4
import json
from catalog.models import Account, EquationVersion
from catalog.validation import ApiError, validate_api
from mathematics.compiler import Plan
from runtime.contracts import JsonObject


def document_for(identity: UUID, tenant_id: UUID, plan: Plan, created: datetime) -> JsonObject:
    """組出契約形狀的公式版本；身分由 canonical DSL 決定，不隨登記時間或資料列而變。"""
    document: JsonObject = {"kind": "EquationVersion", "id": str(identity), "tenant_id": str(tenant_id), "schema_version": "2.0",
        "created_at": created.isoformat(), "dsl": json.loads(plan.canonical), "identity_hash": plan.identity_hash}
    validate_api(document, "EquationVersion")
    return document


def register(actor: Account, plan: Plan, created: datetime) -> EquationVersion:
    """同租戶同 (identity_hash, dsl_version) 只登記一次；已存在即讀回原列，不重建身分。"""
    identity = uuid4()
    document = document_for(identity, actor.tenant_id, plan, created)
    dsl_version: str = document["dsl"]["dsl_version"]
    row, _ = EquationVersion.objects.get_or_create(tenant_id=actor.tenant_id, identity_hash=plan.identity_hash,
        dsl_version=dsl_version, defaults={"id": identity, "created_at": created, "document": document})
    return row


def registered(tenant_id: UUID, identity: str) -> EquationVersion:
    """依身分讀回公式版本；跨租戶一律 404，不藉 hash 繞過租戶分區。"""
    row = EquationVersion.objects.filter(tenant_id=tenant_id, identity_hash=identity).first()
    if row is None:
        raise ApiError("NOT_FOUND", 404)
    validate_api(row.document, "EquationVersion")
    return row
