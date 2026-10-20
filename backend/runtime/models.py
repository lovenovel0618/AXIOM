"""Schema-aligned documents; indexed identities and relations remain SQL-owned."""
from __future__ import annotations
from datetime import datetime
from uuid import UUID, uuid4
from django.db import models
from runtime.contracts import JsonObject


class RuntimeRun(models.Model):
    id: models.UUIDField[UUID, UUID] = models.UUIDField(primary_key=True, editable=False)
    tenant_id: models.UUIDField[UUID, UUID] = models.UUIDField(db_index=True)
    document: models.JSONField[JsonObject, JsonObject] = models.JSONField()
    control_only: models.BooleanField[bool, bool] = models.BooleanField(default=True)
    first_started_at: models.DateTimeField[datetime | None, datetime | None] = models.DateTimeField(null=True)
    queue_deadline: models.DateTimeField[datetime, datetime] = models.DateTimeField()
    available_at: models.DateTimeField[datetime, datetime] = models.DateTimeField()
    last_polled_at: models.DateTimeField[datetime | None, datetime | None] = models.DateTimeField(null=True, db_index=True)

    class Meta:
        constraints = [models.CheckConstraint(condition=models.Q(control_only=True), name="runtime_control_only")]


class InputSnapshot(models.Model):
    run: models.OneToOneField[RuntimeRun, RuntimeRun] = models.OneToOneField(RuntimeRun, on_delete=models.PROTECT, primary_key=True)
    task_input: models.JSONField[JsonObject, JsonObject] = models.JSONField()
    execution: models.JSONField[JsonObject, JsonObject] = models.JSONField()
    budget: models.JSONField[JsonObject, JsonObject] = models.JSONField()
    content_hash: models.CharField[str, str] = models.CharField(max_length=64)


class RuntimeAttempt(models.Model):
    id: models.UUIDField[UUID, UUID] = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    run: models.ForeignKey[RuntimeRun, RuntimeRun] = models.ForeignKey(RuntimeRun, on_delete=models.PROTECT)
    generation: models.PositiveIntegerField[int, int] = models.PositiveIntegerField()
    document: models.JSONField[JsonObject, JsonObject] = models.JSONField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["run", "generation"], name="attempt_run_generation_unique")]


class RunEvent(models.Model):
    id: models.UUIDField[UUID, UUID] = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    run: models.ForeignKey[RuntimeRun, RuntimeRun] = models.ForeignKey(RuntimeRun, on_delete=models.PROTECT)
    sequence: models.PositiveIntegerField[int, int] = models.PositiveIntegerField()
    document: models.JSONField[JsonObject, JsonObject] = models.JSONField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["run", "sequence"], name="run_event_sequence_unique")]
