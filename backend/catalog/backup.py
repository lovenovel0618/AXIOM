"""AX-27 備份與還原核心：一致集（BackupSet）建立、被引用物件驗證與刪除帳本重播。

本模組只提供兩類可在離線測試中重現的能力：把權威 DB 的當下指紋、被引用物件清單與各帳本
高水位收斂成單一 `BackupSet` 文件，以及對既有 `BackupSet` 重跑「引用物件是否仍可讀且
checksum 相符」。金鑰只記指紋、永不落盤，備份檔與金鑰分開保管；缺件一律如實回報，不以
新檔取代原證據，也不因驗證未完成就宣告可還原。
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
from typing import Any, cast
from uuid import UUID
from django.conf import settings
from django.db import connection, transaction
from django.db.models import Max
from catalog.models import (Artifact, DatasetVersion, DeletionRequest, DeletionTarget, EvidenceBundle,
                            EquationVersion, ResearchVersion, StoredObject, Tombstone)
from catalog.storage import LocalVersionStore, ObjectRef, StorageRejected
from mathematics.search import INPUT_SCHEMA_VERSION
from runtime.contracts import JsonObject, canonical_bytes, identity_hash
from runtime.models import RuntimeRun, ValidationRun

BACKUP_SET_VERSION = "1.0"
BACKUP_SET_NAME = "backup-set.json"
OBJECTS_NAME = "objects.json"
CHECKSUMS_NAME = "checksums.json"
MAX_BACKUP_OBJECTS = 100_000
MAX_REPORTED_ITEMS = 20
TERMINAL_RUN_STATES = ("SUCCEEDED", "FAILED", "CANCELLED")
_EVENT_SEQUENCE = Max("runevent__sequence")


@dataclass(frozen=True)
class ObjectEntry:
    """單一被引用物件版本；tenant／upload／version 皆為 UUID，使用者檔名永不進路徑。"""
    tenant: str
    upload: str
    version: str
    sha256: str
    size: int

    @classmethod
    def read(cls, value: object) -> "ObjectEntry":
        """逐欄驗型別，不接受以 str() 隱藏契約錯誤的輸入；缺欄或壞 UUID 一律視為無效。"""
        row = fields(value)
        try:
            tenant, upload, version = (UUID(str(row[key])) for key in ("tenant", "upload", "version"))
            sha256, size = row["sha256"], row["size"]
        except (KeyError, ValueError) as error:
            raise ValueError("BACKUP_SET_INVALID") from error
        if not isinstance(sha256, str) or len(sha256) != 64 or type(size) is not int or size < 1:
            raise ValueError("BACKUP_SET_INVALID")
        return cls(tenant.hex, upload.hex, version.hex, sha256, size)

    def document(self) -> JsonObject:
        return {"tenant": self.tenant, "upload": self.upload, "version": self.version,
                "sha256": self.sha256, "size": self.size}

    def reference(self) -> ObjectRef:
        return ObjectRef(UUID(self.tenant), UUID(self.upload), UUID(self.version), self.sha256, self.size)


@dataclass(frozen=True)
class Verification:
    """物件驗證結果；「找不到」與「內容變形」都必須讓還原失敗，兩者一律列為不可用。"""
    checked: int
    unreadable: tuple[str, ...]

    def ok(self) -> bool:
        return self.checked > 0 and not self.unreadable

    def document(self) -> JsonObject:
        return {"checked": self.checked, "unreadable_count": len(self.unreadable), "ok": self.ok(),
                "unreadable": list(self.unreadable[:MAX_REPORTED_ITEMS])}


@dataclass(frozen=True)
class DispatchReconstruction:
    """Redis 非權威：派送狀態必須能只由 DB 的 Run 列與事件鏈重建。"""
    runs: int
    terminal: int
    unfinished: int
    inconsistent: tuple[str, ...]

    def document(self) -> JsonObject:
        return {"runs": self.runs, "terminal": self.terminal, "unfinished": self.unfinished,
                "event_chain_consistent": not self.inconsistent, "inconsistent_count": len(self.inconsistent),
                "inconsistent": list(self.inconsistent[:MAX_REPORTED_ITEMS])}


def fields(value: object) -> dict[str, object]:
    """收斂未知 JSON 物件；呼叫端仍須逐欄驗型別，不直接信任鍵集合。"""
    if not isinstance(value, dict):
        raise ValueError("BACKUP_SET_INVALID")
    return cast("dict[str, object]", value)


def root() -> Path:
    """備份保管位置；與物件本體及金鑰分開，未設定時用預設路徑。"""
    return Path(settings.BACKUP_ROOT)


def secret_key_fingerprint() -> str:
    """只記 `AXIOM_SECRET_KEY` 的指紋，讓還原端確認為同一把金鑰而不洩漏內容。"""
    return hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).hexdigest()[:16]


def code_version() -> str:
    """雜湊當版 backend 原始碼與契約，避免用舊快照對到新實作。"""
    from catalog.ingest_manifest import code_digest
    return code_digest()


def object_entries() -> tuple[ObjectEntry, ...]:
    """列出所有被 DB 引用的物件版本；超過上限即拒絕，避免靜默截斷。"""
    rows = StoredObject.objects.order_by("id").values_list("tenant_id", "upload_id", "id", "sha256", "size_bytes")
    entries: list[ObjectEntry] = []
    for tenant_id, upload_id, version_id, sha256, size in rows:
        entries.append(ObjectEntry(UUID(str(tenant_id)).hex, UUID(str(upload_id)).hex, UUID(str(version_id)).hex,
                                   str(sha256), int(size)))
        if len(entries) > MAX_BACKUP_OBJECTS:
            raise ValueError("BACKUP_SET_TOO_LARGE")
    return tuple(entries)


def manifest_digest(entries: tuple[ObjectEntry, ...]) -> str:
    return identity_hash([entry.document() for entry in entries])


def authoritative_counts() -> JsonObject:
    """還原後必須逐項比對的權威列數；結果本身只存在 document。"""
    return {
        "dataset_versions": DatasetVersion.objects.count(),
        "research_versions": ResearchVersion.objects.count(),
        "artifacts": Artifact.objects.count(),
        "stored_objects": StoredObject.objects.count(),
        "equation_versions": EquationVersion.objects.count(),
        "evidence_bundles": EvidenceBundle.objects.count(),
        "evidence_bundles_active": EvidenceBundle.objects.filter(status="ACTIVE").count(),
        "validation_runs": ValidationRun.objects.count(),
        "deletion_requests": DeletionRequest.objects.count(),
        "deletion_targets": DeletionTarget.objects.count(),
        "tombstones": Tombstone.objects.count(),
    }


def deletion_ledger() -> JsonObject:
    """刪除／隔離帳本高水位：條數與逐筆身分 digest；重播後必須完全相同。"""
    rows = list(Tombstone.objects.order_by("tenant_id", "object_type", "object_id")
                .values_list("tenant_id", "object_type", "object_id"))
    entries = [[UUID(str(tenant)).hex, str(object_type), UUID(str(identity)).hex] for tenant, object_type, identity in rows]
    return {"tombstones": len(entries), "digest": identity_hash(entries),
            "requests": DeletionRequest.objects.count(), "targets": DeletionTarget.objects.count()}


def outbox_high_water() -> JsonObject:
    """DB outbox 高水位：事件總數與每 root 事件游標的 digest，供還原後比對。"""
    rows = RuntimeRun.objects.annotate(top=_EVENT_SEQUENCE).values_list("id", "document", "top")
    entries: list[list[Any]] = []
    for run_id, document, top in rows:
        cursor = str(fields(document)["current_event_cursor"]).rsplit(":", 1)[-1]
        entries.append([UUID(str(run_id)).hex, int(cursor), int(top or 0)])
    entries.sort()
    return {"runs": len(entries), "events": sum(int(row[2]) for row in entries), "digest": identity_hash(entries)}


def dispatch_reconstruction() -> DispatchReconstruction:
    """以 DB 為唯一權威重建派送狀態：游標必須等於該 root 的最大事件序號。"""
    rows = RuntimeRun.objects.annotate(top=_EVENT_SEQUENCE).values_list("id", "document__status", "document", "top")
    runs = terminal = 0
    inconsistent: list[str] = []
    for run_id, status, document, top in rows:
        runs += 1
        if str(status) in TERMINAL_RUN_STATES:
            terminal += 1
        cursor = str(fields(document)["current_event_cursor"]).rsplit(":", 1)[-1]
        if int(cursor) != int(top or 0):
            inconsistent.append(UUID(str(run_id)).hex)
    return DispatchReconstruction(runs=runs, terminal=terminal, unfinished=runs - terminal,
                                  inconsistent=tuple(inconsistent))


def restore_point() -> JsonObject:
    """DB 還原點：WAL LSN 與資料庫時鐘；復原端據此對齊增量。"""
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_current_wal_lsn()::text, clock_timestamp()")
        row = cursor.fetchone()
    if row is None:
        raise ValueError("BACKUP_SET_INVALID")
    captured = row[1]
    return {"wal_lsn": str(row[0]),
            "captured_at": captured.isoformat() if isinstance(captured, datetime) else str(captured)}


def migration_manifest() -> tuple[str, ...]:
    """已套用遷移清單；還原後必須先跑遷移再開讀流量。"""
    with connection.cursor() as cursor:
        cursor.execute("SELECT app, name FROM django_migrations ORDER BY app, name")
        return tuple(f"{app}.{name}" for app, name in cursor.fetchall())


def capture(created_at: datetime, identity: str) -> tuple[JsonObject, tuple[ObjectEntry, ...]]:
    """在單一 REPEATABLE READ 唯讀交易內收斂一致集。

    規格禁止只拷貝正在寫入的 DB 目錄；此交易提供跨表一致的讀取快照，讓物件清單、帳本高水位
    與還原點彼此對齊，維護窗結束後才由呼叫端寫出檔案。"""
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        point = restore_point()
        migrations = migration_manifest()
        entries = object_entries()
        counts = authoritative_counts()
        ledger = deletion_ledger()
        outbox = outbox_high_water()
        digest = manifest_digest(entries)
    document: JsonObject = {
        "kind": "BackupSet", "backup_set_id": identity, "backup_set_version": BACKUP_SET_VERSION,
        "created_at": created_at.isoformat(),
        "schema_versions": {"migrations": list(migrations), "migration_count": len(migrations)},
        "dsl_version": INPUT_SCHEMA_VERSION, "app_version": code_version(),
        "db_restore_point": point,
        "object_manifest": {"count": len(entries), "digest": digest},
        "secret_key_version": secret_key_fingerprint(),
        "outbox_high_water": outbox,
        "deletion_ledger_high_water": ledger,
        "exposure_ledger_high_water": {"status": "未取得",
                                       "reason": "web 身分沒有 journal socket 與 token；依 Fail-Closed 不推測曝光高水位"},
        "authoritative_counts": counts,
        "storage_location": str(root()),
    }
    return document, entries


def write(document: JsonObject, entries: tuple[ObjectEntry, ...]) -> Path:
    """把一致集落成不可變檔案並附逐檔 checksum；每檔先 fsync 再 fsync 目錄。"""
    directory = root() / str(document["backup_set_id"])
    directory.mkdir(parents=True, exist_ok=True)
    payloads = {BACKUP_SET_NAME: canonical_bytes(document), OBJECTS_NAME: canonical_bytes([entry.document() for entry in entries])}
    artifacts: dict[str, str] = {}
    for name, data in payloads.items():
        artifacts[name] = write_file(directory / name, data)
    write_file(directory / CHECKSUMS_NAME, canonical_bytes(artifacts))
    ensure_durable(directory)
    return directory


def write_file(path: Path, data: bytes) -> str:
    """以 O_NOFOLLOW 建立或覆寫單一檔案並回傳其 SHA-256。"""
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o640)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    return hashlib.sha256(data).hexdigest()


def ensure_durable(directory: Path) -> None:
    """fsync 目錄項，避免當機後檔案存在但目錄未落地。"""
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def read(directory: Path) -> tuple[JsonObject, tuple[ObjectEntry, ...]]:
    """讀回一致集並先驗檔案 checksum；不符即拒絕，不以殘缺備份繼續還原。"""
    try:
        raw_checksums = (directory / CHECKSUMS_NAME).read_bytes()
        raw_document = (directory / BACKUP_SET_NAME).read_bytes()
        raw_objects = (directory / OBJECTS_NAME).read_bytes()
    except OSError as error:
        raise ValueError("BACKUP_SET_MISSING") from error
    payloads = {BACKUP_SET_NAME: raw_document, OBJECTS_NAME: raw_objects}
    for name, expected in fields(json.loads(raw_checksums)).items():
        data = payloads.get(name)
        if data is None or hashlib.sha256(data).hexdigest() != str(expected):
            raise ValueError("BACKUP_SET_INVALID")
    objects = json.loads(raw_objects)
    if not isinstance(objects, list):
        raise ValueError("BACKUP_SET_INVALID")
    entries = tuple(ObjectEntry.read(value) for value in cast("list[object]", objects))
    return fields(json.loads(raw_document)), entries


def verify(entries: tuple[ObjectEntry, ...], store: LocalVersionStore) -> Verification:
    """逐一讀回被 DB 引用的物件並核對大小與 SHA-256；不符者列為不可用。"""
    unreadable: list[str] = []
    for entry in entries:
        try:
            store.read_verified(entry.reference())
        except (StorageRejected, OSError, ValueError):
            unreadable.append(entry.version)
    return Verification(checked=len(entries), unreadable=tuple(unreadable))


def detach(entry: ObjectEntry, store: LocalVersionStore) -> Path:
    """把單一物件暫移出保管位置以驗證缺件偵測；不做刪除，呼叫端必須復原。"""
    path = store.path(entry.reference())
    hidden = path.with_name(path.name + ".drill-missing")
    os.replace(path, hidden)
    ensure_durable(store.root)
    return hidden


def reattach(hidden: Path, entry: ObjectEntry, store: LocalVersionStore) -> None:
    """演練結束後把物件放回原位；缺此步代表演練未清理，命令以失敗收場。"""
    os.replace(hidden, store.path(entry.reference()))
    ensure_durable(store.root)
