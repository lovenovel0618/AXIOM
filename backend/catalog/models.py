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
    enabled: models.BooleanField[bool, bool] = models.BooleanField(default=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["id", "tenant"], name="account_tenant_identity")]


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

    seal: models.ForeignKey[SealRegistration | None, SealRegistration | None] = models.ForeignKey("SealRegistration", on_delete=models.PROTECT, null=True)
    seal_id: UUID | None

    class Meta:
        constraints = [models.CheckConstraint(condition=models.Q(status__in=["DRAFT", "VALIDATING", "READY"]), name="research_state_local_status"),
                       models.CheckConstraint(condition=~models.Q(status="READY") | models.Q(seal__isnull=False), name="research_state_ready_requires_seal")]


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


class SealRegistration(models.Model):
    """公有 DB 的不透明封存登記；tokens／final 檔與密鑰只在 Evaluator 域。"""
    id: models.UUIDField[UUID, UUID] = models.UUIDField(primary_key=True,default=uuid4,editable=False)
    tenant: models.ForeignKey[Tenant, Tenant] = models.ForeignKey(Tenant,on_delete=models.PROTECT)
    tenant_id: UUID
    research_version: models.OneToOneField[ResearchVersion, ResearchVersion] = models.OneToOneField(ResearchVersion,on_delete=models.PROTECT)
    research_version_id: UUID
    run: models.OneToOneField[RuntimeRun, RuntimeRun] = models.OneToOneField(RuntimeRun,on_delete=models.PROTECT)
    run_id: UUID
    sealed_test_id: models.UUIDField[UUID, UUID] = models.UUIDField()
    source_sha256: models.CharField[str, str] = models.CharField(max_length=64)
    protocol_hash: models.CharField[str, str] = models.CharField(max_length=64)
    authority_epoch: models.UUIDField[UUID, UUID] = models.UUIDField()
    authority_sequence: models.PositiveBigIntegerField[int, int] = models.PositiveBigIntegerField()
    attestation_hash: models.CharField[str, str] = models.CharField(max_length=64)
    available: models.BooleanField[bool, bool] = models.BooleanField(default=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["id","tenant"],name="seal_registration_tenant_identity")]


class EvidenceBundle(models.Model):
    """READY 版本的不變證據包；只引用既有產物與登記，不生成新的科學主張。"""
    id: models.UUIDField[UUID, UUID] = models.UUIDField(primary_key=True,default=uuid4,editable=False)
    tenant: models.ForeignKey[Tenant, Tenant] = models.ForeignKey(Tenant,on_delete=models.PROTECT)
    tenant_id: UUID
    research_version: models.ForeignKey[ResearchVersion, ResearchVersion] = models.ForeignKey(ResearchVersion,on_delete=models.PROTECT)
    research_version_id: UUID
    run: models.ForeignKey[RuntimeRun, RuntimeRun] = models.ForeignKey(RuntimeRun,on_delete=models.PROTECT)
    run_id: UUID
    created_at: models.DateTimeField[datetime, datetime] = models.DateTimeField(default=timezone.now)
    status: models.CharField[str, str] = models.CharField(max_length=12,default="ACTIVE")
    revision: models.PositiveIntegerField[int, int] = models.PositiveIntegerField(default=0)
    document: models.JSONField[JsonObject, JsonObject] = models.JSONField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["id","tenant"],name="evidence_bundle_tenant_identity"),
                       models.CheckConstraint(condition=models.Q(status__in=["ACTIVE","QUARANTINED"]),name="evidence_bundle_valid_status")]


