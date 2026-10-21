"""Filesystem identity and bounded stream tests independent of HTTP."""
import hashlib
import io
import os
from pathlib import Path
import stat
from tempfile import TemporaryDirectory
from unittest import TestCase
from uuid import uuid4
from django.core.management import call_command
from django.test import override_settings
from catalog.storage import LocalVersionStore, ObjectRef, StorageRejected


class StorageTests(TestCase):
    def setUp(self) -> None:
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.store = LocalVersionStore(self.root)
        self.content = b"public synthetic data"
        self.reference = ObjectRef(uuid4(), uuid4(), uuid4(), hashlib.sha256(self.content).hexdigest(), len(self.content))

    def test_atomic_create_verify_and_replay(self) -> None:
        self.store.create(self.reference, io.BytesIO(self.content))
        self.store.create(self.reference, io.BytesIO(self.content))
        self.assertEqual(self.store.read_verified(self.reference), self.content)
        self.assertEqual(len(list(self.root.iterdir())), 1)

    def test_bad_checksum_and_oversize_remove_partial(self) -> None:
        changed = io.BytesIO(b"x" * len(self.content))
        with self.assertRaisesRegex(StorageRejected, "CHECKSUM_MISMATCH"):
            self.store.create(self.reference, changed)
        oversized = io.BytesIO(self.content + b"x")
        with self.assertRaisesRegex(StorageRejected, "UPLOAD_TOO_LARGE"):
            self.store.create(self.reference, oversized)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_symlink_never_reads_outside_content(self) -> None:
        outside = self.root / "outside"
        outside.write_bytes(self.content)
        self.store.path(self.reference).symlink_to(outside)
        with self.assertRaisesRegex(StorageRejected, "UPLOAD_OBJECT_CHANGED"):
            self.store.read_verified(self.reference)

    def test_missing_and_truncated_version_rejected(self) -> None:
        with self.assertRaisesRegex(StorageRejected, "UPLOAD_OBJECT_CHANGED"):
            self.store.read_verified(self.reference)
        self.store.create(self.reference, io.BytesIO(self.content))
        path = self.store.path(self.reference)
        path.chmod(0o600)
        path.write_bytes(b"short")
        with self.assertRaisesRegex(StorageRejected, "UPLOAD_OBJECT_CHANGED"):
            self.store.read_verified(self.reference)

    def test_changed_version_cannot_be_overwritten(self) -> None:
        self.store.create(self.reference, io.BytesIO(self.content))
        path = self.store.path(self.reference)
        path.chmod(0o600)
        path.write_bytes(b"z" * len(self.content))
        source = io.BytesIO(self.content)
        with self.assertRaisesRegex(StorageRejected, "UPLOAD_OBJECT_CHANGED"):
            self.store.create(self.reference, source)
        self.assertEqual(path.read_bytes(), b"z" * len(self.content))

    def test_prepare_raw_access_upgrades_legacy_objects_for_the_evaluator_group(self) -> None:
        self.store.create(self.reference, io.BytesIO(self.content))
        path = self.store.path(self.reference)
        path.chmod(0o400)
        self.root.chmod(0o700)
        with override_settings(OBJECT_ROOT=self.root, RAW_GID=os.getgid()):
            call_command("prepare_raw_access", stdout=io.StringIO())
        self.assertEqual(stat.S_IMODE(self.root.stat().st_mode), 0o2750)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o440)
        self.assertEqual(path.stat().st_gid, os.getgid())
        self.assertEqual(self.store.read_verified(self.reference), self.content)
