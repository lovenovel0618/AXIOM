"""Exercise the real relay, Redis and worker, checking one committed effect."""
import json
import time
from typing import Any
from django.core.management.base import BaseCommand, CommandError
from foundation.models import DispatchProbe, DONE
from foundation.tasks import publish_probe


class Command(BaseCommand):
    help = "Create and observe a synthetic probe through the real worker"

    def handle(self, *args: Any, **options: Any) -> None:
        row = DispatchProbe.objects.create()
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            row.refresh_from_db()
            if row.state == DONE:
                # First delivery must come from the running relay service.
                publish_probe(str(row.id), row.generation)
                publish_probe(str(row.id), row.generation)
                time.sleep(1)
                row.refresh_from_db()
                if row.completions != 1:
                    raise CommandError("Probe completion count is not one")
                self.stdout.write(json.dumps({"status": "PASS", "probe_id": str(row.id), "completions": row.completions}))
                return
            time.sleep(0.2)
        raise CommandError("Probe did not finish within 30 seconds")
