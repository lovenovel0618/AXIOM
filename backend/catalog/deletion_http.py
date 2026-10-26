"""刪除工作的對外 HTTP 邊界：dry-run、宣告與狀態讀回。

每個入口都重新驗租戶分區與資料集 owner，不能只憑 UUID 或舊列表放行；dry-run 唯讀，
宣告在政策未放行時只寫 tombstone 並把工作停在 BLOCKED，讀回端點只投影公開欄位。
"""
from uuid import UUID
from django.http import HttpRequest, JsonResponse
from catalog.deletion import declare, latest, preview, serialize, source_for
from catalog.http import api, allowed_methods
from catalog.models import Account
from catalog.services import replay
from catalog.validation import validate_api
from runtime.contracts import JsonObject
from runtime.records import db_now


@allowed_methods(["POST"])
@api
def dry_run(_request: HttpRequest, actor: Account, identity: UUID) -> JsonResponse:
    """dry-run：只回 lineage 影響，不建立 tombstone、刪除工作或任何列。"""
    result = preview(actor, identity)
    validate_api(result, "DeletionImpact")
    return JsonResponse(result)


@allowed_methods(["GET", "POST"])
@api
def deletion_requests(request: HttpRequest, actor: Account, identity: UUID) -> JsonResponse:
    """同一路徑承載宣告與讀回：POST 宣告來源失效，GET 讀最新刪除工作。

    POST 同交易寫 tombstone 與逐項工作，政策未放行時停在 BLOCKED；GET 尚未宣告時 404，
    不以空集合假裝已刪除。"""
    if request.method == "GET":
        result = serialize(latest(actor, identity))
        validate_api(result, "DeletionRequestView")
        return JsonResponse(result)

    def authorize(_previous: JsonObject) -> None:
        source_for(actor, identity)
    response = replay(actor, request.path, request.headers.get("Idempotency-Key", ""), {},
                      lambda: serialize(declare(actor, identity, db_now())), authorize)
    validate_api(response, "DeletionRequestView")
    return JsonResponse(response, status=201)
