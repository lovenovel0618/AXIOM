"""真實 PostgreSQL 下的刪除傳播回歸：同交易宣告、Fail-Closed 狀態機與讀取回查。"""
from collections.abc import Callable
from io import BytesIO
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest.mock import patch
from uuid import UUID, uuid4
from django.contrib.auth.models import User
from django.db import IntegrityError, connection, transaction
from django.test import TransactionTestCase, override_settings
from catalog.artifacts import register
from catalog.deletion import affected, declare, due, is_tombstoned, outstanding, propagate
from catalog.ingest import complete_upload, ingest_tick
from catalog.models import Account, Artifact, Dataset, DatasetVersion, DeletionRequest, DeletionTarget, EvidenceBundle, IngestBinding, Provenance, ResearchVersion, Tenant, Tombstone, Upload
from catalog.research import create_research, create_version, research_for
from catalog.services import actor_for, create_dataset, create_upload, put_upload
from catalog.tasks import relay_deletion
from catalog.tests.test_research import draft_data
from catalog.validation import ApiError, validate_api
from runtime.contracts import JsonObject
from runtime.records import db_now

CONTENT = b'x,y\n' + b''.join(f'{i},{2*i+1}\n'.encode() for i in range(10))
LIMITS = {"max_rows": 100, "max_columns": 8, "max_cell_utf8_bytes": 4096, "max_decoded_bytes": 65536, "max_parse_seconds": 10}


def enforce(action: Callable[[], object]) -> None:
    with transaction.atomic():
        action()
        connection.check_constraints()