class DeletionRequest(models.Model):
    """來源失效宣告；政策未放行前只停在 BLOCKED，不推進衍生傳播。"""
    id: models.UUIDField[UUID, UUID] = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    tenant: models.ForeignKey[Tenant, Tenant] = models.ForeignKey(Tenant, on_delete=models.PROTECT)
    tenant_id: UUID
    dataset_version: models.ForeignKey[DatasetVersion, DatasetVersion] = models.ForeignKey(DatasetVersion, on_delete=models.PROTECT)
    dataset_version_id: UUID
    requested_by: models.ForeignKey[Account, Account] = models.ForeignKey(Account, on_delete=models.PROTECT)
    requested_by_id: UUID
    created_at: models.DateTimeField[datetime, datetime] = models.DateTimeField(default=timezone.now)
    status: models.CharField[str, str] = models.CharField(max_length=12, default="REQUESTED")
    blocked_code: models.CharField[str | None, str | None] = models.CharField(max_length=40, null=True)
    policy_status: models.CharField[str, str] = models.CharField(max_length=8, default="BLOCKED")
    revision: models.PositiveIntegerField[int, int] = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["id", "tenant"], name="deletion_request_tenant_identity"),
                       models.CheckConstraint(condition=models.Q(status__in=["REQUESTED", "BLOCKED", "PROPAGATING", "COMPLETED", "FAILED"]), name="deletion_request_valid_status"),
                       models.CheckConstraint(condition=models.Q(policy_status__in=["BLOCKED", "ACTIVE"]), name="deletion_request_policy_status"),
                       models.CheckConstraint(condition=~models.Q(status="BLOCKED") | models.Q(blocked_code__isnull=False), name="deletion_request_blocked_reason")]


class DeletionTarget(models.Model):
    """受影響物件與其動作；重試與錯誤逐項保留，不彙總成單一結果。"""
    id: models.UUIDField[UUID, UUID] = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    deletion_request: models.ForeignKey[DeletionRequest, DeletionRequest] = models.ForeignKey(DeletionRequest, on_delete=models.PROTECT)
    deletion_request_id: UUID
    tenant: models.ForeignKey[Tenant, Tenant] = models.ForeignKey(Tenant, on_delete=models.PROTECT)
    tenant_id: UUID
    object_type: models.CharField[str, str] = models.CharField(max_length=32)
    object_id: models.UUIDField[UUID, UUID] = models.UUIDField()
    action: models.CharField[str, str] = models.CharField(max_length=16)
    outcome: models.CharField[str, str] = models.CharField(max_length=8, default="PENDING")
    attempts: models.PositiveIntegerField[int, int] = models.PositiveIntegerField(default=0)
    last_error: models.CharField[str | None, str | None] = models.CharField(max_length=40, null=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["deletion_request", "object_type", "object_id", "action"], name="deletion_target_unique_action"),
                       models.CheckConstraint(condition=models.Q(object_type__in=["DatasetVersion", "Artifact", "ResearchVersion", "EvidenceBundle"]), name="deletion_target_object_type"),
                       models.CheckConstraint(condition=models.Q(action__in=["TOMBSTONE", "PURGE_DERIVED"]), name="deletion_target_valid_action"),
                       models.CheckConstraint(condition=models.Q(outcome__in=["PENDING", "DONE", "BLOCKED", "FAILED"]), name="deletion_target_valid_outcome")]


class Tombstone(models.Model):
    """權威有效性來源；寫入即生效，不可改、不可刪。"""
    id: models.UUIDField[UUID, UUID] = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    tenant: models.ForeignKey[Tenant, Tenant] = models.ForeignKey(Tenant, on_delete=models.PROTECT)
    tenant_id: UUID
    deletion_request: models.ForeignKey[DeletionRequest, DeletionRequest] = models.ForeignKey(DeletionRequest, on_delete=models.PROTECT)
    deletion_request_id: UUID
    object_type: models.CharField[str, str] = models.CharField(max_length=32)
    object_id: models.UUIDField[UUID, UUID] = models.UUIDField()
    created_at: models.DateTimeField[datetime, datetime] = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["tenant", "object_type", "object_id"], name="tombstone_object_unique"),
                       models.CheckConstraint(condition=models.Q(object_type__in=["DatasetVersion", "Artifact", "ResearchVersion", "EvidenceBundle"]), name="tombstone_object_type")]


