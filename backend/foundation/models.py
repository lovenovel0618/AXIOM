"""Internal synthetic dispatch records, separate from domain RunRecord."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4
from django.db import models

PENDING = "PENDING"
RUNNING = "RUNNING"
DONE = "DONE"


class DispatchProbe(models.Model):
    id: models.UUIDField[UUID, UUID] = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    generation: models.PositiveIntegerField[int, int] = models.PositiveIntegerField(default=0)
    state: models.CharField[str, str] = models.CharField(max_length=7, default=PENDING)
    token: models.UUIDField[UUID | None, UUID | None] = models.UUIDField(null=True)
    lease_until: models.DateTimeField[datetime | None, datetime | None] = models.DateTimeField(null=True)
    completions: models.PositiveIntegerField[int, int] = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(state__in=[PENDING, RUNNING, DONE]), name="probe_valid_state"),
            models.CheckConstraint(condition=models.Q(completions__lte=1), name="probe_at_most_once"),
            models.CheckConstraint(condition=(models.Q(state=DONE, completions=1) | models.Q(state__in=[PENDING, RUNNING], completions=0)), name="probe_completion_state"),
            models.CheckConstraint(condition=(models.Q(state=RUNNING, token__isnull=False, lease_until__isnull=False) | models.Q(state__in=[PENDING, DONE], token__isnull=True, lease_until__isnull=True)), name="probe_lease_state"),
        ]
