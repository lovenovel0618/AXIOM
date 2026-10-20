"""Current ACL and immutable-version integration with the real parse process."""
from datetime import timedelta
import hashlib
from io import BytesIO, StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import UUID, uuid4
from django.core.management import call_command
from django.core.management.base import CommandError
from django.contrib.auth.models import User
from django.test import TestCase
from catalog.management.commands.ingest_preview import preview
from catalog.models import Account, Audit, Dataset, Grant, Tenant, Upload
from catalog.services import actor_for, create_dataset, create_upload, put_upload
from catalog.storage import LocalVersionStore, ObjectRef
from catalog.validation import ApiError
from ingestion.limits import ImportLimits, ImportRejected
from runtime.models import RuntimeRun
from runtime.records import db_now

CONTENT = b'x,y\n1,3\n2,5\n'
LIMITS = ImportLimits(100, 8, 4096, 65536, 10)


class PreviewTests(TestCase):
    def setUp(self) -> None:
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        override = self.settings(OBJECT_ROOT=self.root)
        override.enable()
        self.addCleanup(override.disable)
        self.owner = self.account(Tenant.objects.create(name="first"))
        self.other = self.account(Tenant.objects.create(name="other"))
        actor = actor_for(self.owner.user_id)
        self.dataset = UUID(create_dataset(actor, {"name": "synthetic"})["id"])
        result = create_upload(actor, Dataset.objects.get(pk=self.dataset), {"filename": "input.csv", "format": "CSV", "size_bytes": len(CONTENT), "sha256": hashlib.sha256(CONTENT).hexdigest()}, "http://localhost")
        self.upload = Upload.objects.get(pk=UUID(result["id"]))
        put_upload(actor, self.upload, result["required_headers"]["X-Upload-Token"], BytesIO(CONTENT))
        self.upload.refresh_from_db()

    def account(self, tenant: Tenant) -> Account:
        user = User.objects.create(username=uuid4().hex, password="!")
        return Account.objects.create(user=user, tenant=tenant, role="RESEARCHER")

    def test_real_preview_has_no_cells_or_business_success(self) -> None:
        result = preview(self.owner.id, self.upload.id, LIMITS)
        self.assertEqual(result["metadata"]["row_count"], 2)
        self.assertEqual(set(result["metadata"]), {"row_count", "columns"})
        self.assertEqual(result["object_version"], str(self.upload.object_version))
        self.upload.refresh_from_db()
        self.assertEqual(self.upload.status, "OPEN")
        self.assertIsNone(self.upload.ingest_run_id)
        self.assertFalse(RuntimeRun.objects.exists())
        self.assertEqual(Audit.objects.filter(action="INSPECT_UPLOAD").count(), 1)

    def test_cross_tenant_and_revoked_acl_reject_before_spawn(self) -> None:
        with patch("catalog.management.commands.ingest_preview.inspect_bytes") as process:
            with self.assertRaises(ApiError) as raised:
                preview(self.other.id, self.upload.id, LIMITS)
            self.assertEqual(raised.exception.code, "NOT_FOUND")
            Grant.objects.filter(dataset_id=self.dataset, actor=self.owner).delete()
            with self.assertRaises(ApiError):
                preview(self.owner.id, self.upload.id, LIMITS)
            process.assert_not_called()

    def test_disabled_and_downgraded_actor(self) -> None:
        with patch("catalog.management.commands.ingest_preview.inspect_bytes") as process:
            Account.objects.filter(pk=self.owner.id).update(enabled=False)
            with self.assertRaises(ApiError):
                preview(self.owner.id, self.upload.id, LIMITS)
            Account.objects.filter(pk=self.owner.id).update(enabled=True, role="VIEWER")
            with self.assertRaises(ApiError):
                preview(self.owner.id, self.upload.id, LIMITS)
            Account.objects.filter(pk=self.owner.id).update(role="RESEARCHER")
            User.objects.filter(pk=self.owner.user_id).update(is_active=False)
            with self.assertRaises(ApiError):
                preview(self.owner.id, self.upload.id, LIMITS)
            process.assert_not_called()

    def test_missing_actor_and_upload(self) -> None:
        for actor, upload in ((uuid4(), self.upload.id), (self.owner.id, uuid4())):
            with self.assertRaises(ApiError):
                preview(actor, upload, LIMITS)

    def test_expired_upload_rejects(self) -> None:
        future = db_now() + timedelta(hours=1)
        with patch("catalog.management.commands.ingest_preview.db_now", return_value=future):
            with self.assertRaises(ApiError) as raised:
                preview(self.owner.id, self.upload.id, LIMITS)
        self.assertEqual(raised.exception.code, "INVALID_TRANSITION")

    def test_replaced_source_never_reaches_parser(self) -> None:
        assert self.upload.object_version is not None
        ref = ObjectRef(self.owner.tenant_id, self.upload.id, self.upload.object_version, self.upload.sha256, self.upload.size_bytes)
        path = LocalVersionStore(self.root).path(ref)
        path.chmod(0o600)
        path.write_bytes(b'z' * len(CONTENT))
        with patch("catalog.management.commands.ingest_preview.inspect_bytes") as process:
            with self.assertRaises(ApiError) as raised:
                preview(self.owner.id, self.upload.id, LIMITS)
            self.assertEqual(raised.exception.code, "UPLOAD_OBJECT_CHANGED")
            process.assert_not_called()

    def test_limit_failure_keeps_upload_and_no_success_audit(self) -> None:
        limits = ImportLimits(1, 8, 4096, 65536, 10)
        with self.assertRaises(ImportRejected):
            preview(self.owner.id, self.upload.id, limits)
        self.upload.refresh_from_db()
        self.assertIsNone(self.upload.ingest_run_id)
        self.assertFalse(Audit.objects.filter(action="INSPECT_UPLOAD").exists())

    def test_cli_reports_metadata_and_sanitizes_failure(self) -> None:
        flags = ["--max-rows", "100", "--max-columns", "8", "--max-cell-utf8-bytes", "4096", "--max-decoded-bytes", "65536", "--max-parse-seconds", "10"]
        output = StringIO()
        call_command("ingest_preview", str(self.owner.id), str(self.upload.id), *flags, stdout=output)
        self.assertEqual(json.loads(output.getvalue())["metadata"]["row_count"], 2)
        with self.assertRaises(CommandError) as raised:
            call_command("ingest_preview", str(self.other.id), str(self.upload.id), *flags)
        self.assertEqual(str(raised.exception), "NOT_FOUND")
