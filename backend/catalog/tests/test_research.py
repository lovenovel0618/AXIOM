"""PostgreSQL and real-parser research-draft boundary regression tests."""
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
from catalog.models import Account, Audit, Dataset, DatasetVersion, IdempotentResult, Provenance, Research, ResearchVersion, Tenant, Upload
from catalog.research import create_research, create_version, research_for
from catalog.research_validation import iid_rows
from catalog.services import actor_for, create_dataset, create_upload, put_upload, provenance
from catalog.validation import validate_api
from runtime.contracts import JsonObject, identity_hash
from runtime.models import RuntimeRun

CONTENT = b'x,y\n' + b''.join(f'{i},{2*i+1}\n'.encode() for i in range(10))
LIMITS = {"max_rows": 100, "max_columns": 8, "max_cell_utf8_bytes": 4096, "max_decoded_bytes": 65536, "max_parse_seconds": 10}


def draft_data(identity: UUID) -> JsonObject:
    mapping = {"name": "x", "source_column": "x", "unit": [0] * 7, "conversion": {"source_unit": "1", "scale": "1", "offset": "0"}}
    target = deepcopy(mapping)
    target.update(name="y", source_column="y")
    return {
        "dataset_version_id": str(identity), "semantic_profile": {"inputs": [mapping], "target": target, "units_confirmed": True, "time_ordered": False, "measurement_resolution": None, "resolution_reason": "synthetic exact integers", "group_column": None},
        "budget": {"cpu_seconds": 30, "gpu_seconds": 0, "wall_seconds": 60, "tokens": 0, "candidate_limit": 10, "memory_bytes": 1073741824}, "purpose": "DESCRIPTION",
        "observation_split": {"kind": "EXPLICIT", "dataset_version_id": str(identity), "fit": [0,1,2,3,4,5], "development": [6,7], "final_test": [8,9], "gap_rows": 0, "lookback_rows": 0, "horizon_rows": 0, "seed": 7, "time_column": None, "group_column": None, "group_assignment_digest": None, "splitter_version": "synthetic-explicit-v1", "policy_version": "2.0", "sealed_final_test": True},
        "domain": [{"name": "x", "lower": {"numerator": "0", "denominator": "1"}, "upper": {"numerator": "10", "denominator": "1"}, "lower_closed": True, "upper_closed": True}],
        "evaluation_policy": {"policy_version": "1.0", "metric_version": "2.0", "error_model": "EXACT", "absolute_error_bound": None, "comparison_method": "IID_PAIRED_BOOTSTRAP", "bootstrap_replicates": 2000, "bootstrap_seed": 7, "block_method": None, "block_length": None, "practical_scale_override": None, "practical_margin_ratio": "0.01", "baseline": "FIT_MEAN", "practical_scale_reason": None},
    }


