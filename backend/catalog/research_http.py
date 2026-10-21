"""Existing v2 research endpoints, bounded to persisted DRAFT operations."""
import re
from uuid import UUID
from django.conf import settings
from django.core import signing
from django.db.models import Q
from django.http import HttpRequest, JsonResponse
from catalog.http import allowed_methods, api, body
from catalog.models import Account, ProfileBinding, Research
from catalog.research import available_version, create_research, create_version, page, research_dto, research_for, version_for, visible_versions, writable
from catalog.services import replay
from catalog.validation import ApiError, validate_api
from catalog.research_state import document_for
from catalog.profile import enqueue_profile
from runtime.contracts import project


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
        result = page(visible_versions(actor, research), actor, str(identity), cursor, limit, document_for)
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
    document = document_for(version_for(actor, identity))
    validate_api(document, "ResearchVersion")
    response = JsonResponse(document)
    response["X-Control-Revision"] = str(document["revision"])
    return response


@allowed_methods(["POST"])
@api
def validate_draft(request: HttpRequest, actor: Account, identity: UUID) -> JsonResponse:
    writable(actor)
    version = version_for(actor, identity)
    available_version(actor, version.dataset_version_id)
    if not settings.PROFILE_ENABLED:
        raise ApiError("DEPENDENCY_UNAVAILABLE",503)
    expected = control_revision(request)
    data = body(request,"CreateProfileRun")
    def authorize(_previous: dict[str,object]) -> None:
        version_for(actor,identity)
        available_version(actor,version.dataset_version_id)
    result = replay(actor,request.path,request.headers.get("Idempotency-Key",""),data,lambda:enqueue_profile(actor,version,data,expected),authorize)
    return JsonResponse(result,status=202)


def control_revision(request: HttpRequest) -> int:
    value = request.headers.get("If-Control-Revision")
    if value is None:
        raise ApiError("PRECONDITION_REQUIRED",428)
    if re.fullmatch(r"\d{1,16}",value,flags=re.ASCII) is None:
        raise ApiError("INVALID_SCHEMA",422)
    return int(value)


@allowed_methods(["GET"])
@api
def runs(request: HttpRequest, actor: Account, identity: UUID) -> JsonResponse:
    version_for(actor,identity)
    cursor, limit = paging(request)
    binding = {"actor":str(actor.id),"tenant":str(actor.tenant_id),"version":str(identity)}
    rows = ProfileBinding.objects.filter(research_version_id=identity,tenant_id=actor.tenant_id).select_related("run").order_by("-run__document__created_at","-run_id")
    if cursor:
        try:
            value = signing.loads(cursor,salt="axiom-profile-runs-v1",max_age=900)
            if value["binding"]!=binding:
                raise ValueError("Cursor scope")
            created, last = value["created"], UUID(value["id"])
            rows = rows.filter(Q(run__document__created_at__lt=created)|Q(run__document__created_at=created,run_id__lt=last))
        except (signing.BadSignature,ValueError,TypeError,KeyError) as error:
            raise ApiError("INVALID_CURSOR",400) from error
    selected = list(rows[:limit+1])
    cursor_out = None
    if len(selected)>limit:
        last_row = selected[limit-1]
        cursor_out = signing.dumps({"binding":binding,"created":last_row.run.document["created_at"],"id":str(last_row.run_id)},salt="axiom-profile-runs-v1")
    result = {"items":[project(row.run.document,"Run") for row in selected[:limit]],"next_cursor":cursor_out}
    validate_api(result,"RunPage")
    return JsonResponse(result)
