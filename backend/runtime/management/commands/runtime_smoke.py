"""Real broker control lifecycle; never reports an INGEST business success."""
import json
import time
from typing import Any
from uuid import UUID
from django.core.management.base import BaseCommand, CommandError
from runtime.control import cancel, enqueue
from runtime.control_fixture import bundle
from runtime.models import RunEvent, RuntimeAttempt, RuntimeRun
from runtime.records import public_attempt, public_run


class Command(BaseCommand):
    help = "Exercise a synthetic INGEST root control lifecycle through Celery"

    def handle(self, *args: Any, **options: Any) -> None:
        documents = bundle()
        tenant = UUID(documents[0]["tenant_id"])
        identity = enqueue(tenant, *documents)
        self._wait(identity, "RUNNING")
        run = public_run(tenant, identity)
        # Give the relay a second pass to prove heartbeats do not change revision.
        time.sleep(3)
        if public_run(tenant, identity)["revision"] != run["revision"]:
            raise CommandError("Heartbeat changed public revision")
        cancel(tenant, identity, run["revision"])
        self._wait(identity, "CANCELLED")
        attempts = list(RuntimeAttempt.objects.filter(run_id=identity))
        if len(attempts) != 1:
            raise CommandError("Duplicate delivery created multiple attempts")
        self.stdout.write(json.dumps({
            "scope": "CONTROL_ONLY", "status": "PASS", "business_ingest_status": "NOT_RUN",
            "run": public_run(tenant, identity), "attempt": public_attempt(tenant, identity, attempts[0].id),
            "event_types": [row.document["event_type"] for row in RunEvent.objects.filter(run_id=identity).order_by("sequence")],
        }, ensure_ascii=False))

    def _wait(self, identity: UUID, status: str) -> None:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if RuntimeRun.objects.get(pk=identity).document["status"] == status:
                return
            time.sleep(0.2)
        raise CommandError(f"Control Run did not reach {status} within 30 seconds")