class EquationVersion(models.Model):
    """不可變公式版本；身分即 canonical DSL 的 SHA-256，同租戶同身分只留一列。"""
    id: models.UUIDField[UUID, UUID] = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    tenant: models.ForeignKey[Tenant, Tenant] = models.ForeignKey(Tenant, on_delete=models.PROTECT)
    tenant_id: UUID
    created_at: models.DateTimeField[datetime, datetime] = models.DateTimeField(default=timezone.now)
    identity_hash: models.CharField[str, str] = models.CharField(max_length=64)
    dsl_version: models.CharField[str, str] = models.CharField(max_length=8)
    document: models.JSONField[JsonObject, JsonObject] = models.JSONField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["id", "tenant"], name="equation_version_tenant_identity"),
                       models.UniqueConstraint(fields=["tenant", "identity_hash", "dsl_version"], name="equation_version_identity_hash"),
                       models.CheckConstraint(condition=models.Q(dsl_version="1.0"), name="equation_version_dsl_version"),
                       models.CheckConstraint(condition=models.Q(identity_hash__regex="^[0-9a-f]{64}$"), name="equation_version_identity_hash_format")]


class ObservationSplit(models.Model):
    """單題觀測切分的不可變 recipe；同資料版本同 row_ids_hash 只留一列，不重建身分。"""
    id: models.UUIDField[UUID, UUID] = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    tenant: models.ForeignKey[Tenant, Tenant] = models.ForeignKey(Tenant, on_delete=models.PROTECT)
    tenant_id: UUID
    dataset_version: models.ForeignKey[DatasetVersion, DatasetVersion] = models.ForeignKey(DatasetVersion, on_delete=models.PROTECT)
    dataset_version_id: UUID
    row_ids_hash: models.CharField[str, str] = models.CharField(max_length=64)
    document: models.JSONField[JsonObject, JsonObject] = models.JSONField()
    created_at: models.DateTimeField[datetime, datetime] = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["id", "tenant"], name="observation_split_tenant_identity"),
                       models.UniqueConstraint(fields=["dataset_version", "row_ids_hash"], name="observation_split_row_hash_unique"),
                       models.CheckConstraint(condition=models.Q(row_ids_hash__regex="^[0-9a-f]{64}$"), name="observation_split_row_hash_format")]


class RepresentationSpec(models.Model):
    """M1 的識別表徵 recipe；FitRun 與 FrozenCandidate 必須引用同一份不可變表徵。"""
    id: models.UUIDField[UUID, UUID] = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    tenant: models.ForeignKey[Tenant, Tenant] = models.ForeignKey(Tenant, on_delete=models.PROTECT)
    tenant_id: UUID
    research_version: models.ForeignKey[ResearchVersion, ResearchVersion] = models.ForeignKey(ResearchVersion, on_delete=models.PROTECT)
    research_version_id: UUID
    dataset_version: models.ForeignKey[DatasetVersion, DatasetVersion] = models.ForeignKey(DatasetVersion, on_delete=models.PROTECT)
    dataset_version_id: UUID
    observation_split: models.ForeignKey[ObservationSplit, ObservationSplit] = models.ForeignKey(ObservationSplit, on_delete=models.PROTECT)
    observation_split_id: UUID
    fit_rows_hash: models.CharField[str, str] = models.CharField(max_length=64)
    document: models.JSONField[JsonObject, JsonObject] = models.JSONField()
    created_at: models.DateTimeField[datetime, datetime] = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["id", "tenant"], name="representation_spec_tenant_identity"),
                       models.UniqueConstraint(fields=["research_version", "observation_split", "fit_rows_hash"], name="representation_spec_identity_unique"),
                       models.CheckConstraint(condition=models.Q(fit_rows_hash__regex="^[0-9a-f]{64}$"), name="representation_spec_fit_rows_hash_format")]


