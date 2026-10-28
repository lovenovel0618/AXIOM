"""Real ingestion, PostgreSQL, tenant-scope and immutable preflight records."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
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
from catalog.inspection import parameters_from, preflight
from catalog.models import Account, Dataset, DatasetVersion, ResearchInspection, ResearchVersion, Tenant, Upload
from catalog.research import create_research, create_version
from catalog.services import actor_for, create_dataset, create_upload, put_upload
from catalog.storage import LocalVersionStore, ObjectRef, StorageRejected
from catalog.tests.test_research import draft_data
from catalog.tests.test_inspection_engine import LIMITS, linear_model
from catalog.validation import ApiError
from ingestion.research import POLICY


@override_settings(INGEST_ENABLED=True, INGEST_LIMITS_JSON=json.dumps(LIMITS.document()), PROFILE_ENABLED=False)
class InspectionTests(TransactionTestCase):
    def setUp(self) -> None:
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        override = self.settings(OBJECT_ROOT=self.root)
        override.enable()
        self.addCleanup(override.disable)
        user = User.objects.create(username=uuid4().hex,password="!")
        self.actor = Account.objects.create(user=user,tenant=Tenant.objects.create(name="synthetic"))
        content = b'x,y\n' + b''.join(f'{i},{2*i+1}\n'.encode() for i in range(10))
        with transaction.atomic():
            actor = actor_for(user.pk)
            self.dataset = Dataset.objects.get(pk=UUID(create_dataset(actor,{"name":"inspection"})["id"]))
            upload = create_upload(actor,self.dataset,{"filename":"test","format":"CSV","size_bytes":len(content),"sha256":hashlib.sha256(content).hexdigest()},"http://localhost")
            row = Upload.objects.get(pk=UUID(upload["id"]))
            put_upload(actor,row,upload["required_headers"]["X-Upload-Token"],BytesIO(content))
            run = complete_upload(actor,row,row.sha256,"complete")
        self.assertTrue(ingest_tick(str(actor.tenant_id),run["id"],0))
        dataset_version = DatasetVersion.objects.get()
        with transaction.atomic():
            actor = actor_for(user.pk)
            research = create_research(actor,{"name":"inspection"})
            from catalog.research import research_for
            document = create_version(actor,research_for(actor,UUID(research["id"])),draft_data(dataset_version.id))
        self.version = ResearchVersion.objects.get(pk=UUID(document["id"]))
        self.model = json.dumps(linear_model(document["domain"])).encode()
        self.client.force_login(user)

    def inspect(self) -> dict[str, object]:
        return preflight(self.actor.id,self.version.id,LIMITS,self.model)

    def test_isolated_time_and_group_validation_and_masked_final_failures(self) -> None:
        from catalog.research import research_for
        from runtime.contracts import identity_hash
        for kind in ("TIME_ORDERED", "GROUPED_ROWS"):
            for valid in (True, False):
                data = draft_data(self.version.dataset_version_id)
                data["evaluation_policy"]["comparison_method"] = "NONE"
                if kind == "TIME_ORDERED":
                    data["semantic_profile"]["time_ordered"] = True
                    data["observation_split"].update(kind=kind, time_column="x")
                    if not valid:
                        data["observation_split"].update(fit=[0,1,2,3,4,6], development=[5,7])
                        with transaction.atomic(), self.assertRaises(ApiError):
                            create_version(self.actor, research_for(self.actor, self.version.research_id), data)
                        continue
                else:
                    data["semantic_profile"]["group_column"] = "x"
                    assignments = [[i, f"s:{i}", "fit" if i < 6 else "development" if i < 8 else "final_test"] for i in range(10)]
                    data["observation_split"].update(kind=kind, group_column="x",
                        group_assignment_digest=identity_hash(assignments) if valid else "0" * 64)
                with transaction.atomic():
                    document = create_version(self.actor, research_for(self.actor, self.version.research_id), data)
                result = preflight(self.actor.id, UUID(document["id"]), LIMITS, self.model)
                row = ResearchInspection.objects.get(pk=result["id"])
                self.assertEqual(row.document["result"]["quality"], "PASS" if valid else "BLOCKED")
                if not valid:
                    self.assertIsNone(row.document["result"]["model_evaluation"])
                    self.assertEqual(row.document["result"]["blocking_code"], "DATA_QUALITY_BLOCKED")

    def raw_path(self) -> Path:
        stored = self.version.dataset_version.raw.object
        assert stored is not None
        return LocalVersionStore(self.root).path(ObjectRef(self.actor.tenant_id,stored.upload_id,stored.id,stored.sha256,stored.size_bytes))

    def test_persists_snapshot_and_replays_without_reexecuting(self) -> None:
        first = self.inspect()
        with patch("catalog.inspection.inspect_research") as worker:
            self.assertEqual(self.inspect(),first)
            worker.assert_not_called()
        row = ResearchInspection.objects.get()
        self.assertEqual(row.document["result"]["policy_version"],POLICY)
        self.assertEqual(row.document["result"]["quality"],"PASS")
        self.assertEqual(row.document["result"]["model_evaluation"]["development"]["mae"],"0")
        self.assertEqual(row.configuration["research"],self.version.document)
        self.assertGreater(row.document["measured_execution_usage"]["peak_memory_bytes"],0)
        self.version.refresh_from_db()
        self.assertEqual(self.version.document["status"],"DRAFT")
        self.assertIsNone(self.version.document["quality_report_id"])
        self.assertEqual(self.client.post(f'/api/v2/research-versions/{self.version.id}/validate').status_code,503)

    def test_source_change_during_worker_prevents_commit(self) -> None:
        path = self.raw_path()
        def replace_source(*args: object, **kwargs: object) -> dict[str, object]:
            path.chmod(0o600)
            path.write_bytes(b'source-replaced')
            return {"policy_version":POLICY,"quality":"BLOCKED","blocking_code":"DATA_QUALITY_BLOCKED","precision_bits":53,"fit_summary":None,"model_evaluation":None}
        with patch("catalog.inspection.inspect_research",side_effect=replace_source):
            with self.assertRaises(StorageRejected):
                self.inspect()
        self.assertFalse(ResearchInspection.objects.exists())

    def test_environment_change_rejects_late_result(self) -> None:
        initial = "a"*64
        with patch("catalog.inspection.environment",side_effect=[initial,"b"*64]):
            with self.assertRaises(ApiError) as raised:
                self.inspect()
        self.assertEqual(raised.exception.code,"CHECKPOINT_INCOMPATIBLE")
        self.assertFalse(ResearchInspection.objects.exists())

    def test_disabled_and_inactive_actor_never_parse(self) -> None:
        for change in ("disabled","inactive"):
            with self.subTest(change=change):
                Account.objects.filter(pk=self.actor.id).update(enabled=True)
                User.objects.filter(pk=self.actor.user_id).update(is_active=True)
                if change=="disabled": Account.objects.filter(pk=self.actor.id).update(enabled=False)
                else: User.objects.filter(pk=self.actor.user_id).update(is_active=False)
                with patch("catalog.inspection.inspect_research") as worker:
                    with self.assertRaises(ApiError): self.inspect()
                    worker.assert_not_called()

    def test_same_tenant_account_has_no_research_access(self) -> None:
        user = User.objects.create(username=uuid4().hex,password="!")
        other = Account.objects.create(user=user,tenant=self.actor.tenant)
        with self.assertRaises(ApiError) as raised:
            preflight(other.id,self.version.id,LIMITS)
        self.assertEqual(raised.exception.code,"NOT_FOUND")

    def test_native_updates_deletes_and_forged_identity_rejected(self) -> None:
        self.inspect()
        for action in (lambda: ResearchInspection.objects.update(document={}),lambda: ResearchInspection.objects.all().delete()):
            with self.assertRaises(IntegrityError),transaction.atomic(): action()
        row = ResearchInspection.objects.get()
        document = deepcopy(row.document)
        document["research_version_id"] = str(uuid4())
        with self.assertRaises(IntegrityError),transaction.atomic():
            ResearchInspection.objects.create(tenant=self.actor.tenant,actor=self.actor,research_version=self.version,request_hash="b"*64,configuration=row.configuration,document=document)
            connection.check_constraints()

    def test_parallel_checks_create_only_one_record(self) -> None:
        def invoke(_index: int) -> object:
            try: return self.inspect()["id"]
            finally: connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(len(set(pool.map(invoke,range(2)))),1)
        self.assertEqual(ResearchInspection.objects.count(),1)

    def test_invalid_parameters_and_child_protocol_fail_closed(self) -> None:
        with self.assertRaises(ApiError): parameters_from('{"a":1}')
        with self.assertRaises(ApiError): parameters_from('{"a":"1","a":"2"}')
        with patch("catalog.inspection.inspect_research",return_value={"quality":"PASS","final_values":[999]}):
            with self.assertRaises(ValueError): self.inspect()
        self.assertFalse(ResearchInspection.objects.exists())

    def test_changed_source_also_blocks_cached_record(self) -> None:
        self.inspect()
        path = self.raw_path()
        path.chmod(0o600)
        path.write_bytes(b'changed')
        with self.assertRaises(StorageRejected): self.inspect()

    def test_no_model_path_persists_quality_without_scores(self) -> None:
        report = preflight(self.actor.id,self.version.id,LIMITS)
        self.assertEqual(report["result"]["quality"],"PASS")
        self.assertIsNone(report["result"]["model_evaluation"])
