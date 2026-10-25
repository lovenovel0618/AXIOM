"""Tenant-scoped reads for committed local versions and safe JSON artifacts."""
from datetime import datetime
import hashlib
from uuid import UUID
from django.core import signing
from django.db.models import Q
from django.http import HttpRequest, HttpResponse, JsonResponse
from catalog.artifacts import authorized
from catalog.candidates import authorized_equation, authorized_fit_run, authorized_frozen_candidate, candidates_page
from catalog.evidence import authorized as evidence_bundle
from catalog.final_evaluation import authorized_result, evaluation_view
from catalog.freezing import authorized_submission
from catalog.http import api, allowed_methods
from catalog.models import Account, DatasetVersion, IngestBinding, ProfileBinding, Reservation
from catalog.services import dataset_for
from catalog.research import version_for
from catalog.validation import ApiError, validate_api
from runtime.contracts import canonical_bytes, project
from runtime.models import RuntimeRun


@allowed_methods(["GET"])
@api
def versions(request: HttpRequest, actor: Account, identity: UUID) -> JsonResponse:
    """以租戶分區查分頁版本，簽章 cursor 綁 actor／資料集且有期限。"""
    dataset_for(actor, identity)
    if set(request.GET).difference({"cursor", "limit"}):
        raise ApiError("INVALID_SCHEMA", 422)
    try:
        limit = int(request.GET.get("limit", "50"))
    except ValueError as error:
        raise ApiError("INVALID_SCHEMA", 422) from error
    if not 1 <= limit <= 200:
        raise ApiError("INVALID_SCHEMA", 422)
    rows = DatasetVersion.objects.filter(dataset_id=identity, tenant_id=actor.tenant_id).order_by("-created_at", "-id")
    cursor = request.GET.get("cursor", "")
    if cursor:
        try:
            value = signing.loads(cursor, salt="axiom-versions-v1", max_age=900)
            if value["actor"] != str(actor.id) or value["dataset"] != str(identity):
                raise ValueError("Cursor scope")
            created, last = datetime.fromisoformat(value["created"]), UUID(value["id"])
            rows = rows.filter(Q(created_at__lt=created) | Q(created_at=created, id__lt=last))
        except (signing.BadSignature, ValueError, TypeError, KeyError) as error:
            raise ApiError("INVALID_CURSOR", 400) from error
    page = list(rows[:limit + 1])
    next_cursor = None
    if len(page) > limit:
        last_row = page[limit - 1]
        next_cursor = signing.dumps({"actor": str(actor.id), "dataset": str(identity), "created": last_row.created_at.isoformat(), "id": str(last_row.id)}, salt="axiom-versions-v1")
    result = {"items": [row.document for row in page[:limit]], "next_cursor": next_cursor}
    validate_api(result, "VersionPage")
    return JsonResponse(result)


@allowed_methods(["GET"])
@api
def dataset_runs(request: HttpRequest, actor: Account, identity: UUID) -> JsonResponse:
    """以租戶分區查資料集的真實 run 分頁，簽章 cursor 綁 actor／資料集且有期限。"""
    dataset_for(actor, identity)
    if set(request.GET).difference({"cursor", "limit"}):
        raise ApiError("INVALID_SCHEMA", 422)
    try:
        limit = int(request.GET.get("limit", "50"))
    except ValueError as error:
        raise ApiError("INVALID_SCHEMA", 422) from error
    if not 1 <= limit <= 200:
        raise ApiError("INVALID_SCHEMA", 422)
    rows = RuntimeRun.objects.filter(tenant_id=actor.tenant_id, control_only=False, document__dataset_id=str(identity)).order_by("-document__created_at", "-id")
    cursor = request.GET.get("cursor", "")
    if cursor:
        try:
            value = signing.loads(cursor, salt="axiom-dataset-runs-v1", max_age=900)
            if value["actor"] != str(actor.id) or value["dataset"] != str(identity):
                raise ValueError("Cursor scope")
            created, last = value["created"], UUID(value["id"])
            rows = rows.filter(Q(document__created_at__lt=created) | Q(document__created_at=created, id__lt=last))
        except (signing.BadSignature, ValueError, TypeError, KeyError) as error:
            raise ApiError("INVALID_CURSOR", 400) from error
    page = list(rows[:limit + 1])
    next_cursor = None
    if len(page) > limit:
        last_row = page[limit - 1]
        next_cursor = signing.dumps({"actor": str(actor.id), "dataset": str(identity), "created": last_row.document["created_at"], "id": str(last_row.id)}, salt="axiom-dataset-runs-v1")
    result = {"items": [project(row.document, "Run") for row in page[:limit]], "next_cursor": next_cursor}
    validate_api(result, "RunPage")
    return JsonResponse(result)


def run_for(actor: Account, identity: UUID) -> RuntimeRun:
    """拒絕 control probe；PROFILE 額外驗研究 owner，INGEST 驗租戶分區。"""
    row = RuntimeRun.objects.filter(pk=identity,tenant_id=actor.tenant_id,control_only=False).first()
    if row is None:
        raise ApiError("NOT_FOUND",404)
    if row.document["type"]=="PROFILE":
        binding = ProfileBinding.objects.get(run=row)
        version_for(actor,binding.research_version_id)
    else:
        dataset_for(actor,UUID(row.document["dataset_id"]))
    return row


