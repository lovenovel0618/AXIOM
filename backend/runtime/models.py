"""持久任務模型：Run 狀態、不可變輸入、Attempt 租約、單調不可變事件、最終評估槽位與評估結果。

Schema-aligned documents; indexed identities and relations remain SQL-owned."""
from __future__ import annotations
from datetime import datetime
from uuid import UUID, uuid4
from django.db import models
from django.utils import timezone
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
        constraints = [models.UniqueConstraint(fields=["id", "tenant_id"], name="runtime_run_tenant_identity")]


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


class RuntimeCheckpoint(models.Model):
    """崩潰重試用的不可變 checkpoint：只保存受控 JSON，永不保存或載入 pickle。"""
    id: models.UUIDField[UUID, UUID] = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    run: models.ForeignKey[RuntimeRun, RuntimeRun] = models.ForeignKey(RuntimeRun, on_delete=models.PROTECT)
    tenant_id: models.UUIDField[UUID, UUID] = models.UUIDField(db_index=True)
    attempt_id: models.UUIDField[UUID, UUID] = models.UUIDField()
    document: models.JSONField[JsonObject, JsonObject] = models.JSONField()
    created_at: models.DateTimeField[datetime, datetime] = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["id", "tenant_id"], name="runtime_checkpoint_tenant_identity")]


class FinalEvaluationSlot(models.Model):
    """最終評估結果槽位：以業務鍵固定唯一 VALIDATE run，不對外曝光也不保存最終結果本身。"""
    id: models.UUIDField[UUID, UUID] = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    tenant_id: models.UUIDField[UUID, UUID] = models.UUIDField(db_index=True)
    submission_id: models.UUIDField[UUID, UUID] = models.UUIDField()
    frozen_candidate_id: models.UUIDField[UUID, UUID] = models.UUIDField()
    metric_version: models.CharField[str, str] = models.CharField(max_length=8, default="2.0")
    run_id: models.UUIDField[UUID, UUID] = models.UUIDField()
    validation_run_id: models.UUIDField[UUID | None, UUID | None] = models.UUIDField(null=True)
    status: models.CharField[str, str] = models.CharField(max_length=12, default="PENDING")
    document: models.JSONField[JsonObject, JsonObject] = models.JSONField()
    created_at: models.DateTimeField[datetime, datetime] = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant_id", "submission_id", "frozen_candidate_id", "metric_version"],
                                    name="final_slot_business_key"),
            models.CheckConstraint(condition=models.Q(metric_version="2.0"), name="final_slot_metric_version"),
            models.CheckConstraint(condition=models.Q(status__in=["PENDING", "COMPLETED", "FAILED"]), name="final_slot_status"),
            models.CheckConstraint(condition=(models.Q(status="COMPLETED") & models.Q(validation_run_id__isnull=False))
                                   | (models.Q(validation_run_id__isnull=True) & ~models.Q(status="COMPLETED")),
                                   name="final_slot_result_reference"),
        ]


class ValidationRun(models.Model):
    """評估結果的不可變權威列；最終結果以提交／候選／metric 唯一，開發結果以 run／split 唯一。

    結果本身只存在 document；欄位只承載唯一鍵與外鍵所需的固定身分，因此同一份結果不可能因換
    run_id 或換 UUID 而重複生效。"""
    id: models.UUIDField[UUID, UUID] = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    tenant_id: models.UUIDField[UUID, UUID] = models.UUIDField(db_index=True)
    run_id: models.UUIDField[UUID, UUID] = models.UUIDField(db_index=True)
    observation_split_id: models.UUIDField[UUID, UUID] = models.UUIDField()
    split_role: models.CharField[str, str] = models.CharField(max_length=16)
    metric_version: models.CharField[str, str] = models.CharField(max_length=8, default="2.0")
    submission_id: models.UUIDField[UUID | None, UUID | None] = models.UUIDField(null=True)
    frozen_candidate_id: models.UUIDField[UUID | None, UUID | None] = models.UUIDField(null=True)
    document: models.JSONField[JsonObject, JsonObject] = models.JSONField()
    created_at: models.DateTimeField[datetime, datetime] = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant_id", "run_id", "observation_split_id", "split_role", "metric_version"],
                                    name="validation_run_development_key"),
            models.UniqueConstraint(fields=["tenant_id", "submission_id", "frozen_candidate_id", "metric_version"],
                                    condition=models.Q(split_role="FINAL_TEST"), name="validation_run_final_key"),
            models.CheckConstraint(condition=models.Q(split_role__in=["FIT", "DEVELOPMENT", "FINAL_TEST"]),
                                   name="validation_run_split_role"),
            models.CheckConstraint(condition=models.Q(metric_version="2.0"), name="validation_run_metric_version"),
            models.CheckConstraint(condition=(models.Q(split_role="FINAL_TEST", submission_id__isnull=False, frozen_candidate_id__isnull=False)
                                              | (~models.Q(split_role="FINAL_TEST") & models.Q(submission_id__isnull=True)
                                                 & models.Q(frozen_candidate_id__isnull=True))),
                                   name="validation_run_final_reference"),
        ]
