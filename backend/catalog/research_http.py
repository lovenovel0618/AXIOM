"""Existing v2 research endpoints, bounded to persisted DRAFT operations."""
from uuid import UUID
from django.http import HttpRequest, JsonResponse
from catalog.http import allowed_methods, api, body
from catalog.models import Account, Research
from catalog.research import available_version, create_research, create_version, page, research_dto, research_for, version_for, visible_versions, writable
from catalog.services import replay
from catalog.validation import ApiError, validate_api


def paging(request: HttpRequest) -> tuple[str, int]:
    if set(request.GET).difference({"limit", "cursor"}):
        raise ApiError("INVALID_SCHEMA", 422)
    try:
        limit = int(request.GET.get("limit", "50"))
    except ValueError as error:
        raise ApiError("INVALID_SCHEMA", 422) from error
    if not 1 <= limit <= 200:
        raise ApiError("INVALID_SCHEMA", 422)
    return request.GET.get("cursor", ""), limit


@allowed_methods(["GET", "POST"])
@api
def researches(request: HttpRequest, actor: Account) -> JsonResponse:
    if request.method == "GET":
        cursor, limit = paging(request)
        result = page(Research.objects.filter(owner=actor, tenant_id=actor.tenant_id), actor, "researches", cursor, limit, research_dto)
        validate_api(result, "ResearchPage")
        return JsonResponse(result)
    writable(actor)
    data = body(request, "CreateResearch")
    def authorize(previous: dict[str, object]) -> None:
        research_for(actor, UUID(str(previous["id"])))
    response = replay(actor, request.path, request.headers.get("Idempotency-Key", ""), data, lambda: create_research(actor, data), authorize)
    return JsonResponse(response, status=201)


@allowed_methods(["GET"])
@api
def research_detail(_request: HttpRequest, actor: Account, identity: UUID) -> JsonResponse:
    return JsonResponse(research_dto(research_for(actor, identity)))


@allowed_methods(["GET", "POST"])
@api
def versions(request: HttpRequest, actor: Account, identity: UUID) -> JsonResponse:
    research = research_for(actor, identity)
    if request.method == "GET":
        cursor, limit = paging(request)
        result = page(visible_versions(actor, research), actor, str(identity), cursor, limit, lambda row: row.document)
        validate_api(result, "ResearchVersionPage")
        return JsonResponse(result)
    writable(actor)
    data = body(request, "CreateResearchVersion")
    def authorize(previous: dict[str, object]) -> None:
        version = version_for(actor, UUID(str(previous["id"])))
        available_version(actor, version.dataset_version_id)
    response = replay(actor, request.path, request.headers.get("Idempotency-Key", ""), data, lambda: create_version(actor, research, data), authorize)
    return JsonResponse(response, status=201)


@allowed_methods(["GET"])
@api
def version_detail(_request: HttpRequest, actor: Account, identity: UUID) -> JsonResponse:
    document = version_for(actor, identity).document
    validate_api(document, "ResearchVersion")
    return JsonResponse(document)


@allowed_methods(["POST"])
@api
def validate_draft(_request: HttpRequest, actor: Account, identity: UUID) -> JsonResponse:
    writable(actor)
    version_for(actor, identity)
    raise ApiError("DEPENDENCY_UNAVAILABLE", 503)
