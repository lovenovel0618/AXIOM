"""HTTP 安全邊界：所有 API 經 session／CSRF、現行 actor 鎖與交易包裝。
錯誤只回穩定代碼；登入節流、同源上傳及冪等操作不能旁路授權。

Same-origin session authentication and the T05 catalog HTTP boundary."""
from collections.abc import Callable
from datetime import timedelta
from functools import wraps
import hashlib
import hmac
import logging
from typing import Concatenate, ParamSpec
from uuid import UUID, uuid4
from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.core.exceptions import RequestDataTooBig
from django.db import DatabaseError, transaction
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from runtime.contracts import JsonObject
from runtime.records import db_now
from catalog.models import Account, Audit, LoginThrottle
from catalog.ingest import complete_upload
from catalog.services import actor_for, create_dataset, create_upload, dataset_for, list_datasets, put_upload, replay, upload_for
from catalog.validation import ApiError, decode, validate_api

P = ParamSpec("P")
logger = logging.getLogger(__name__)


def error_response(error: ApiError) -> JsonResponse:
    request_id = str(uuid4())
    response = JsonResponse({"code": error.code, "message": "Request could not be completed", "details": error.details, "request_id": request_id, "retryable": error.status == 503}, status=error.status)
    response["X-Request-ID"] = request_id
    response["Cache-Control"] = "no-store"
    return response


def allowed_methods(methods: list[str]) -> Callable[[Callable[Concatenate[HttpRequest, P], HttpResponse]], Callable[Concatenate[HttpRequest, P], HttpResponse]]:
    def decorate(view: Callable[Concatenate[HttpRequest, P], HttpResponse]) -> Callable[Concatenate[HttpRequest, P], HttpResponse]:
        @wraps(view)
        def wrapped(request: HttpRequest, *args: P.args, **kwargs: P.kwargs) -> HttpResponse:
            if request.method not in methods:
                response = error_response(ApiError("METHOD_NOT_ALLOWED", 405))
                response["Allow"] = ", ".join(methods)
                return response
            return view(request, *args, **kwargs)
        return wrapped
    return decorate


def not_found(_request: HttpRequest, exception: Exception) -> JsonResponse:
    logger.debug("Rejected route category=%s", type(exception).__name__)
    return error_response(ApiError("NOT_FOUND", 404))


def bad_request(_request: HttpRequest, exception: Exception) -> JsonResponse:
    logger.debug("Rejected request category=%s", type(exception).__name__)
    return error_response(ApiError("INVALID_JSON", 400))


def server_error(_request: HttpRequest) -> JsonResponse:
    response = error_response(ApiError("INTERNAL_ERROR", 500))
    logger.error("Unhandled request request_id=%s", response["X-Request-ID"])
    return response


def csrf_failure(_request: HttpRequest, **_failure: object) -> JsonResponse:
    try:
        Audit.objects.create(action="CSRF_DENY", code="CSRF_FAILED")
    except DatabaseError:
        return error_response(ApiError("DEPENDENCY_UNAVAILABLE", 503))
    return error_response(ApiError("CSRF_FAILED", 403))


def api(view: Callable[Concatenate[HttpRequest, Account, P], HttpResponse]) -> Callable[Concatenate[HttpRequest, P], HttpResponse]:
    @wraps(view)
    def wrapped(request: HttpRequest, *args: P.args, **kwargs: P.kwargs) -> HttpResponse:
        actor: Account | None = None
        try:
            identity = request.user.pk
            if not request.user.is_authenticated or not isinstance(identity, int):
                raise ApiError("AUTH_REQUIRED", 401)
            with transaction.atomic():
                actor = actor_for(identity)
                response = view(request, actor, *args, **kwargs)
            response["Cache-Control"] = "no-store"
            return response
        except ApiError as error:
            if actor is None and request.user.is_authenticated:
                actor = Account.objects.filter(user_id=request.user.pk).first()
            Audit.objects.create(tenant_id=None if actor is None else actor.tenant_id, actor_id=None if actor is None else actor.id, action="API_DENY", code=error.code)
            return error_response(error)
        except RequestDataTooBig:
            return error_response(ApiError("UPLOAD_TOO_LARGE", 413))
        except (OSError, DatabaseError):
            return error_response(ApiError("DEPENDENCY_UNAVAILABLE", 503))
    return wrapped


def body(request: HttpRequest, schema: str) -> JsonObject:
    if request.content_type != "application/json":
        raise ApiError("UNSUPPORTED_MEDIA_TYPE", 415)
    value = decode(request.body)
    validate_api(value, schema)
    return value