@override_settings(INGEST_ENABLED=True, INGEST_LIMITS_JSON=json.dumps(LIMITS), PROFILE_ENABLED=False)
class DeletionTests(TransactionTestCase):
    def setUp(self) -> None:
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        override = self.settings(OBJECT_ROOT=Path(directory.name))
        override.enable()
        self.addCleanup(override.disable)
        self.tenant = Tenant.objects.create(name="deletion-synthetic")
        self.other_tenant = Tenant.objects.create(name="deletion-other")
        self.actor = self.account(self.tenant)
        self.other = self.account(self.other_tenant)
        with transaction.atomic():
            actor = actor_for(self.actor.user_id)
            self.dataset = Dataset.objects.get(pk=UUID(create_dataset(actor, {"name": "synthetic"})["id"]))
            upload = create_upload(actor, self.dataset, {"filename": "test.csv", "format": "CSV", "size_bytes": len(CONTENT), "sha256": hashlib.sha256(CONTENT).hexdigest()}, "http://localhost")
            row = Upload.objects.get(pk=UUID(upload["id"]))
            put_upload(actor, row, upload["required_headers"]["X-Upload-Token"], BytesIO(CONTENT))
            run = complete_upload(actor, row, row.sha256, "complete")
            research = UUID(create_research(actor, {"name": "synthetic"})["id"])
        self.run_id = UUID(str(run["id"]))
        self.assertTrue(ingest_tick(str(self.tenant.id), str(self.run_id), 0))
        self.version = DatasetVersion.objects.get()
        with transaction.atomic():
            actor = actor_for(self.actor.user_id)
            document = create_version(actor, research_for(actor, research), draft_data(self.version.id))
        self.research_version = ResearchVersion.objects.get(pk=UUID(document["id"]))
        with transaction.atomic():
            actor = actor_for(self.actor.user_id)
            self.artifact = self.private_artifact(actor)
            self.bundle = self.evidence_bundle(actor)
        self.client.force_login(self.actor.user)

    def account(self, tenant: Tenant) -> Account:
        user = User.objects.create(username=uuid4().hex, password="!")
        return Account.objects.create(user=user, tenant=tenant)

    def private_artifact(self, actor: Account) -> Artifact:
        source = Provenance.objects.get(pk=self.version.provenance_id, tenant_id=actor.tenant_id)
        content: JsonObject = {"kind": "StructureAssessment", "research_version_id": str(self.research_version.id)}
        return register(actor, IngestBinding.objects.get(run_id=self.run_id), uuid4(), content, source, research_version=self.research_version)

    def evidence_bundle(self, actor: Account) -> EvidenceBundle:
        identity, created = uuid4(), db_now()
        document: JsonObject = {"kind": "EvidenceBundle", "id": str(identity), "tenant_id": str(actor.tenant_id), "schema_version": "2.0",
            "created_at": created.isoformat(), "research_version_id": str(self.research_version.id), "validation_ids": [],
            "proof_artifact_ids": [str(self.artifact.id)], "status": "ACTIVE", "revision": 0}
        validate_api(document, "EvidenceBundle")
        return EvidenceBundle.objects.create(id=identity, tenant_id=actor.tenant_id, research_version_id=self.research_version.id,
            run_id=self.run_id, created_at=created, document=document)

    def declare(self) -> DeletionRequest:
        with transaction.atomic():
            return declare(actor_for(self.actor.user_id), self.version.id, db_now())

    def deletion_url(self) -> str:
        return f"/api/v2/dataset-versions/{self.version.id}/deletion-requests"

    def http_declare(self, key: str = "deletion-key") -> Any:
        response = self.client.post(self.deletion_url(), headers={"Idempotency-Key": key})
        self.assertEqual(response.status_code, 201)
        return response.json()

    def test_declaration_records_work_and_stays_blocked_while_policy_is_closed(self) -> None:
        request = self.declare()
        expected = affected(self.actor, self.version)
        self.assertEqual((request.status, request.policy_status, request.blocked_code, request.revision), ("BLOCKED", "BLOCKED", "FEATURE_DISABLED", 0))
        self.assertEqual(Tombstone.objects.filter(deletion_request=request).count(), len(expected))
        self.assertEqual(DeletionTarget.objects.filter(deletion_request=request).count(), len(expected))
        self.assertEqual(outstanding(request), len(expected))
        self.assertEqual(set(DeletionTarget.objects.filter(deletion_request=request).values_list("outcome", flat=True)), {"PENDING"})
        self.assertEqual(set(DeletionTarget.objects.filter(deletion_request=request).values_list("action", flat=True)), {"TOMBSTONE", "PURGE_DERIVED"})
        for object_type, identity in [("DatasetVersion", self.version.id), ("Artifact", self.artifact.id), ("EvidenceBundle", self.bundle.id), ("ResearchVersion", self.research_version.id)]:
            self.assertTrue(is_tombstoned(self.actor, object_type, identity))

    def test_reads_and_downloads_stop_after_declaration(self) -> None:
        preview = self.version.preview_id
        self.assertEqual(self.client.get(f"/api/v2/artifacts/{preview}").status_code, 200)
        self.assertEqual(self.client.get(f"/api/v2/artifacts/{self.artifact.id}/content").status_code, 200)
        self.assertEqual(self.client.get(f"/api/v2/evidence-bundles/{self.bundle.id}").status_code, 200)
        self.declare()
        self.assertEqual(self.client.get(f"/api/v2/artifacts/{preview}").status_code, 409)
        self.assertEqual(self.client.get(f"/api/v2/artifacts/{self.artifact.id}/content").status_code, 409)
        self.assertEqual(self.client.get(f"/api/v2/evidence-bundles/{self.bundle.id}").status_code, 404)

    def test_second_declaration_of_the_same_source_is_rejected(self) -> None:
        self.declare()
        with self.assertRaises(ApiError) as raised:
            self.declare()
        self.assertEqual((raised.exception.code, raised.exception.status), ("INVALID_TRANSITION", 409))
        self.assertEqual(DeletionRequest.objects.count(), 1)

    def test_enabled_policy_propagates_without_claiming_cleanup(self) -> None:
        with self.settings(DELETION_PROPAGATION_ENABLED=True):
            request = self.declare()
        self.assertEqual((request.status, request.policy_status, request.blocked_code), ("PROPAGATING", "ACTIVE", None))
        self.assertEqual(outstanding(request), len(affected(self.actor, self.version)))
        self.assertEqual(self.client.get(f"/api/v2/artifacts/{self.artifact.id}/content").status_code, 409)

    def test_cross_tenant_source_root_is_rejected(self) -> None:
        with self.assertRaises(IntegrityError):
            enforce(lambda: DeletionRequest.objects.create(id=uuid4(), tenant_id=self.other_tenant.id, dataset_version=self.version,
                requested_by=self.other, created_at=db_now()))

    def test_database_rejects_tombstone_mutation_and_removal(self) -> None:
        self.declare()
        rows = Tombstone.objects.all()
        with self.assertRaises(IntegrityError):
            enforce(lambda: rows.update(object_type="Artifact"))
        with self.assertRaises(IntegrityError):
            enforce(lambda: rows.delete())
        self.assertTrue(Tombstone.objects.exists())

    def test_database_rejects_revision_skips_and_unknown_status(self) -> None:
        request = self.declare()
        rows = DeletionRequest.objects.filter(pk=request.id)
        with self.assertRaises(IntegrityError):
            enforce(lambda: rows.update(revision=5))
        with self.assertRaises(IntegrityError):
            enforce(lambda: rows.update(status="UNKNOWN", revision=1))
        self.assertEqual(DeletionRequest.objects.get(pk=request.id).revision, 0)

    def test_database_blocks_propagation_while_policy_is_not_active(self) -> None:
        request = self.declare()
        rows = DeletionRequest.objects.filter(pk=request.id)
        for status in ("PROPAGATING", "COMPLETED"):
            with self.assertRaises(IntegrityError):
                enforce(lambda: rows.update(status=status, revision=1))
        self.assertEqual(DeletionRequest.objects.get(pk=request.id).status, "BLOCKED")

    def test_database_rejects_invalid_status_transition(self) -> None:
        with self.settings(DELETION_PROPAGATION_ENABLED=True):
            request = self.declare()
        rows = DeletionRequest.objects.filter(pk=request.id)
        with self.assertRaises(IntegrityError):
            enforce(lambda: rows.update(status="BLOCKED", blocked_code="FEATURE_DISABLED", revision=1))
        self.assertEqual(DeletionRequest.objects.get(pk=request.id).status, "PROPAGATING")

    def test_database_requires_finished_targets_before_completion(self) -> None:
        with self.settings(DELETION_PROPAGATION_ENABLED=True):
            request = self.declare()
        rows = DeletionRequest.objects.filter(pk=request.id)
        with self.assertRaises(IntegrityError):
            enforce(lambda: rows.update(status="COMPLETED", revision=1))
        DeletionTarget.objects.filter(deletion_request=request).update(outcome="DONE")
        enforce(lambda: rows.update(status="COMPLETED", revision=1))
        self.assertEqual(DeletionRequest.objects.get(pk=request.id).status, "COMPLETED")

    def test_http_dry_run_lists_lineage_without_writing_anything(self) -> None:
        url = f"{self.deletion_url()}/dry-run"
        first = self.client.post(url)
        self.assertEqual(first.status_code, 200)
        document = first.json()
        self.assertFalse(document["propagation_enabled"])
        self.assertEqual({str(item["object_id"]) for item in document["affected"]},
                         {str(object_id) for _, object_id, _ in affected(self.actor, self.version)})
        self.assertFalse(Tombstone.objects.exists())
        self.assertFalse(DeletionRequest.objects.exists())
        self.assertFalse(DeletionTarget.objects.exists())
        self.assertEqual(self.client.post(url).json(), document)

    def test_http_declaration_replays_and_reads_back_the_same_work(self) -> None:
        created = self.http_declare()
        self.assertEqual((created["status"], created["policy_status"], created["blocked_code"]), ("BLOCKED", "BLOCKED", "FEATURE_DISABLED"))
        self.assertEqual(created["outstanding"], len(affected(self.actor, self.version)))
        self.assertEqual([target["object_type"] for target in created["targets"]], sorted(target["object_type"] for target in created["targets"]))
        self.assertEqual(self.http_declare(), created)
        self.assertEqual(DeletionRequest.objects.count(), 1)
        read = self.client.get(self.deletion_url())
        self.assertEqual(read.status_code, 200)
        self.assertEqual(read.json(), created)

    def test_http_declaration_stops_reads_and_rejects_a_second_declaration(self) -> None:
        preview = self.version.preview_id
        self.assertEqual(self.client.get(f"/api/v2/artifacts/{preview}").status_code, 200)
        self.http_declare()
        self.assertEqual(self.client.get(f"/api/v2/artifacts/{preview}").status_code, 409)
        self.assertEqual(self.client.post(self.deletion_url(), headers={"Idempotency-Key": "another-key"}).status_code, 409)

    def test_http_source_access_is_404_for_other_tenant_and_before_declaration(self) -> None:
        self.assertEqual(self.client.get(self.deletion_url()).status_code, 404)
        self.client.force_login(self.other.user)
        self.assertEqual(self.client.get(self.deletion_url()).status_code, 404)
        self.assertEqual(self.client.post(f"{self.deletion_url()}/dry-run").status_code, 404)
        self.assertEqual(self.client.post(self.deletion_url(), headers={"Idempotency-Key": "other"}).status_code, 404)
        self.assertFalse(DeletionRequest.objects.exists())

    def test_relay_and_propagation_converge_only_while_policy_is_open(self) -> None:
        with self.settings(DELETION_PROPAGATION_ENABLED=True):
            created = self.http_declare()
            self.assertEqual((created["status"], created["policy_status"]), ("PROPAGATING", "ACTIVE"))
            request = DeletionRequest.objects.get(pk=UUID(str(created["deletion_request_id"])))
            self.assertEqual(due(100), [(str(self.tenant.id), str(request.id))])
            with patch("catalog.tasks.app.send_task") as send:
                self.assertEqual(relay_deletion(), 1)
            send.assert_called_once()
            self.assertTrue(propagate(self.tenant.id, request.id))
            self.assertFalse(propagate(self.tenant.id, request.id))
            request.refresh_from_db()
            self.assertEqual((request.status, request.revision, request.blocked_code), ("COMPLETED", 1, None))
            self.assertEqual(outstanding(request), 0)
            self.assertEqual(DeletionTarget.objects.filter(outcome="DONE").count(), len(affected(self.actor, self.version)))
            self.assertEqual(due(100), [])
            read = self.client.get(self.deletion_url()).json()
            self.assertEqual((read["status"], read["outstanding"], read["revision"]), ("COMPLETED", 0, 1))

    def test_closed_policy_keeps_the_relay_empty_and_refuses_propagation(self) -> None:
        request = self.declare()
        with patch("catalog.tasks.app.send_task") as send:
            self.assertEqual(relay_deletion(), 0)
        send.assert_not_called()
        self.assertEqual(due(100), [])
        with self.assertRaises(ApiError) as raised:
            propagate(self.tenant.id, request.id)
        self.assertEqual((raised.exception.code, raised.exception.status), ("FEATURE_DISABLED", 503))
        request.refresh_from_db()
        self.assertEqual((request.status, request.policy_status), ("BLOCKED", "BLOCKED"))
        self.assertEqual(DeletionTarget.objects.filter(outcome="PENDING").count(), len(affected(self.actor, self.version)))
