"""資料層權威模型：欄位／外鍵具體標註，動態 JSON 只作持久相容邊界。

帳本身分與限額由資料庫 guard 保護；不可變配置與可變狀態分開保存。

Tenant-scoped catalog and immutable upload receipts."""
from __future__ import annotations
from datetime import datetime
from uuid import UUID, uuid4
from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone
from runtime.contracts import JsonObject
from runtime.models import RuntimeAttempt, RuntimeRun


class Tenant(models.Model):
    id: models.UUIDField[UUID, UUID] = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    name: models.TextField[str, str] = models.TextField()


class Account(models.Model):
    id: models.UUIDField[UUID, UUID] = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    user: models.OneToOneField[User, User] = models.OneToOneField(User, on_delete=models.PROTECT)
    user_id: int
    tenant: models.ForeignKey[Tenant, Tenant] = models.ForeignKey(Tenant, on_delete=models.PROTECT)
    tenant_id: UUID
    role: models.CharField[str, str] = models.CharField(max_length=10, default="VIEWER")
    enabled: models.BooleanField[bool, bool] = models.BooleanField(default=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["id", "tenant"], name="account_tenant_identity"), models.CheckConstraint(condition=models.Q(role__in=["RESEARCHER", "VIEWER", "ADMIN"]), name="account_valid_role")]


class Provenance(models.Model):
    id: models.UUIDField[UUID, UUID] = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    tenant: models.ForeignKey[Tenant, Tenant] = models.ForeignKey(Tenant, on_delete=models.PROTECT)
    tenant_id: UUID
    resource_type: models.CharField[str, str] = models.CharField(max_length=32)
    resource_id: models.UUIDField[UUID, UUID] = models.UUIDField()
    document: models.JSONField[JsonObject, JsonObject] = models.JSONField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["id", "tenant"], name="provenance_tenant_identity"), models.UniqueConstraint(fields=["resource_type", "resource_id"], name="provenance_resource_unique")]


class Dataset(models.Model):
    id: models.UUIDField[UUID, UUID] = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    tenant: models.ForeignKey[Tenant, Tenant] = models.ForeignKey(Tenant, on_delete=models.PROTECT)
    tenant_id: UUID
    owner: models.ForeignKey[Account, Account] = models.ForeignKey(Account, on_delete=models.PROTECT)
    owner_id: UUID
    name: models.TextField[str, str] = models.TextField()
    created_at: models.DateTimeField[datetime, datetime] = models.DateTimeField(default=timezone.now)
    provenance_id: models.UUIDField[UUID, UUID] = models.UUIDField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["id", "tenant"], name="dataset_tenant_identity")]


class Grant(models.Model):
    tenant: models.ForeignKey[Tenant, Tenant] = models.ForeignKey(Tenant, on_delete=models.PROTECT)
    tenant_id: UUID
    actor: models.ForeignKey[Account, Account] = models.ForeignKey(Account, on_delete=models.PROTECT)
    actor_id: UUID
    dataset: models.ForeignKey[Dataset, Dataset] = models.ForeignKey(Dataset, on_delete=models.PROTECT, related_name="grants")
    dataset_id: UUID
    permission: models.CharField[str, str] = models.CharField(max_length=6)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["actor", "dataset"], name="dataset_actor_grant_unique"), models.CheckConstraint(condition=models.Q(permission__in=["OWNER", "EDITOR", "READER"]), name="grant_valid_permission")]


