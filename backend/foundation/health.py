"""Operational endpoints return no dependency addresses or exception details."""
import logging
from django.conf import settings
from django.db import DatabaseError
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
        with Redis.from_url(settings.REDIS_URL, socket_connect_timeout=2, socket_timeout=2) as client:
            client.ping()
    except (DatabaseError, RedisError):
        logger.warning("Readiness dependency check failed")
        return JsonResponse({"status": "unavailable"}, status=503)
    return JsonResponse({"status": "ok"})
