"""AX-27 備份集核心回歸：一致集落盤、checksum 拒絕、引用物件驗證與缺件演練。

純檔案層的行為以 `SimpleTestCase` 驗證，完全不碰 DB；需要權威列與真實 PostgreSQL 快照的
一致集建立則用 `TransactionTestCase`，因為 `capture` 必須在自身交易內先設定隔離級別。
"""
import hashlib
import io
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4
from django.contrib.auth.models import User
from django.test import SimpleTestCase, TransactionTestCase
from catalog import backup
from catalog.models import Account, Dataset, Provenance, StoredObject, Tenant, Upload
from catalog.storage import LocalVersionStore, ObjectRef
from runtime.contracts import JsonObject
from runtime.records import db_now

CONTENT = b"axiom backup drill synthetic payload"


def materialize(store: LocalVersionStore, content: bytes = CONTENT) -> ObjectRef:
    """把合成位元組落成不可變物件並回傳引用；測試不經 HTTP。"""
    reference = ObjectRef(uuid4(), uuid4(), uuid4(), hashlib.sha256(content).hexdigest(), len(content))
    store.create(reference, io.BytesIO(content))
    return reference


def as_entry(reference: ObjectRef) -> backup.ObjectEntry:
    return backup.ObjectEntry(reference.tenant.hex, reference.upload.hex, reference.version.hex, reference.sha256, reference.size)


def sample_document(identity: str) -> JsonObject:
    return {"kind": "BackupSet", "backup_set_id": identity, "backup_set_version": backup.BACKUP_SET_VERSION, "storage_location": "test"}


class BackupSetContractTests(SimpleTestCase):
    """物件項目與檔案 checksum 的契約；不涉及資料庫。"""

    def setUp(self) -> None:
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        override = self.settings(BACKUP_ROOT=self.root)
        override.enable()
        self.addCleanup(override.disable)
        self.store = LocalVersionStore(self.root / "objects")
        self.reference = materialize(self.store)
        self.entry = as_entry(self.reference)

    def test_object_entry_reads_only_well_formed_rows(self) -> None:
        self.assertEqual(backup.ObjectEntry.read(self.entry.document()), self.entry)
        self.assertEqual(self.entry.reference(), self.reference)
        for broken in (
            {"tenant": self.entry.tenant, "upload": self.entry.upload, "version": self.entry.version, "sha256": "short", "size": self.entry.size},
            {"tenant": self.entry.tenant, "upload": self.entry.upload, "version": self.entry.version, "sha256": self.entry.sha256, "size": 0},
            {"tenant": "not-a-uuid", "upload": self.entry.upload, "version": self.entry.version, "sha256": self.entry.sha256, "size": self.entry.size},
        ):
            with self.assertRaisesRegex(ValueError, "BACKUP_SET_INVALID"):
                backup.ObjectEntry.read(broken)
        with self.assertRaisesRegex(ValueError, "BACKUP_SET_INVALID"):
            backup.fields([1, 2, 3])

    def test_manifest_digest_is_stable_and_order_sensitive(self) -> None:
        second = as_entry(materialize(self.store))
        self.assertEqual(backup.manifest_digest((self.entry, second)), backup.manifest_digest((self.entry, second)))
        self.assertNotEqual(backup.manifest_digest((self.entry, second)), backup.manifest_digest((second, self.entry)))

    def test_write_and_read_round_trip_rejects_tampering_and_missing_files(self) -> None:
        document = sample_document(str(uuid4()))
        directory = backup.write(document, (self.entry,))
        self.assertEqual(directory, self.root / str(document["backup_set_id"]))
        restored, entries = backup.read(directory)
        self.assertEqual(restored, document)
        self.assertEqual(entries, (self.entry,))
        (directory / backup.BACKUP_SET_NAME).write_bytes(b'{"kind":"BackupSet"}')
        with self.assertRaisesRegex(ValueError, "BACKUP_SET_INVALID"):
            backup.read(directory)
        (directory / backup.OBJECTS_NAME).unlink()
        with self.assertRaisesRegex(ValueError, "BACKUP_SET_MISSING"):
            backup.read(directory)

    def test_verify_flags_missing_object_and_empty_manifest_is_not_ok(self) -> None:
        self.assertTrue(backup.verify((self.entry,), self.store).ok())
        absent = as_entry(ObjectRef(uuid4(), uuid4(), uuid4(), hashlib.sha256(CONTENT).hexdigest(), len(CONTENT)))
        degraded = backup.verify((self.entry, absent), self.store)
        self.assertFalse(degraded.ok())
        self.assertEqual(degraded.unreadable, (absent.version,))
        self.assertFalse(backup.verify((), self.store).ok())

    def test_detach_hides_the_object_and_reattach_restores_it(self) -> None:
        hidden = backup.detach(self.entry, self.store)
        self.assertFalse(self.store.path(self.reference).exists())
        self.assertEqual(backup.verify((self.entry,), self.store).unreadable, (self.entry.version,))
        backup.reattach(hidden, self.entry, self.store)
        self.assertTrue(backup.verify((self.entry,), self.store).ok())
        self.assertEqual(self.store.read_verified(self.reference), CONTENT)