class Upload(models.Model):
    id: models.UUIDField[UUID, UUID] = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    tenant: models.ForeignKey[Tenant, Tenant] = models.ForeignKey(Tenant, on_delete=models.PROTECT)
    tenant_id: UUID
    dataset: models.ForeignKey[Dataset, Dataset] = models.ForeignKey(Dataset, on_delete=models.PROTECT)
    dataset_id: UUID
    actor: models.ForeignKey[Account, Account] = models.ForeignKey(Account, on_delete=models.PROTECT)
    actor_id: UUID
    filename: models.TextField[str, str] = models.TextField()
    format: models.CharField[str, str] = models.CharField(max_length=7)
    size_bytes: models.PositiveBigIntegerField[int, int] = models.PositiveBigIntegerField()
    sha256: models.CharField[str, str] = models.CharField(max_length=64)
    created_at: models.DateTimeField[datetime, datetime] = models.DateTimeField(default=timezone.now)
    expires_at: models.DateTimeField[datetime, datetime] = models.DateTimeField()
    status: models.CharField[str, str] = models.CharField(max_length=9, default="OPEN")
    object_version: models.UUIDField[UUID | None, UUID | None] = models.UUIDField(null=True)
    ingest_run_id: models.UUIDField[UUID | None, UUID | None] = models.UUIDField(null=True, unique=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["id", "dataset", "tenant"], name="upload_dataset_tenant_identity"),
            models.CheckConstraint(condition=models.Q(status__in=["OPEN", "COMPLETED", "EXPIRED", "ABORTED"]), name="upload_valid_status"),
            models.CheckConstraint(condition=models.Q(size_bytes__gte=1, size_bytes__lte=52428800), name="upload_size_limit"),
            models.CheckConstraint(condition=~models.Q(status="COMPLETED") | models.Q(object_version__isnull=False, ingest_run_id__isnull=False), name="upload_completed_bindings"),
        ]


class StoredObject(models.Model):
    id: models.UUIDField[UUID, UUID] = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    tenant: models.ForeignKey[Tenant, Tenant] = models.ForeignKey(Tenant, on_delete=models.PROTECT)
    tenant_id: UUID
    dataset: models.ForeignKey[Dataset, Dataset] = models.ForeignKey(Dataset, on_delete=models.PROTECT)
    dataset_id: UUID
    upload: models.OneToOneField[Upload, Upload] = models.OneToOneField(Upload, on_delete=models.PROTECT)
    upload_id: UUID
    sha256: models.CharField[str, str] = models.CharField(max_length=64)
    size_bytes: models.PositiveBigIntegerField[int, int] = models.PositiveBigIntegerField()
    created_at: models.DateTimeField[datetime, datetime] = models.DateTimeField(default=timezone.now)
    provenance_id: models.UUIDField[UUID, UUID] = models.UUIDField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["id", "dataset", "tenant"], name="object_dataset_tenant_identity"), models.UniqueConstraint(fields=["id", "tenant"], name="object_tenant_identity"), models.UniqueConstraint(fields=["id", "upload", "tenant"], name="object_upload_tenant_identity")]


class IdempotentResult(models.Model):
    actor: models.ForeignKey[Account, Account] = models.ForeignKey(Account, on_delete=models.PROTECT)
    scope: models.CharField[str, str] = models.CharField(max_length=64)
    request_hash: models.CharField[str, str] = models.CharField(max_length=64)
    response: models.JSONField[JsonObject, JsonObject] = models.JSONField()
    expires_at: models.DateTimeField[datetime, datetime] = models.DateTimeField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["actor", "scope"], name="idempotency_actor_scope_unique")]


class Audit(models.Model):
    tenant_id: models.UUIDField[UUID | None, UUID | None] = models.UUIDField(null=True)
    actor_id: models.UUIDField[UUID | None, UUID | None] = models.UUIDField(null=True)
    action: models.CharField[str, str] = models.CharField(max_length=32)
    code: models.CharField[str, str] = models.CharField(max_length=40)
    created_at: models.DateTimeField[datetime, datetime] = models.DateTimeField(default=timezone.now)


class LoginThrottle(models.Model):
    key: models.CharField[str, str] = models.CharField(primary_key=True, max_length=64)
    failures: models.PositiveIntegerField[int, int] = models.PositiveIntegerField(default=0)
    reset_at: models.DateTimeField[datetime, datetime] = models.DateTimeField()


