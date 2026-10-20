"""Tenant-scoped catalog and immutable upload receipts."""
from __future__ import annotations
from datetime import datetime
from uuid import UUID, uuid4
from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone
from runtime.contracts import JsonObject
from runtime.models import RuntimeRun


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