class Candidate(models.Model):
    """同一搜尋內的同結構候選只留一列；參數估計與凍結副本另存 FitRun 與 FrozenCandidate。"""
    id: models.UUIDField[UUID, UUID] = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    tenant: models.ForeignKey[Tenant, Tenant] = models.ForeignKey(Tenant, on_delete=models.PROTECT)
    tenant_id: UUID
    search_run: models.ForeignKey[RuntimeRun, RuntimeRun] = models.ForeignKey(RuntimeRun, on_delete=models.PROTECT)
    search_run_id: UUID
    equation_version: models.ForeignKey[EquationVersion, EquationVersion] = models.ForeignKey(EquationVersion, on_delete=models.PROTECT)
    equation_version_id: UUID
    development_rank: models.PositiveIntegerField[int, int] = models.PositiveIntegerField()
    document: models.JSONField[JsonObject, JsonObject] = models.JSONField()
    created_at: models.DateTimeField[datetime, datetime] = models.DateTimeField(default=timezone.now)

    class Meta:
        indexes = [models.Index(fields=["search_run", "development_rank"], name="candidate_rank_index")]
        constraints = [models.UniqueConstraint(fields=["id", "tenant"], name="candidate_tenant_identity"),
                       models.UniqueConstraint(fields=["search_run", "equation_version"], name="candidate_search_structure_unique"),
                       models.CheckConstraint(condition=models.Q(development_rank__gte=1), name="candidate_development_rank")]


class FitRun(models.Model):
    """一次擬合的完整結果；run 與公式／資料／切分／表徵引用皆不可變且同租戶。"""
    id: models.UUIDField[UUID, UUID] = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    tenant: models.ForeignKey[Tenant, Tenant] = models.ForeignKey(Tenant, on_delete=models.PROTECT)
    tenant_id: UUID
    run: models.OneToOneField[RuntimeRun, RuntimeRun] = models.OneToOneField(RuntimeRun, on_delete=models.PROTECT)
    run_id: UUID
    equation_version: models.ForeignKey[EquationVersion, EquationVersion] = models.ForeignKey(EquationVersion, on_delete=models.PROTECT)
    equation_version_id: UUID
    dataset_version: models.ForeignKey[DatasetVersion, DatasetVersion] = models.ForeignKey(DatasetVersion, on_delete=models.PROTECT)
    dataset_version_id: UUID
    observation_split: models.ForeignKey[ObservationSplit, ObservationSplit] = models.ForeignKey(ObservationSplit, on_delete=models.PROTECT)
    observation_split_id: UUID
    representation_artifact: models.ForeignKey[RepresentationSpec, RepresentationSpec] = models.ForeignKey(RepresentationSpec, on_delete=models.PROTECT)
    representation_artifact_id: UUID
    fit_rows_hash: models.CharField[str, str] = models.CharField(max_length=64)
    document: models.JSONField[JsonObject, JsonObject] = models.JSONField()
    created_at: models.DateTimeField[datetime, datetime] = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["id", "tenant"], name="fit_run_tenant_identity"),
                       models.CheckConstraint(condition=models.Q(fit_rows_hash__regex="^[0-9a-f]{64}$"), name="fit_run_fit_rows_hash_format")]