@allowed_methods(["GET", "POST"])
@api
def datasets(request: HttpRequest, actor: Account) -> JsonResponse:
    if request.method == "GET":
        if set(request.GET).difference({"limit", "cursor"}):
            raise ApiError("INVALID_SCHEMA", 422)
        try:
            limit = int(request.GET.get("limit", "50"))
        except ValueError as error:
            raise ApiError("INVALID_SCHEMA", 422) from error
        if not 1 <= limit <= 200:
            raise ApiError("INVALID_SCHEMA", 422)
        return JsonResponse(list_datasets(actor, request.GET.get("cursor", ""), limit))
    data = body(request, "CreateDataset")
    def authorize(previous: JsonObject) -> None:
        dataset_for(actor, UUID(previous["id"]))
    response = replay(actor, request.path, request.headers.get("Idempotency-Key", ""), data, lambda: create_dataset(actor, data), authorize)
    return JsonResponse(response, status=201)


@allowed_methods(["POST"])
@api
def uploads(request: HttpRequest, actor: Account, identity: UUID) -> JsonResponse:
    dataset = dataset_for(actor, identity, write=True)
    data = body(request, "CreateUpload")
    origin = request.build_absolute_uri("/").rstrip("/")
    def authorize(_previous: JsonObject) -> None:
        dataset_for(actor, identity, write=True)
    response = replay(actor, request.path, request.headers.get("Idempotency-Key", ""), data, lambda: create_upload(actor, dataset, data, origin), authorize)
    return JsonResponse(response, status=201)


@allowed_methods(["PUT"])
@api
def upload_bytes(request: HttpRequest, actor: Account, identity: UUID) -> HttpResponse:
    row = upload_for(actor, identity)
    if request.content_type != "application/octet-stream":
        raise ApiError("UNSUPPORTED_MEDIA_TYPE", 415)
    try:
        length = int(request.META.get("CONTENT_LENGTH", ""))
    except ValueError as error:
        raise ApiError("INVALID_SCHEMA", 422) from error
    if length != row.size_bytes:
        raise ApiError("UPLOAD_TOO_LARGE", 413)
    put_upload(actor, row, request.headers.get("X-Upload-Token", ""), request)
    return HttpResponse(status=204)


@allowed_methods(["POST"])
@api
def complete(request: HttpRequest, actor: Account, identity: UUID) -> HttpResponse:
    row = upload_for(actor, identity)
    data = body(request, "CompleteUpload")
    result = complete_upload(actor, row, data["checksum"], request.headers.get("Idempotency-Key", ""))
    return JsonResponse(result, status=202)


def _throttle_key(request: HttpRequest, username: str) -> str:
    value = request.META.get("REMOTE_ADDR", "") + "\0" + username[:150].casefold()
    return hmac.new(settings.SECRET_KEY.encode("utf-8"), value.encode("utf-8"), hashlib.sha256).hexdigest()


def _try_login(request: HttpRequest, username: str, password: str) -> bool:
    with transaction.atomic():
        now = db_now()
        key = _throttle_key(request, username)
        LoginThrottle.objects.get_or_create(key=key, defaults={"reset_at": now + timedelta(minutes=5)})
        throttle = LoginThrottle.objects.select_for_update().get(pk=key)
        if throttle.reset_at <= now:
            throttle.failures, throttle.reset_at = 0, now + timedelta(minutes=5)
        if throttle.failures >= 5:
            return False
        user = authenticate(request, username=username, password=password)
        actor = None if user is None else Account.objects.filter(user_id=user.pk, enabled=True).first()
        if user is None or actor is None:
            throttle.failures += 1
            throttle.save()
            Audit.objects.create(action="LOGIN", code="AUTH_REQUIRED")
            return False
        throttle.failures = 0
        throttle.save()
        login(request, user)
        Audit.objects.create(tenant_id=actor.tenant_id, actor_id=actor.id, action="LOGIN", code="OK")
        return True


@allowed_methods(["GET", "POST"])
def login_view(request: HttpRequest) -> HttpResponse:
    if request.method == "GET":
        response = render(request, "catalog/login.html")
    elif _try_login(request, request.POST.get("username", ""), request.POST.get("password", "")):
        response = JsonResponse({"status": "ok"})
    else:
        response = error_response(ApiError("AUTH_REQUIRED", 401))
    response["Cache-Control"] = "no-store"
    return response


@allowed_methods(["POST"])
def logout_view(request: HttpRequest) -> JsonResponse:
    actor = Account.objects.filter(user_id=request.user.pk).first() if request.user.is_authenticated else None
    logout(request)
    Audit.objects.create(tenant_id=None if actor is None else actor.tenant_id, actor_id=None if actor is None else actor.id, action="LOGOUT", code="OK")
    return JsonResponse({"status": "ok"}, headers={"Cache-Control": "no-store"})