class Artifact(models.Model):
    id: models.UUIDField[UUID, UUID] = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    tenant: models.ForeignKey[Tenant, Tenant] = models.ForeignKey(Tenant, on_delete=models.PROTECT)
    tenant_id: UUID
    dataset: models.ForeignKey[Dataset, Dataset] = models.ForeignKey(Dataset, on_delete=models.PROTECT)
    dataset_id: UUID
    owner: models.ForeignKey[Account, Account] = models.ForeignKey(Account, on_delete=models.PROTECT)
    owner_id: UUID
    object: models.ForeignKey[StoredObject | None, StoredObject | None] = models.ForeignKey(StoredObject, null=True, on_delete=models.PROTECT)
    object_id: UUID | None
    content: models.JSONField[JsonObject | None, JsonObject | None] = models.JSONField(null=True)
    document: models.JSONField[JsonObject, JsonObject] = models.JSONField()
    research_version: models.ForeignKey["ResearchVersion | None", "ResearchVersion | None"] = models.ForeignKey("catalog.ResearchVersion", on_delete=models.PROTECT, null=True)
    research_version_id: UUID | None
    provenance_id: models.UUIDField[UUID, UUID] = models.UUIDField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["id", "dataset", "tenant"], name="artifact_dataset_tenant_identity"), models.CheckConstraint(condition=(models.Q(object__isnull=True, content__isnull=False) | models.Q(object__isnull=False, content__isnull=True)), name="artifact_content_source")]


class DatasetVersion(models.Model):
    id: models.UUIDField[UUID, UUID] = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    tenant: models.ForeignKey[Tenant, Tenant] = models.ForeignKey(Tenant, on_delete=models.PROTECT)
    tenant_id: UUID
    dataset: models.ForeignKey[Dataset, Dataset] = models.ForeignKey(Dataset, on_delete=models.PROTECT)
    dataset_id: UUID
    sha256: models.CharField[str, str] = models.CharField(max_length=64)
    document: models.JSONField[JsonObject, JsonObject] = models.JSONField()
    raw: models.ForeignKey[Artifact, Artifact] = models.ForeignKey(Artifact, on_delete=models.PROTECT, related_name="raw_versions")
    raw_id: UUID
    preview: models.ForeignKey[Artifact, Artifact] = models.ForeignKey(Artifact, on_delete=models.PROTECT, related_name="preview_versions")
    preview_id: UUID
    provenance_id: models.UUIDField[UUID, UUID] = models.UUIDField()
    created_at: models.DateTimeField[datetime, datetime] = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["id", "tenant"], name="version_tenant_identity"), models.UniqueConstraint(fields=["dataset", "sha256"], name="dataset_content_version_unique"), models.UniqueConstraint(fields=["id", "dataset", "tenant"], name="version_dataset_tenant_identity")]


class IngestBinding(models.Model):
    run: models.OneToOneField[RuntimeRun, RuntimeRun] = models.OneToOneField("runtime.RuntimeRun", on_delete=models.PROTECT, primary_key=True)
    run_id: UUID
    tenant: models.ForeignKey[Tenant, Tenant] = models.ForeignKey(Tenant, on_delete=models.PROTECT)
    tenant_id: UUID
    dataset: models.ForeignKey[Dataset, Dataset] = models.ForeignKey(Dataset, on_delete=models.PROTECT)
    dataset_id: UUID
    upload: models.OneToOneField[Upload, Upload] = models.OneToOneField(Upload, on_delete=models.PROTECT)
    upload_id: UUID
    actor: models.ForeignKey[Account, Account] = models.ForeignKey(Account, on_delete=models.PROTECT)
    actor_id: UUID
    result: models.ForeignKey[DatasetVersion | None, DatasetVersion | None] = models.ForeignKey(DatasetVersion, null=True, on_delete=models.PROTECT)
    result_id: UUID | None
    error_code: models.CharField[str | None, str | None] = models.CharField(max_length=40, null=True)


class Research(models.Model):
    id: models.UUIDField[UUID, UUID] = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    tenant: models.ForeignKey[Tenant, Tenant] = models.ForeignKey(Tenant, on_delete=models.PROTECT)
    tenant_id: UUID
    owner: models.ForeignKey[Account, Account] = models.ForeignKey(Account, on_delete=models.PROTECT)
    owner_id: UUID
    name: models.TextField[str, str] = models.TextField()
    created_at: models.DateTimeField[datetime, datetime] = models.DateTimeField(default=timezone.now)
    provenance_id: models.UUIDField[UUID, UUID] = models.UUIDField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["id", "tenant"], name="research_tenant_identity")]


