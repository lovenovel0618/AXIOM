"""Operational endpoints return no dependency addresses or exception details."""
import logging
import os
from django.conf import settings
from django.db import DatabaseError, connection
from django.db.migrations.recorder import MigrationRecorder
from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_safe
from redis import Redis
from redis.exceptions import RedisError
from foundation.models import DispatchProbe

logger = logging.getLogger(__name__)


@require_safe
def live(_request: HttpRequest) -> JsonResponse:
    return JsonResponse({"status": "ok"})


@require_safe
def ready(_request: HttpRequest) -> JsonResponse:
    try:
        DispatchProbe.objects.exists()
        required = {("foundation", "0001_initial"), ("runtime", "0001_initial"), ("runtime", "0002_document_guards"), ("runtime", "0003_runtimerun_runtime_run_tenant_identity"), ("catalog", "0002_tenant_guards"), ("sessions", "0001_initial"), ("catalog", "0004_ingest_guards"), ("catalog", "0006_research_guards"), ("catalog", "0008_inspection_guards"), ("runtime", "0004_remove_runtimerun_runtime_control_only")}
        if required.difference(MigrationRecorder(connection).applied_migrations()):
            return JsonResponse({"status": "unavailable"}, status=503)
        if not settings.OBJECT_ROOT.is_dir() or not os.access(settings.OBJECT_ROOT, os.W_OK):
            return JsonResponse({"status": "unavailable"}, status=503)
        with Redis.from_url(settings.REDIS_URL, socket_connect_timeout=2, socket_timeout=2) as client:
            client.ping()
    except (DatabaseError, RedisError):
        logger.warning("Readiness dependency check failed")
        return JsonResponse({"status": "unavailable"}, status=503)
    return JsonResponse({"status": "ok"})
