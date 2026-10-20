"""Actual PostgreSQL submit, dedup, current ACL and immutable result tests."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from io import BytesIO
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import UUID, uuid4
from django.contrib.auth.models import User
from django.db import IntegrityError, connection, connections, transaction
from django.test import TransactionTestCase, override_settings
from catalog.ingest import complete_upload, ingest_tick
from catalog.models import Account, Artifact, Audit, Dataset, DatasetVersion, Grant, IngestBinding, Provenance, Tenant, Upload
from catalog.services import actor_for, create_dataset, create_upload, put_upload, upload_for, provenance
from catalog.storage import LocalVersionStore, ObjectRef
from catalog.validation import ApiError, validate_api
from runtime.contracts import validate, identity_hash
from runtime.control import cancel, claim, recover
from runtime.models import InputSnapshot, RunEvent, RuntimeAttempt, RuntimeRun
from runtime.records import db_now

CONTENT = b'x,y\n1,3\n2,5\n'
LIMITS = {"max_rows": 100, "max_columns": 8, "max_cell_utf8_bytes": 4096, "max_decoded_bytes": 65536, "max_parse_seconds": 10}


@override_settings(INGEST_ENABLED=True, INGEST_LIMITS_JSON=json.dumps(LIMITS))
class BusinessTests(TransactionTestCase):
    def setUp(self) -> None:
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        override = self.settings(OBJECT_ROOT=self.root)
        override.enable()
        self.addCleanup(override.disable)
        user = User.objects.create(username=uuid4().hex, password="!")
        self.actor = Account.objects.create(user=user, tenant=Tenant.objects.create(name="synthetic"), role="RESEARCHER")
        with transaction.atomic():
            self.dataset = UUID(create_dataset(actor_for(user.pk), {"name": "synthetic"})["id"])
        self.upload = self.staged()
        self.client.force_login(user)

    def staged(self, content: bytes = CONTENT, format_name: str = "CSV") -> Upload:
        with transaction.atomic():
            actor = actor_for(self.actor.user_id)
            result = create_upload(actor, Dataset.objects.get(pk=self.dataset), {"filename": "synthetic", "format": format_name, "sha256": hashlib.sha256(content).hexdigest(), "size_bytes": len(content)}, "http://localhost")
            row = Upload.objects.get(pk=UUID(result["id"]))
            put_upload(actor, row, result["required_headers"]["X-Upload-Token"], BytesIO(content))
            return row

    def enqueue(self, upload: Upload | None = None) -> UUID:
        row = upload or self.upload
        with transaction.atomic():
            actor = actor_for(self.actor.user_id)
            result = complete_upload(actor, upload_for(actor, row.id), row.sha256, "complete")
        return UUID(result["id"])

    def execute(self, identity: UUID) -> bool:
        return ingest_tick(str(self.actor.tenant_id), str(identity), 0)

    def test_http_complete_and_successful_registry(self) -> None:
        response = self.client.post(f"/api/v2/uploads/{self.upload.id}/complete", data=json.dumps({"checksum": self.upload.sha256}), content_type="application/json", headers={"Idempotency-Key": "key"})
        self.assertEqual(response.status_code, 202)
        record = json.loads(response.content)
        validate_api(record, "Run")
        identity = UUID(record["id"])
        self.assertTrue(self.execute(identity))
        run = RuntimeRun.objects.get(pk=identity)
        snapshot = InputSnapshot.objects.get(run=run)
        self.assertEqual(snapshot.execution["input_hash"], identity_hash({key: value for key, value in snapshot.task_input.items() if key != "execution_manifest_id"}))
        self.assertFalse(run.control_only)
        self.assertEqual(run.document["status"], "SUCCEEDED")
        self.assertGreater(run.document["budget_usage"]["peak_memory_bytes"], 0)
        version = DatasetVersion.objects.get()
        validate(version.document, "research-v2.schema.json", "DatasetVersion")
        preview = version.preview.content
        assert preview is not None
        validate(preview, "research-learning-v1.schema.json", "StructureAssessment")
        self.assertEqual(preview["source_metadata"]["row_count"], 2)
        self.assertIsNone(preview["fit_rows_hash"])
        self.assertNotIn("labels", preview)
        self.assertEqual(IngestBinding.objects.get().result_id, version.id)
        self.assertEqual(RuntimeAttempt.objects.get().document["status"], "SUCCEEDED")
        self.assertEqual(RunEvent.objects.count(), 3)

    def test_complete_replays_even_after_expiry_and_gate_off(self) -> None:
        identity = self.enqueue()
        with self.settings(INGEST_ENABLED=False), patch("catalog.ingest.db_now", return_value=db_now() + timedelta(days=2)):
            self.assertEqual(self.enqueue(), identity)
        self.assertEqual(RuntimeRun.objects.count(), 1)
        self.assertEqual(IngestBinding.objects.count(), 1)

    def test_bad_checksum_and_missing_configuration_reject(self) -> None:
        with transaction.atomic():
            actor = actor_for(self.actor.user_id)
            row = upload_for(actor, self.upload.id)
            with self.assertRaises(ApiError):
                complete_upload(actor, row, "0" * 64, "key")
        with self.settings(INGEST_LIMITS_JSON="{}"):
            with self.assertRaises(ApiError):
                self.enqueue()
        self.assertFalse(RuntimeRun.objects.exists())

    def test_duplicate_delivery_does_not_add_attempt_or_version(self) -> None:
        identity = self.enqueue()
        self.assertTrue(self.execute(identity))
        self.assertFalse(self.execute(identity))
        self.assertEqual(RuntimeAttempt.objects.count(), 1)
        self.assertEqual(DatasetVersion.objects.count(), 1)

    def test_two_uploads_same_hash_reuse_version(self) -> None:
        other = self.staged()
        first, second = self.enqueue(), self.enqueue(other)
        self.execute(first)
        self.execute(second)
        self.assertEqual(DatasetVersion.objects.count(), 1)
        self.assertEqual({r.result_id for r in IngestBinding.objects.all()}, {DatasetVersion.objects.get().id})
        self.assertEqual(RuntimeRun.objects.filter(document__status="SUCCEEDED").count(), 2)

    def test_parser_failure_has_safe_diagnostic_and_no_version(self) -> None:
        invalid = self.staged(b'x,x\nprivate-marker,2\n')
        identity = self.enqueue(invalid)
        self.execute(identity)
        row = RuntimeRun.objects.get(pk=identity)
        self.assertEqual(row.document["status"], "FAILED")
        self.assertEqual(IngestBinding.objects.get().error_code, "INVALID_SCHEMA")
        self.assertFalse(DatasetVersion.objects.exists())
        diagnostic = Artifact.objects.get(pk=UUID(row.document["diagnostic_artifact_ids"][0]))
        self.assertNotIn("private-marker", json.dumps(diagnostic.content))

    def test_revoked_before_execution_never_parses(self) -> None:
        identity = self.enqueue()
        Grant.objects.filter(actor=self.actor).delete()
        with patch("catalog.ingest.inspect_bytes") as parser:
            self.execute(identity)
            parser.assert_not_called()
        self.assertFalse(DatasetVersion.objects.exists())
        self.assertEqual(RuntimeRun.objects.get(pk=identity).document["status"], "FAILED")

    def test_revoke_during_parser_prevents_commit(self) -> None:
        identity = self.enqueue()
        def parse_and_revoke(*_args: object) -> dict[str, object]:
            Grant.objects.filter(actor=self.actor).delete()
            return {"source_sha256": self.upload.sha256, "metadata": {"row_count": 2, "columns": [{"name": "x", "physical_type": "CSV_TEXT"}, {"name": "y", "physical_type": "CSV_TEXT"}]}}
        with patch("catalog.ingest.inspect_bytes", side_effect=parse_and_revoke):
            self.execute(identity)
        self.assertFalse(DatasetVersion.objects.exists())
        self.assertEqual(IngestBinding.objects.get().error_code, "NOT_FOUND")

    def test_cancel_during_parser_prevents_commit_and_confirms_exit(self) -> None:
        identity = self.enqueue()
        def parse_and_cancel(*_args: object) -> dict[str, object]:
            row = RuntimeRun.objects.get(pk=identity)
            cancel(self.actor.tenant_id, identity, row.document["revision"])
            return {"source_sha256": self.upload.sha256, "metadata": {"row_count": 2, "columns": [{"name": "x", "physical_type": "CSV_TEXT"}]}}
        with patch("catalog.ingest.inspect_bytes", side_effect=parse_and_cancel):
            self.execute(identity)
        self.assertFalse(DatasetVersion.objects.exists())
        self.assertEqual(RuntimeRun.objects.get(pk=identity).document["status"], "CANCELLED")

    def test_source_replacement_before_execution(self) -> None:
        identity = self.enqueue()
        assert self.upload.object_version is not None
        path = LocalVersionStore(self.root).path(ObjectRef(self.actor.tenant_id, self.upload.id, self.upload.object_version, self.upload.sha256, self.upload.size_bytes))
        path.chmod(0o600)
        path.write_bytes(b'z' * len(CONTENT))
        self.execute(identity)
        self.assertFalse(DatasetVersion.objects.exists())
        self.assertEqual(IngestBinding.objects.get().error_code, "UPLOAD_OBJECT_CHANGED")

    def test_current_acl_on_all_reads_and_sealed_raw_denied(self) -> None:
        identity = self.enqueue()
        self.execute(identity)
        version = DatasetVersion.objects.get()
        self.assertEqual(self.client.get(f"/api/v2/runs/{identity}").status_code, 200)
        self.assertEqual(self.client.get(f"/api/v2/datasets/{self.dataset}/versions").status_code, 200)
        self.assertEqual(self.client.get(f"/api/v2/artifacts/{version.raw_id}").status_code, 404)
        self.assertEqual(self.client.get(f"/api/v2/artifacts/{version.raw_id}/content").status_code, 404)
        response = self.client.get(f"/api/v2/artifacts/{version.preview_id}/content")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertEqual(hashlib.sha256(response.content).hexdigest(), version.preview.document["sha256"])
        Grant.objects.filter(actor=self.actor).delete()
        for path in [f"/api/v2/runs/{identity}", f"/api/v2/datasets/{self.dataset}/versions", f"/api/v2/artifacts/{version.preview_id}", f"/api/v2/artifacts/{version.preview_id}/content"]:
            self.assertEqual(self.client.get(path).status_code, 404)

    def test_atomic_callback_failure_rolls_back_version_and_success(self) -> None:
        identity = self.enqueue()
        with patch("catalog.ingest.publish", side_effect=ApiError("DEPENDENCY_UNAVAILABLE", 503)):
            self.execute(identity)
        self.assertEqual(RuntimeRun.objects.get(pk=identity).document["status"], "FAILED")
        self.assertFalse(DatasetVersion.objects.exists())
        self.assertFalse(Audit.objects.filter(action="INGEST_SUCCESS").exists())

    def test_stale_attempt_cannot_submit(self) -> None:
        identity = self.enqueue()
        lease = claim(self.actor.tenant_id, identity, 0, "first")
        assert lease is not None
        from catalog.ingest import submit
        current = self.client.get(f"/api/v2/runs/{identity}")
        self.assertEqual(current["X-Control-Revision"], str(json.loads(current.content)["revision"]))
        self.assertEqual(current["X-Usage-Status"], "UNKNOWN")
        forged = replace(lease, generation=lease.generation + 1)
        metadata = {"row_count": 1, "columns": [{"name": "x", "physical_type": "CSV_TEXT"}]}
        from runtime.records import ControlError
        usage = RuntimeRun.objects.get(pk=identity).document["budget_usage"]
        with self.assertRaises(ControlError):
            submit(IngestBinding.objects.get(), forged, metadata, usage)
        self.assertFalse(DatasetVersion.objects.exists())

    def test_sql_content_and_mode_tampering_rejected(self) -> None:
        identity = self.enqueue()
        self.execute(identity)
        for action in [lambda: Artifact.objects.update(content={"private": 1}), lambda: DatasetVersion.objects.update(sha256="0" * 64), lambda: RuntimeRun.objects.filter(pk=identity).update(control_only=True)]:
            with self.assertRaises(IntegrityError), transaction.atomic():
                action()

    def test_deadline_during_parser_rejects_result(self) -> None:
        identity = self.enqueue()
        def parse_and_expire(*_args: object) -> dict[str, object]:
            RuntimeRun.objects.filter(pk=identity).update(first_started_at=db_now() - timedelta(hours=1))
            return {"source_sha256": self.upload.sha256, "metadata": {"row_count": 2, "columns": [{"name": "x", "physical_type": "CSV_TEXT"}]}}
        with patch("catalog.ingest.inspect_bytes", side_effect=parse_and_expire):
            self.execute(identity)
        self.assertFalse(DatasetVersion.objects.exists())
        self.assertEqual(RuntimeRun.objects.get(pk=identity).document["stop_reason"], "BUDGET_EXHAUSTED")

    def test_disabled_actor_never_executes(self) -> None:
        identity = self.enqueue()
        User.objects.filter(pk=self.actor.user_id).update(is_active=False)
        with patch("catalog.ingest.inspect_bytes") as parser:
            self.execute(identity)
            parser.assert_not_called()
        self.assertFalse(DatasetVersion.objects.exists())
        self.assertEqual(IngestBinding.objects.get().error_code, "FORBIDDEN")

    def test_queue_timeout_reports_not_started(self) -> None:
        identity = self.enqueue()
        RuntimeRun.objects.filter(pk=identity).update(queue_deadline=db_now() - timedelta(seconds=1))
        recover(self.actor.tenant_id, identity)
        response = self.client.get(f"/api/v2/runs/{identity}")
        self.assertEqual(response["X-Usage-Status"], "NOT_STARTED")
        self.assertFalse(self.execute(identity))
        self.assertFalse(DatasetVersion.objects.exists())

    def test_lost_attempt_reports_unknown_usage(self) -> None:
        identity = self.enqueue()
        lease = claim(self.actor.tenant_id, identity, 0, "lost")
        assert lease is not None
        attempt = RuntimeAttempt.objects.get(pk=lease.attempt_id)
        attempt.document["lease_expires_at"] = (db_now() - timedelta(seconds=1)).isoformat()
        attempt.save()
        recover(self.actor.tenant_id, identity)
        response = self.client.get(f"/api/v2/runs/{identity}")
        self.assertEqual(response["X-Usage-Status"], "UNKNOWN")
        self.assertFalse(DatasetVersion.objects.exists())

    def test_cross_tenant_read_and_foreign_key(self) -> None:
        identity = self.enqueue()
        self.execute(identity)
        version = DatasetVersion.objects.get()
        user = User.objects.create(username=uuid4().hex, password="!")
        other = Account.objects.create(user=user, tenant=Tenant.objects.create(name="other"), role="ADMIN")
        self.client.force_login(user)
        for path in [f"/api/v2/runs/{identity}", f"/api/v2/datasets/{self.dataset}/versions", f"/api/v2/artifacts/{version.preview_id}"]:
            self.assertEqual(self.client.get(path).status_code, 404)
        source = Provenance.objects.get(pk=version.preview.provenance_id)
        artifact_id, source_id = uuid4(), uuid4()
        document = dict(version.preview.document)
        document.update(id=str(artifact_id), owner_id=str(other.id), artifact_uri=f"/api/v2/artifacts/{artifact_id}/content")
        with self.assertRaises(IntegrityError) as raised, transaction.atomic():
            provenance(self.actor, "Artifact", artifact_id, source_id, source)
            Artifact.objects.create(id=artifact_id, tenant_id=self.actor.tenant_id, dataset_id=self.dataset, owner=other,
                                    content=version.preview.content, document=document, provenance_id=source_id)
            connection.check_constraints()
        self.assertIn("artifact_owner_fk", str(raised.exception))

    def test_versions_cursor_is_scoped(self) -> None:
        first = self.enqueue()
        self.execute(first)
        second = self.enqueue(self.staged(b'x,y\n3,7\n'))
        self.execute(second)
        response = self.client.get(f"/api/v2/datasets/{self.dataset}/versions?limit=1")
        cursor = json.loads(response.content)["next_cursor"]
        self.assertIsNotNone(cursor)
        second_page = self.client.get(f"/api/v2/datasets/{self.dataset}/versions", {"limit": 1, "cursor": cursor})
        self.assertEqual(len(json.loads(second_page.content)["items"]), 1)
        bad = self.client.get(f"/api/v2/datasets/{self.dataset}/versions", {"cursor": "tampered"})
        self.assertEqual(bad.status_code, 400)

    def test_parallel_complete_only_one_run(self) -> None:
        def invoke(_index: int) -> UUID:
            try:
                return self.enqueue()
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(invoke, range(4)))
        self.assertEqual(len(set(results)), 1)
        self.assertEqual(RuntimeRun.objects.count(), 1)
