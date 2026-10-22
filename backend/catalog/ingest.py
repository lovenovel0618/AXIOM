"""明確啟用的真正匯入：固定原檔、隔離解析、重驗租戶歸屬與原子版本提交。

Opt-in business INGEST: immutable enqueue, tenant-scoped reads and fenced commit."""
import hashlib
import math
import resource
import time
from uuid import UUID, uuid4
from django.conf import settings
from django.db import DatabaseError, transaction
from catalog.artifacts import publish, register
from catalog.ingest_manifest import configured_limits, documents, environment
from catalog.models import Account, Audit, IngestBinding, Provenance, Upload
from catalog.services import actor_for, provenance, require_key, upload_for, upload_record, verify_staged
from catalog.storage import LocalVersionStore, StorageRejected
from catalog.validation import ApiError
from ingestion.limits import ImportLimits, ImportRejected
from ingestion.supervisor import inspect_bytes
from runtime.completion import finish, confirm_business_stopped
from runtime.contracts import JsonObject
from runtime.budget_types import BudgetUsage
from runtime.control import Lease, check_submission, claim, enqueue, recover
from runtime.models import RuntimeRun
from runtime.records import ControlError, db_now, public_run, snapshot_for


def complete_upload(actor: Account, row: Upload, checksum: str, key: str) -> JsonObject:
    """驗 checksum 與固定物件後建立真正 INGEST；重送同 upload 回同租戶 root。"""
    require_key(key)
    if checksum != row.sha256:
        raise ApiError("CHECKSUM_MISMATCH", 422)
    if row.status == "COMPLETED" and row.ingest_run_id is not None:
        return public_run(actor.tenant_id, row.ingest_run_id)
    if row.status != "OPEN" or row.expires_at <= db_now():
        raise ApiError("INVALID_TRANSITION", 409)
    verify_staged(actor, row.id)
    limits = configured_limits()
    input_id, source_id = uuid4(), uuid4()
    record, task, execution, budget = documents(actor, row, limits, str(input_id), str(source_id))
    source = Provenance.objects.get(resource_type="StoredObject", resource_id=row.object_version, tenant_id=actor.tenant_id)
    provenance(actor, "Run", UUID(record["id"]), source_id, source)
    binding = IngestBinding(run_id=UUID(record["id"]), tenant_id=actor.tenant_id, dataset_id=row.dataset_id, upload=row, actor=actor)
    register(actor, binding, input_id, task, source)
    identity = enqueue(actor.tenant_id, record, task, execution, budget, control_only=False)
    binding.save(force_insert=True)
    row.status, row.ingest_run_id = "COMPLETED", identity
    row.save(update_fields=["status", "ingest_run_id"])
    upload_record(row)
    Audit.objects.create(tenant_id=actor.tenant_id, actor_id=actor.id, action="COMPLETE_UPLOAD", code="OK")
    return public_run(actor.tenant_id, identity)


def current(binding: IngestBinding) -> tuple[Account, Upload]:
    """背景執行也重新驗 User／Account 與租戶資料集歸屬，不沿用派送時的查詢結果。"""
    account = Account.objects.get(pk=binding.actor_id, tenant_id=binding.tenant_id)
    actor = actor_for(account.user_id)
    if not actor.user.is_active:
        raise ApiError("FORBIDDEN", 403)
    upload = upload_for(actor, binding.upload_id)
    if upload.ingest_run_id != binding.run_id or upload.status != "COMPLETED":
        raise ApiError("INVALID_TRANSITION", 409)
    return actor, upload


def inputs(binding: IngestBinding, lease: Lease) -> tuple[bytes, str, ImportLimits]:
    """核對 lease、環境及不可變來源後讀取 bytes；固定 parser 只接受已核准的完整限額。"""
    check_submission(lease)
    with transaction.atomic():
        actor, upload = current(binding)
        run = RuntimeRun.objects.get(pk=binding.run_id)
        snapshot = snapshot_for(run)
        payload = snapshot.task_input["payload"]
        if run.document["environment_digest"] != environment():
            raise ApiError("CHECKPOINT_INCOMPATIBLE", 409)
        if payload["upload_session_id"] != str(upload.id) or payload["object_version"] != str(upload.object_version) or payload["expected_sha256"] != upload.sha256:
            raise ApiError("UPLOAD_OBJECT_CHANGED", 409)
        reference = verify_staged(actor, upload.id)
        content = LocalVersionStore(settings.OBJECT_ROOT).read_verified(reference)
        return content, upload.format, ImportLimits(**payload["import_limits"])