class ResearchVersion(models.Model):
    id: models.UUIDField[UUID, UUID] = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    tenant: models.ForeignKey[Tenant, Tenant] = models.ForeignKey(Tenant, on_delete=models.PROTECT)
    tenant_id: UUID
    research: models.ForeignKey[Research, Research] = models.ForeignKey(Research, on_delete=models.PROTECT)
    research_id: UUID
    dataset_version: models.ForeignKey[DatasetVersion, DatasetVersion] = models.ForeignKey(DatasetVersion, on_delete=models.PROTECT)
    dataset_version_id: UUID
    document: models.JSONField[JsonObject, JsonObject] = models.JSONField()
    created_at: models.DateTimeField[datetime, datetime] = models.DateTimeField(default=timezone.now)
    provenance_id: models.UUIDField[UUID, UUID] = models.UUIDField()

    class Meta:
        indexes = [models.Index(fields=["research", "-created_at", "-id"], name="research_version_page")]
        constraints = [models.UniqueConstraint(fields=["id", "tenant"], name="research_version_tenant_identity")]


class ResearchInspection(models.Model):
    id: models.UUIDField[UUID, UUID] = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    tenant: models.ForeignKey[Tenant, Tenant] = models.ForeignKey(Tenant, on_delete=models.PROTECT)
    tenant_id: UUID
    research_version: models.ForeignKey[ResearchVersion, ResearchVersion] = models.ForeignKey(ResearchVersion, on_delete=models.PROTECT)
    research_version_id: UUID
    actor: models.ForeignKey[Account, Account] = models.ForeignKey(Account, on_delete=models.PROTECT)
    actor_id: UUID
    request_hash: models.CharField[str, str] = models.CharField(max_length=64)
    configuration: models.JSONField[JsonObject, JsonObject] = models.JSONField()
    document: models.JSONField[JsonObject, JsonObject] = models.JSONField()
    created_at: models.DateTimeField[datetime, datetime] = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["research_version", "request_hash"], name="research_inspection_request_unique")]


class ResearchBudget(models.Model):
    id: models.UUIDField[UUID, UUID] = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    tenant: models.ForeignKey[Tenant, Tenant] = models.ForeignKey(Tenant, on_delete=models.PROTECT)
    tenant_id: UUID
    research_version: models.OneToOneField[ResearchVersion, ResearchVersion] = models.OneToOneField(ResearchVersion, on_delete=models.PROTECT)
    research_version_id: UUID
    document: models.JSONField[JsonObject, JsonObject] = models.JSONField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["id", "tenant"], name="research_budget_tenant_identity")]


class RootBudget(models.Model):
    id: models.UUIDField[UUID, UUID] = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    tenant: models.ForeignKey[Tenant, Tenant] = models.ForeignKey(Tenant, on_delete=models.PROTECT)
    tenant_id: UUID
    run: models.OneToOneField[RuntimeRun, RuntimeRun] = models.OneToOneField(RuntimeRun, on_delete=models.PROTECT)
    run_id: UUID
    research_budget: models.ForeignKey[ResearchBudget, ResearchBudget] = models.ForeignKey(ResearchBudget, on_delete=models.PROTECT)
    research_budget_id: UUID
    document: models.JSONField[JsonObject, JsonObject] = models.JSONField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["id", "tenant"], name="root_budget_tenant_identity")]


class Reservation(models.Model):
    id: models.UUIDField[UUID, UUID] = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    root: models.OneToOneField[RootBudget, RootBudget] = models.OneToOneField(RootBudget, on_delete=models.PROTECT)
    root_id: UUID
    requested: models.JSONField[JsonObject, JsonObject] = models.JSONField()
    held: models.JSONField[JsonObject, JsonObject] = models.JSONField()
    state: models.CharField[str, str] = models.CharField(max_length=9, default="HELD")

    class Meta:
        constraints = [models.CheckConstraint(condition=models.Q(state__in=["HELD", "UNCERTAIN", "RELEASED"]), name="reservation_state_valid")]