@override_settings(INGEST_ENABLED=True, INGEST_LIMITS_JSON=json.dumps(LIMITS), PROFILE_ENABLED=False)
class ResearchTests(TransactionTestCase):
    def setUp(self) -> None:
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        override = self.settings(OBJECT_ROOT=Path(directory.name))
        override.enable()
        self.addCleanup(override.disable)
        self.actor = self.account(Tenant.objects.create(name="synthetic"))
        with transaction.atomic():
            actor = actor_for(self.actor.user_id)
            self.dataset = Dataset.objects.get(pk=UUID(create_dataset(actor, {"name": "synthetic"})["id"]))
            upload = create_upload(actor, self.dataset, {"filename": "test.csv", "format": "CSV", "size_bytes": len(CONTENT), "sha256": hashlib.sha256(CONTENT).hexdigest()}, "http://localhost")
            row = Upload.objects.get(pk=UUID(upload["id"]))
            put_upload(actor, row, upload["required_headers"]["X-Upload-Token"], BytesIO(CONTENT))
            run = complete_upload(actor, row, row.sha256, "complete")
            self.research = UUID(create_research(actor, {"name": "synthetic"})["id"])
        self.assertTrue(ingest_tick(str(actor.tenant_id), run["id"], 0))
        self.version = DatasetVersion.objects.get()
        self.data = draft_data(self.version.id)
        self.path = f"/api/v2/researches/{self.research}/versions"
        self.client.force_login(self.actor.user)

    def account(self, tenant: Tenant) -> Account:
        user = User.objects.create(username=uuid4().hex, password="!")
        return Account.objects.create(user=user, tenant=tenant)

    def post(self, data: JsonObject | None = None, key: str = "create") -> tuple[int, JsonObject]:
        response = self.client.post(self.path, json.dumps(self.data if data is None else data), content_type="application/json", headers={"Idempotency-Key": key})
        return response.status_code, json.loads(response.content)

    def test_create_reopen_and_no_unearned_results(self) -> None:
        status, value = self.post()
        self.assertEqual(status, 201)
        validate_api(value, "ResearchVersion")
        self.assertEqual(self.post(), (status, value))
        self.assertEqual(ResearchVersion.objects.count(), 1)
        self.assertEqual(RuntimeRun.objects.count(), 1)
        self.assertEqual(value["status"], "DRAFT")
        self.assertIsNone(value["observation_split"]["sealed_test_id"])
        self.assertIsNone(value["structure_assessment_artifact_id"])
        self.assertEqual(value["evaluation_policy_hash"], identity_hash(self.data["evaluation_policy"]))
        self.assertEqual(value["observation_split"]["row_ids_hash"], identity_hash({name: self.data["observation_split"][name] for name in ("fit", "development", "final_test", "gap_rows", "lookback_rows", "horizon_rows")}))
        response = self.client.get(f'/api/v2/research-versions/{value["id"]}')
        self.assertEqual(json.loads(response.content), value)
        self.assertEqual(response["Cache-Control"], "no-store")
        pending = self.client.post(f'/api/v2/research-versions/{value["id"]}/validate')
        self.assertEqual(pending.status_code, 503)
        self.assertEqual(ResearchVersion.objects.get().document["status"], "DRAFT")

    def test_source_aliases_are_exact_and_distinct(self) -> None:
        for column, name, code in [(" X", "x", "SOURCE_COLUMN_NOT_FOUND"), ("y", "x", "SOURCE_COLUMN_CONFLICT"), ("x", "y", "SOURCE_COLUMN_CONFLICT")]:
            with self.subTest(column=column, name=name):
                data = deepcopy(self.data)
                data["semantic_profile"]["inputs"][0].update(source_column=column, name=name)
                status, error = self.post(data)
                self.assertEqual((status, error["code"]), (422, code))
        self.assertFalse(ResearchVersion.objects.exists())

    def test_unit_and_decimal_boundaries_are_exact(self) -> None:
        data = deepcopy(self.data)
        conversion = data["semantic_profile"]["inputs"][0]["conversion"]
        conversion.update(scale="0." + "0" * 200 + "1", offset="273.15")
        self.assertEqual(self.post(data)[0], 201)
        for scale in ["0", "-1", "1e3", "1" * 257]:
            with self.subTest(scale=scale):
                data = deepcopy(self.data)
                data["semantic_profile"]["inputs"][0]["conversion"]["scale"] = scale
                self.assertEqual(self.post(data, key=scale[:10])[0], 422)

    def test_domain_requires_canonical_nonempty_matching_interval(self) -> None:
        for change in [{"name": "z"}, {"lower": {"numerator": "20", "denominator": "1"}}, {"lower": {"numerator": "2", "denominator": "2"}}, {"lower": {"numerator": "-0", "denominator": "1"}}, {"lower": {"numerator": "10", "denominator": "1"}, "lower_closed": False}]:
            with self.subTest(change=change):
                data = deepcopy(self.data)
                data["domain"][0].update(change)
                self.assertEqual(self.post(data)[0], 422)
        data = deepcopy(self.data)
        data["domain"][0]["lower"] = {"numerator": "10", "denominator": "1"}
        self.assertEqual(self.post(data)[0], 201)  # singleton closed domain is valid; PROFILE checks observations later

    def test_split_rejects_overlap_omission_range_and_wrong_version(self) -> None:
        for change in [{"fit": [0,1,2,3,4,6]}, {"fit": [0,1,2,3,4]}, {"final_test": [8,10]}, {"final_test": [8,8]}, {"dataset_version_id": str(uuid4())}, {"sealed_test_id": str(uuid4())}]:
            with self.subTest(change=change):
                data = deepcopy(self.data)
                data["observation_split"].update(change)
                self.assertEqual(self.post(data)[0], 422)
        self.assertFalse(ResearchVersion.objects.exists())

    def test_unsorted_explicit_sets_are_stored_in_canonical_order(self) -> None:
        self.data["observation_split"]["fit"].reverse()
        status, value = self.post()
        self.assertEqual(status, 201)
        self.assertEqual(value["observation_split"]["fit"], list(range(6)))

    def test_uuid_case_is_normalized_before_database_binding(self) -> None:
        self.data["dataset_version_id"] = str(self.version.id).upper()
        self.data["observation_split"]["dataset_version_id"] = str(self.version.id).upper()
        status, value = self.post()
        self.assertEqual(status, 201)
        self.assertEqual(value["observation_split"]["dataset_version_id"], str(self.version.id))

    def test_iid_seed_is_recomputed(self) -> None:
        split = self.data["observation_split"]
        expected = {"fit": [1,3,4,5,6,8], "development": [7,9], "final_test": [0,2]}
        self.assertEqual(iid_rows(10, 7), expected)
        split.update(kind="IID_ROWS", splitter_version="axiom-iid-sha256-v1", **expected)
        self.assertEqual(self.post()[0], 201)
        split["seed"] = 8
        self.assertEqual(self.post(key="wrong-seed")[0], 422)

    def test_evaluation_policy_cross_checks(self) -> None:
        for change in [{"error_model": "ABSOLUTE_BOUND", "absolute_error_bound": "0"}, {"practical_margin_ratio": "0"}, {"practical_margin_ratio": "1.000000000000000000001"}, {"practical_scale_override": "0", "practical_scale_reason": "reason"}, {"comparison_method": "BLOCK_BOOTSTRAP", "block_method": "MOVING_BLOCK", "block_length": 1}]:
            with self.subTest(change=change):
                data = deepcopy(self.data)
                data["evaluation_policy"].update(change)
                status, error = self.post(data)
                self.assertEqual((status, error["code"]), (422, "EVALUATION_POLICY_INVALID"))
        self.data["evaluation_policy"].update(error_model="UNSPECIFIED", comparison_method="NONE")
        self.assertEqual(self.post()[0], 201)

    def test_time_group_metadata_is_accepted_but_mixed_dependencies_and_unknown_refit_are_rejected(self) -> None:
        data = deepcopy(self.data)
        data["semantic_profile"]["time_ordered"] = True
        data["observation_split"].update(kind="TIME_ORDERED", time_column="x")
        data["evaluation_policy"]["comparison_method"] = "NONE"
        self.assertEqual(self.post(data, key="time")[0], 201)
        data = deepcopy(self.data)
        data["semantic_profile"]["group_column"] = "x"
        data["observation_split"].update(kind="GROUPED_ROWS", group_column="x", group_assignment_digest="a" * 64)
        data["evaluation_policy"]["comparison_method"] = "NONE"
        self.assertEqual(self.post(data, key="group")[0], 201)
        data = deepcopy(self.data)
        data["semantic_profile"]["time_ordered"] = True
        self.assertEqual(self.post(data)[0], 422)
        data = deepcopy(self.data)
        data["refit_policy"] = {"optimizer": "future", "optimizer_parameters": {}, "candidate_selection": "TOP_K_DEVELOPMENT", "top_k": 1}
        self.assertEqual(self.post(data)[0], 503)
        self.assertEqual(ResearchVersion.objects.count(), 2)

    def test_owner_scope_even_for_same_tenant_account(self) -> None:
        _, value = self.post()
        other = self.account(self.actor.tenant)
        self.client.force_login(other.user)
        self.assertEqual(self.post()[0], 404)
        self.assertEqual(self.client.get(f'/api/v2/research-versions/{value["id"]}').status_code, 404)
        self.assertEqual(self.client.get(f'/api/v2/researches/{self.research}').status_code, 404)
        self.assertEqual(json.loads(self.client.get('/api/v2/researches').content)["items"], [])

    def test_other_tenant_and_disabled_actor_are_rejected(self) -> None:
        other = self.account(Tenant.objects.create(name="other"))
        self.client.force_login(other.user)
        self.assertEqual(self.post()[0], 404)
        self.client.force_login(self.actor.user)
        Account.objects.filter(pk=self.actor.id).update(enabled=False)
        self.assertEqual(self.post()[0], 403)

    def test_research_create_idempotency(self) -> None:
        self.path = "/api/v2/researches"
        first = self.post({"name": "new"})
        self.assertEqual(first[0], 201)
        self.assertEqual(self.post({"name": "new"}), first)
        self.assertEqual(self.post({"name": "different"})[0], 409)
        self.assertEqual(self.client.get(f'/api/v2/researches/{self.research}').status_code, 200)

    def test_cursor_scope_limits(self) -> None:
        self.post()
        self.post(key="second")
        response = json.loads(self.client.get(self.path, {"limit": 1}).content)
        cursor = response["next_cursor"]
        self.assertIsNotNone(cursor)
        following = self.client.get(self.path, {"cursor": cursor, "limit": 1})
        self.assertEqual(len(json.loads(following.content)["items"]), 1)
        self.assertNotEqual(json.loads(following.content)["items"][0]["id"], response["items"][0]["id"])
        self.assertEqual(self.client.get('/api/v2/researches', {"cursor": cursor}).status_code, 400)
        for params in [{"cursor": "bad"}, {"limit": 0}, {"limit": 201}, {"limit": "x"}, {"unexpected": 1}]:
            self.assertIn(self.client.get(self.path, params).status_code, {400,422})

    def test_atomic_failure_rolls_back_provenance_audit_and_idempotency(self) -> None:
        before = (Provenance.objects.count(), Audit.objects.count(), IdempotentResult.objects.count())
        with patch("catalog.research.ResearchVersion.objects.create", side_effect=IntegrityError("synthetic dependency")):
            self.assertEqual(self.post()[0], 503)
        self.assertFalse(ResearchVersion.objects.exists())
        self.assertEqual((Provenance.objects.count(), Audit.objects.count(), IdempotentResult.objects.count()), before)

    def test_database_immutability_and_no_fabricated_ready_insert(self) -> None:
        self.post()
        for action in [lambda: ResearchVersion.objects.update(document={"status": "READY"}), lambda: Research.objects.update(owner=self.account(self.actor.tenant))]:
            with self.assertRaises(IntegrityError), transaction.atomic():
                action()
        existing = ResearchVersion.objects.get()
        identity, source = uuid4(), uuid4()
        bad = deepcopy(existing.document)
        bad.update(id=str(identity), status="READY", current_event_cursor=f"RESEARCH:{identity}:0")
        with self.assertRaises(IntegrityError), transaction.atomic():
            provenance(self.actor, "ResearchVersion", identity, source)
            ResearchVersion.objects.create(id=identity, tenant=self.actor.tenant, research_id=self.research, dataset_version=self.version, document=bad, provenance_id=source)

    def test_database_cross_tenant_owner_foreign_key(self) -> None:
        other = self.account(Tenant.objects.create(name="other"))
        identity, source = uuid4(), uuid4()
        # Valid same-tenant provenance whose creator is the foreign owner is itself rejected.
        with self.assertRaises(IntegrityError), transaction.atomic():
            provenance(self.actor, "Research", identity, source)
            Research.objects.create(id=identity, tenant=self.actor.tenant, owner=other, name="forged", provenance_id=source)
            connection.check_constraints()

    def test_parallel_same_key_only_one_draft(self) -> None:
        def invoke(_index: int) -> str:
            try:
                with transaction.atomic():
                    actor = actor_for(self.actor.user_id)
                    from catalog.services import replay
                    def authorize(previous: JsonObject) -> None:
                        research_for(actor, UUID(previous["research_id"]))
                    result = replay(actor, self.path, "parallel", self.data, lambda: create_version(actor, research_for(actor, self.research), self.data), authorize)
                    return result["id"]
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=4) as pool:
            self.assertEqual(len(set(pool.map(invoke, range(4)))), 1)
        self.assertEqual(ResearchVersion.objects.count(), 1)