class Meter:
    """量測 parent 與已回收 child 的 CPU／wall 上取整及 RSS 保守上界，不冒充精確計費。"""
    def __init__(self) -> None:
        self.wall = time.monotonic()
        self.cpu = time.process_time()
        child = resource.getrusage(resource.RUSAGE_CHILDREN)
        self.child_cpu = child.ru_utime + child.ru_stime

    def usage(self) -> BudgetUsage:
        child = resource.getrusage(resource.RUSAGE_CHILDREN)
        parent = resource.getrusage(resource.RUSAGE_SELF)
        return {"cpu_seconds": max(0, math.ceil(time.process_time() - self.cpu + child.ru_utime + child.ru_stime - self.child_cpu)),
                "elapsed_wall_seconds": max(0, math.ceil(time.monotonic() - self.wall)),
                "peak_memory_bytes": int((parent.ru_maxrss + child.ru_maxrss) * 1024),
                "gpu_seconds": 0, "tokens": 0, "candidates_generated": 0, "candidates_accepted": 0}


def failed(binding: IngestBinding, run: RuntimeRun, code: str) -> None:
    """記錄不含原值的錯誤診斷與 audit；失敗不提交可用資料版本。"""
    binding.refresh_from_db()
    binding.error_code = code
    binding.save(update_fields=["error_code"])
    source = Provenance.objects.get(pk=UUID(run.document["provenance_id"]), tenant_id=binding.tenant_id)
    artifact = register(binding.actor, binding, uuid4(), {"kind": "ImportDiagnostic", "code": code,
        "metering": "CPU/wall rounded up; memory is sum of process high-water upper bounds"}, source)
    run.document["diagnostic_artifact_ids"].append(str(artifact.id))
    Audit.objects.create(tenant_id=binding.tenant_id, actor_id=binding.actor_id, action="INGEST_FAILED", code=code)


def submit(binding: IngestBinding, lease: Lease, metadata: JsonObject, usage: object) -> None:
    """結果提交前重驗租戶歸屬及來源；版本、Artifact 與 Run 終態在同一交易。"""
    with transaction.atomic():
        actor, _upload = current(binding)
        verify_staged(actor, binding.upload_id)
        def commit() -> None:
            run = RuntimeRun.objects.get(pk=binding.run_id)
            publish(actor, binding, metadata, UUID(run.document["execution_manifest_id"]))
            Audit.objects.create(tenant_id=actor.tenant_id, actor_id=actor.id, action="INGEST_SUCCESS", code="OK")
        finish(lease, usage, commit, lambda run, code: failed(binding, run, code))


def ingest_tick(tenant_id: str, run_id: str, generation: int) -> bool:
    """專用匯入 worker 入口；重送由 lease fencing 擋下，解析與提交錯誤走一致結算。"""
    if not settings.INGEST_ENABLED:
        return False
    tenant, identity = UUID(tenant_id), UUID(run_id)
    binding = IngestBinding.objects.filter(run_id=identity, tenant_id=tenant).first()
    if binding is None:
        return False
    lease = claim(tenant, identity, generation, "ingest:" + str(uuid4()))
    if lease is None:
        return False
    meter = Meter()
    try:
        content, format_name, limits = inputs(binding, lease)
        report = inspect_bytes(content, format_name, limits)
        if report["source_sha256"] != hashlib.sha256(content).hexdigest():
            raise ApiError("UPLOAD_OBJECT_CHANGED", 409)
        submit(binding, lease, report["metadata"], meter.usage())
    except (ApiError, ImportRejected, StorageRejected) as error:
        reject(binding, lease, meter.usage(), error.code)
    except (OSError, DatabaseError):
        reject(binding, lease, meter.usage(), "DEPENDENCY_UNAVAILABLE")
    except ControlError:
        if not confirm_business_stopped(lease, meter.usage()):
            recover(tenant, identity)
        return False
    return True


def reject(binding: IngestBinding, lease: Lease, usage: object, code: str) -> None:
    """原 handler 確認 child 已退出後處理取消／失敗，保留量測而不讓遲到產物提交。"""
    try:
        finish(lease, usage, lambda: None, lambda run, reason: failed(binding, run, reason), code)
    except ControlError:
        if not confirm_business_stopped(lease, usage):
            recover(lease.tenant_id, lease.run_id)