@allowed_methods(["GET"])
@api
def run_detail(_request: HttpRequest, actor: Account, identity: UUID) -> JsonResponse:
    """回最新公開 Run 與控制 revision；未知停止成本不能標成已量測或零成本。"""
    row = run_for(actor,identity)
    response = JsonResponse(project(row.document,"Run"))
    response["X-Control-Revision"] = str(row.document["revision"])
    usage_status = "UNKNOWN"
    if row.first_started_at is None:
        usage_status = "NOT_STARTED"
    elif row.document["type"]=="PROFILE":
        if Reservation.objects.get(root__run=row).state=="RELEASED":
            usage_status = "MEASURED_UPPER_BOUND"
    else:
        binding = IngestBinding.objects.get(run=row)
        if row.document["status"] in {"SUCCEEDED","CANCELLED"} or (row.document["status"]=="FAILED" and binding.error_code is not None):
            usage_status = "MEASURED_UPPER_BOUND"
    response["X-Usage-Status"] = usage_status
    return response


@allowed_methods(["GET"])
@api
def artifact_detail(_request: HttpRequest, actor: Account, identity: UUID) -> JsonResponse:
    """重新驗租戶與 access class 後回 metadata，不能藉舊列表或 UUID 繞過。"""
    row = authorized(actor, identity)
    validate_api(row.document, "Artifact")
    return JsonResponse(row.document)


@allowed_methods(["GET"])
@api
def evidence_bundle_detail(_request: HttpRequest, actor: Account, identity: UUID) -> JsonResponse:
    """重新驗租戶與研究 owner 後回證據包，並附目前控制 revision。"""
    row = evidence_bundle(actor,identity)
    response = JsonResponse(row.document)
    response["X-Control-Revision"] = str(row.document["revision"])
    return response


@allowed_methods(["GET"])
@api
def frozen_submission_detail(_request: HttpRequest, actor: Account, identity: UUID) -> JsonResponse:
    """重新驗租戶與研究 owner 後回 FrozenSubmission。"""
    row = authorized_submission(actor, identity)
    return JsonResponse(row.document)


@allowed_methods(["GET"])
@api
def validation_run_detail(_request: HttpRequest, actor: Account, identity: UUID) -> JsonResponse:
    """重新驗租戶、研究 owner 與提交綁定後回最終評估結果；封存細部不因知道 UUID 而可讀。"""
    row = authorized_result(actor, identity)
    return JsonResponse(row.document)


@allowed_methods(["GET"])
@api
def submission_evaluation(_request: HttpRequest, actor: Account, identity: UUID) -> JsonResponse:
    """重新驗租戶與研究 owner 後回槽位最終評估狀態與曝光預算投影；槽位本體不進 HTTP 契約。"""
    result = evaluation_view(actor, identity)
    validate_api(result, "FinalEvaluationView")
    return JsonResponse(result)


@allowed_methods(["GET"])
@api
def run_candidates(request: HttpRequest, actor: Account, identity: UUID) -> JsonResponse:
    """以 SEARCH root 為範圍分頁候選；參數或 cursor 不符契約即拒，不枚舉其他 run 或租戶。"""
    if set(request.GET).difference({"cursor", "limit"}):
        raise ApiError("INVALID_SCHEMA", 422)
    try:
        limit = int(request.GET.get("limit", "50"))
    except ValueError as error:
        raise ApiError("INVALID_SCHEMA", 422) from error
    return JsonResponse(candidates_page(actor, identity, request.GET.get("cursor", ""), limit))


@allowed_methods(["GET"])
@api
def equation_detail(_request: HttpRequest, actor: Account, identity: UUID) -> JsonResponse:
    """重新驗租戶與研究 owner 後回公式版本；DSL 與 hash 供候選顯示。"""
    return JsonResponse(authorized_equation(actor, identity).document)


@allowed_methods(["GET"])
@api
def fit_run_detail(_request: HttpRequest, actor: Account, identity: UUID) -> JsonResponse:
    """重新驗租戶與研究 owner 後回擬合結果；參數與精度供候選比較。"""
    return JsonResponse(authorized_fit_run(actor, identity).document)


@allowed_methods(["GET"])
@api
def frozen_candidate_detail(_request: HttpRequest, actor: Account, identity: UUID) -> JsonResponse:
    """重新驗租戶與研究 owner 後回凍結副本；不因知道 UUID 就放行。"""
    return JsonResponse(authorized_frozen_candidate(actor, identity).document)


@allowed_methods(["GET"])
@api
def artifact_content(_request: HttpRequest, actor: Account, identity: UUID) -> HttpResponse:
    """校驗內容 SHA／大小後以安全 JSON attachment 回傳，禁止瀏覽器把內容當可執行頁面。"""
    row = authorized(actor, identity)
    content = canonical_bytes(row.content)
    if hashlib.sha256(content).hexdigest() != row.document["sha256"] or len(content) != row.document["size_bytes"]:
        raise ApiError("ARTIFACT_UNAVAILABLE", 409)
    response = HttpResponse(content, content_type="application/json")
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Disposition"] = f'attachment; filename="{identity}.json"'
    response["Content-Security-Policy"] = "default-src 'none'; sandbox"
    return response