class BackupCaptureTests(TransactionTestCase):
    """一致集建立與帳本高水位；需要真實 PostgreSQL 的唯讀快照交易。"""

    def setUp(self) -> None:
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        override = self.settings(BACKUP_ROOT=self.root, OBJECT_ROOT=self.root / "objects")
        override.enable()
        self.addCleanup(override.disable)
        self.store = LocalVersionStore(self.root / "objects")

    def seed_object(self) -> backup.ObjectEntry:
        """建立最小權威鏈（租戶→來源→資料集→上傳→物件）並把位元組落成不可變物件。"""
        tenant = Tenant.objects.create(name="backup-synthetic-" + uuid4().hex)
        account = Account.objects.create(user=User.objects.create(username=uuid4().hex), tenant=tenant)
        provenance_id, resource_id = uuid4(), uuid4()
        provenance = Provenance.objects.create(id=provenance_id, tenant=tenant, resource_type="Upload", resource_id=resource_id,
            document={"kind": "Provenance", "id": str(provenance_id), "tenant_id": str(tenant.id), "resource_id": str(resource_id),
                      "resource_type": "Upload", "creator_actor_id": str(account.id), "responsible_human_ids": [], "source_provenance_ids": []})
        dataset = Dataset.objects.create(tenant=tenant, owner=account, name="backup", provenance_id=provenance.id)
        digest = hashlib.sha256(CONTENT).hexdigest()
        upload = Upload.objects.create(tenant=tenant, dataset=dataset, actor=account, filename="synthetic.csv", format="CSV",
                                       size_bytes=len(CONTENT), sha256=digest, expires_at=db_now() + timedelta(hours=1))
        stored = StoredObject.objects.create(tenant=tenant, dataset=dataset, upload=upload, sha256=digest,
                                             size_bytes=len(CONTENT), provenance_id=provenance.id)
        reference = ObjectRef(tenant.id, upload.id, stored.id, digest, len(CONTENT))
        self.store.create(reference, io.BytesIO(CONTENT))
        return as_entry(reference)

    def test_capture_writes_a_consistent_set_and_verifies_its_objects(self) -> None:
        entry = self.seed_object()
        document, entries = backup.capture(datetime.now(timezone.utc), str(uuid4()))
        self.assertEqual((document["kind"], document["backup_set_version"]), ("BackupSet", backup.BACKUP_SET_VERSION))
        self.assertEqual(document["secret_key_version"], backup.secret_key_fingerprint())
        self.assertEqual(document["object_manifest"], {"count": len(entries), "digest": backup.manifest_digest(entries)})
        self.assertIn(entry, entries)
        self.assertTrue(backup.verify(entries, self.store).ok())
        self.assertEqual(document["exposure_ledger_high_water"]["status"], "未取得")
        restored, restored_entries = backup.read(backup.write(document, entries))
        self.assertEqual(restored, document)
        self.assertEqual(restored_entries, entries)

    def test_empty_authority_reports_zero_ledgers_and_consistent_dispatch(self) -> None:
        self.assertEqual(backup.authoritative_counts()["tombstones"], 0)
        ledger = backup.deletion_ledger()
        self.assertEqual((ledger["tombstones"], ledger["requests"], ledger["targets"]), (0, 0, 0))
        self.assertEqual(backup.outbox_high_water(), {"runs": 0, "events": 0, "digest": backup.outbox_high_water()["digest"]})
        reconstruction = backup.dispatch_reconstruction()
        self.assertEqual((reconstruction.runs, reconstruction.inconsistent), (0, ()))
        document, entries = backup.capture(datetime.now(timezone.utc), str(uuid4()))
        self.assertEqual(entries, ())
        self.assertEqual(document["object_manifest"]["count"], 0)
        self.assertFalse(backup.verify(entries, self.store).ok())
        self.assertNotEqual(document["db_restore_point"]["wal_lsn"], "")
        self.assertTrue(document["schema_versions"]["migration_count"] > 0)