class FrozenCandidate(models.Model):
    """凍結後的候選副本；明確綁定單一 FitRun，凍結後參數、排名與來源皆不可改。"""
    id: models.UUIDField[UUID, UUID] = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    tenant: models.ForeignKey[Tenant, Tenant] = models.ForeignKey(Tenant, on_delete=models.PROTECT)
    tenant_id: UUID
    candidate: models.ForeignKey[Candidate, Candidate] = models.ForeignKey(Candidate, on_delete=models.PROTECT)
    candidate_id: UUID
    fit_run: models.ForeignKey[FitRun, FitRun] = models.ForeignKey(FitRun, on_delete=models.PROTECT)
    fit_run_id: UUID
    equation_version: models.ForeignKey[EquationVersion, EquationVersion] = models.ForeignKey(EquationVersion, on_delete=models.PROTECT)
    equation_version_id: UUID
    dataset_version: models.ForeignKey[DatasetVersion, DatasetVersion] = models.ForeignKey(DatasetVersion, on_delete=models.PROTECT)
    dataset_version_id: UUID
    observation_split: models.ForeignKey[ObservationSplit, ObservationSplit] = models.ForeignKey(ObservationSplit, on_delete=models.PROTECT)
    observation_split_id: UUID
    representation_artifact: models.ForeignKey[RepresentationSpec, RepresentationSpec] = models.ForeignKey(RepresentationSpec, on_delete=models.PROTECT)
    representation_artifact_id: UUID
    development_rank: models.PositiveIntegerField[int, int] = models.PositiveIntegerField()
    dsl_identity_hash: models.CharField[str, str] = models.CharField(max_length=64)
    parameter_binding_hash: models.CharField[str, str] = models.CharField(max_length=64)
    document: models.JSONField[JsonObject, JsonObject] = models.JSONField()
    created_at: models.DateTimeField[datetime, datetime] = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["id", "tenant"], name="frozen_candidate_tenant_identity"),
                       models.UniqueConstraint(fields=["candidate", "fit_run"], name="frozen_candidate_selection_unique"),
                       models.CheckConstraint(condition=models.Q(development_rank__gte=1), name="frozen_candidate_development_rank"),
                       models.CheckConstraint(condition=models.Q(dsl_identity_hash__regex="^[0-9a-f]{64}$"), name="frozen_candidate_dsl_identity_format"),
                       models.CheckConstraint(condition=models.Q(parameter_binding_hash__regex="^[0-9a-f]{64}$"), name="frozen_candidate_binding_hash_format")]


class FrozenSubmission(models.Model):
    """最終盲測前的不可變提交包；固定 sealed_test 與候選排序，不保存最終結果。"""
    id: models.UUIDField[UUID, UUID] = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    tenant: models.ForeignKey[Tenant, Tenant] = models.ForeignKey(Tenant, on_delete=models.PROTECT)
    tenant_id: UUID
    research_version: models.ForeignKey[ResearchVersion, ResearchVersion] = models.ForeignKey(ResearchVersion, on_delete=models.PROTECT)
    research_version_id: UUID
    verification_plan_artifact: models.ForeignKey[Artifact, Artifact] = models.ForeignKey(Artifact, on_delete=models.PROTECT)
    verification_plan_artifact_id: UUID
    sealed_test_id: models.UUIDField[UUID, UUID] = models.UUIDField()
    metric_version: models.CharField[str, str] = models.CharField(max_length=8, default="2.0")
    snapshot_hash: models.CharField[str, str] = models.CharField(max_length=64)
    status: models.CharField[str, str] = models.CharField(max_length=12, default="FROZEN")
    document: models.JSONField[JsonObject, JsonObject] = models.JSONField()
    created_at: models.DateTimeField[datetime, datetime] = models.DateTimeField(default=timezone.now)

    class Meta:
        indexes = [models.Index(fields=["research_version", "created_at", "id"], name="frozen_submission_page")]
        constraints = [models.UniqueConstraint(fields=["id", "tenant"], name="frozen_submission_tenant_identity"),
                       models.UniqueConstraint(fields=["research_version", "snapshot_hash"], name="frozen_submission_snapshot_unique"),
                       models.CheckConstraint(condition=models.Q(metric_version="2.0"), name="frozen_submission_metric_version"),
                       models.CheckConstraint(condition=models.Q(snapshot_hash__regex="^[0-9a-f]{64}$"), name="frozen_submission_snapshot_format"),
                       models.CheckConstraint(condition=models.Q(status__in=["FROZEN", "EVALUATING", "EVALUATED", "FAILED"]), name="frozen_submission_status")]