class UsageReceipt(models.Model):
    id: models.UUIDField[UUID, UUID] = models.UUIDField(primary_key=True, editable=False)
    root: models.ForeignKey[RootBudget, RootBudget] = models.ForeignKey(RootBudget, on_delete=models.PROTECT)
    root_id: UUID
    attempt: models.ForeignKey["RuntimeAttempt", "RuntimeAttempt"] = models.ForeignKey("runtime.RuntimeAttempt", on_delete=models.PROTECT)
    attempt_id: UUID
    sequence: models.PositiveIntegerField[int, int] = models.PositiveIntegerField()
    document: models.JSONField[JsonObject, JsonObject] = models.JSONField()
    content_hash: models.CharField[str, str] = models.CharField(max_length=64)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["attempt", "sequence"], name="usage_attempt_sequence_unique")]


class ResearchState(models.Model):
    research_version: models.OneToOneField[ResearchVersion, ResearchVersion] = models.OneToOneField(ResearchVersion, on_delete=models.PROTECT, primary_key=True)
    research_version_id: UUID
    tenant: models.ForeignKey[Tenant, Tenant] = models.ForeignKey(Tenant, on_delete=models.PROTECT)
    tenant_id: UUID
    revision: models.PositiveBigIntegerField[int, int] = models.PositiveBigIntegerField(default=0)
    status: models.CharField[str, str] = models.CharField(max_length=10, default="DRAFT")
    active_run: models.ForeignKey[RuntimeRun | None, RuntimeRun | None] = models.ForeignKey(RuntimeRun, on_delete=models.PROTECT, null=True)
    active_run_id: UUID | None
    quality: models.ForeignKey[Artifact | None, Artifact | None] = models.ForeignKey(Artifact, on_delete=models.PROTECT, null=True, related_name="quality_states")
    quality_id: UUID | None
    structure: models.ForeignKey[Artifact | None, Artifact | None] = models.ForeignKey(Artifact, on_delete=models.PROTECT, null=True, related_name="structure_states")
    structure_id: UUID | None

    class Meta:
        constraints = [models.CheckConstraint(condition=models.Q(status__in=["DRAFT", "VALIDATING"]), name="research_state_local_status")]


class ProfileBinding(models.Model):
    run: models.OneToOneField[RuntimeRun, RuntimeRun] = models.OneToOneField(RuntimeRun, on_delete=models.PROTECT, primary_key=True)
    run_id: UUID
    tenant: models.ForeignKey[Tenant, Tenant] = models.ForeignKey(Tenant, on_delete=models.PROTECT)
    tenant_id: UUID
    research_version: models.ForeignKey[ResearchVersion, ResearchVersion] = models.ForeignKey(ResearchVersion, on_delete=models.PROTECT)
    research_version_id: UUID
    dataset: models.ForeignKey[Dataset, Dataset] = models.ForeignKey(Dataset, on_delete=models.PROTECT)
    dataset_id: UUID
    actor: models.ForeignKey[Account, Account] = models.ForeignKey(Account, on_delete=models.PROTECT)
    actor_id: UUID
    root_budget: models.OneToOneField[RootBudget, RootBudget] = models.OneToOneField(RootBudget, on_delete=models.PROTECT)
    root_budget_id: UUID
    result: models.ForeignKey[Artifact | None, Artifact | None] = models.ForeignKey(Artifact, on_delete=models.PROTECT, null=True, related_name="profile_results")
    result_id: UUID | None
    error_code: models.CharField[str | None, str | None] = models.CharField(max_length=40, null=True)


class ResearchEvent(models.Model):
    id: models.UUIDField[UUID, UUID] = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    research_version: models.ForeignKey[ResearchVersion, ResearchVersion] = models.ForeignKey(ResearchVersion, on_delete=models.PROTECT)
    research_version_id: UUID
    sequence: models.PositiveBigIntegerField[int, int] = models.PositiveBigIntegerField()
    document: models.JSONField[JsonObject, JsonObject] = models.JSONField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["research_version", "sequence"], name="research_event_sequence_unique")]
