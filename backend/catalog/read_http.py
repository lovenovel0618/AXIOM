"""Current-ACL reads for committed local versions and safe JSON artifacts."""
from datetime import datetime
import hashlib
from uuid import UUID
from django.core import signing
from django.db.models import Q
from django.http import HttpRequest, HttpResponse, JsonResponse
from catalog.artifacts import authorized
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


def run_for(actor: Account, identity: UUID) -> RuntimeRun:
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
    row = authorized(actor, identity)
    validate_api(row.document, "Artifact")
    return JsonResponse(row.document)


@allowed_methods(["GET"])
@api
def artifact_content(_request: HttpRequest, actor: Account, identity: UUID) -> HttpResponse:
    row = authorized(actor, identity)
    content = canonical_bytes(row.content)
    if hashlib.sha256(content).hexdigest() != row.document["sha256"] or len(content) != row.document["size_bytes"]:
        raise ApiError("ARTIFACT_UNAVAILABLE", 409)
    response = HttpResponse(content, content_type="application/json")
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Disposition"] = f'attachment; filename="{identity}.json"'
    response["Content-Security-Policy"] = "default-src 'none'; sandbox"
    return response
