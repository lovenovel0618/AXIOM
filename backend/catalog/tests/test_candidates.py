"""真實 PostgreSQL 下的候選、擬合與凍結：唯一鍵、複合外鍵、凍結鏈與 relay 排除。

Real-PostgreSQL candidate/fit/freeze persistence, deterministic ranking and fail-closed freeze.
"""
from collections.abc import Callable
from fractions import Fraction
from io import BytesIO
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID, uuid4
from django.contrib.auth.models import User
from django.db import IntegrityError, connection, transaction
from django.test import TransactionTestCase, override_settings
from catalog.artifacts import register as register_artifact
from catalog.candidates import persist, rows_hash
from catalog.equations import register as register_equation
from catalog.freezing import binding_hash, canonical_decimal, empty_search_decision, freeze_decision, frozen_candidate, frozen_submission, snapshot_payload
from catalog.ingest import complete_upload, ingest_tick
from catalog.models import Account, Artifact, Candidate, Dataset, DatasetVersion, FrozenSubmission, EquationVersion, FitRun, FrozenCandidate, ObservationSplit, ProfileBinding, Provenance, RepresentationSpec, Reservation, ResearchBudget, ResearchEvent, ResearchVersion, RootBudget, SealRegistration, Tenant, Upload
from catalog.research import create_research, create_version, research_for
from catalog.research_state import document_for, state_for, transition
from catalog.services import actor_for, create_dataset, create_upload, put_upload
from catalog.tests.test_research import CONTENT, LIMITS, draft_data
from catalog.validation import ApiError
from mathematics.compiler import compile_dsl
from mathematics.search import Domain, Request, Variable, search
from runtime.contracts import JsonObject, canonical_bytes, identity_hash
from runtime.models import InputSnapshot, RunEvent, RuntimeAttempt, RuntimeRun
from runtime.records import db_now

DIMENSIONLESS = (0,) * 7


def request(fit: list[tuple[float, float]], development: list[tuple[float, float]]) -> Request:
    """固定域與無量綱單位的離線請求；介面沒有 final_test 欄位。"""
    return Request(Variable("x", DIMENSIONLESS), DIMENSIONLESS, Domain(Fraction(-1000), Fraction(1000), True, True),
        tuple(fit), tuple(development))


def enforce(action: Callable[[], object]) -> None:
    """在單一交易內執行並檢查延遲複合外鍵；違反即拋 IntegrityError。"""
    with transaction.atomic():
        action()
        connection.check_constraints()


def non_canonical(context: JsonObject) -> None:
    """同時改寫擬合與凍結副本的參數形狀，促使 canonical 檢查先行拒絕。"""
    context["fit"]["parameters"] = {"c0": "2.50"}
    context["frozen_candidate"]["parameters"] = {"c0": "2.50"}


@override_settings(INGEST_ENABLED=True, INGEST_LIMITS_JSON=json.dumps(LIMITS), PROFILE_ENABLED=False)
class CandidateTests(TransactionTestCase):
    def setUp(self) -> None:
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        override = self.settings(OBJECT_ROOT=Path(directory.name))
        override.enable()
        self.addCleanup(override.disable)
        self.actor = self.account(Tenant.objects.create(name="candidate-synthetic"))
        self.other = self.account(Tenant.objects.create(name="candidate-other"))
        self.version = self.fixture()
        self.budget = ResearchBudget.objects.get(research_version=self.version)

    def account(self, tenant: Tenant) -> Account:
        user = User.objects.create(username=uuid4().hex, password="!")
        return Account.objects.create(user=user, tenant=tenant)

    def fixture(self) -> ResearchVersion:
        """以真實匯入建立可用的資料版本與研究版本，不使用偽造 fixture。"""
        with transaction.atomic():
            actor = actor_for(self.actor.user_id)
            dataset = Dataset.objects.get(pk=UUID(create_dataset(actor, {"name": "candidate"})["id"]))
            upload = create_upload(actor, dataset, {"filename": "synthetic", "format": "CSV", "size_bytes": len(CONTENT),
                "sha256": hashlib.sha256(CONTENT).hexdigest()}, "http://localhost")
            row = Upload.objects.get(pk=UUID(upload["id"]))
            put_upload(actor, row, upload["required_headers"]["X-Upload-Token"], BytesIO(CONTENT))
            run = complete_upload(actor, row, row.sha256, "complete")
        self.assertTrue(ingest_tick(str(actor.tenant_id), run["id"], 0))
        version_row = DatasetVersion.objects.get(dataset=dataset)
        with transaction.atomic():
            actor = actor_for(self.actor.user_id)
            research = research_for(actor, UUID(create_research(actor, {"name": "candidate"})["id"]))
            document = create_version(actor, research, draft_data(version_row.id))
        return ResearchVersion.objects.get(pk=UUID(document["id"]))

    def report(self) -> JsonObject:
        """精確線性資料的離線報告；fit 與 development 都不含 final_test。"""
        fit = [(float(index), float(2 * index + 1)) for index in range(6)]
        development = [(float(index), float(2 * index + 1)) for index in range(6, 8)]
        return search(request(fit, development))

    def store(self) -> list[Candidate]:
        with transaction.atomic():
            return persist(self.actor, self.version, self.budget, self.report())

    def freeze_context(self, rows: list[Candidate]) -> JsonObject:
        """由已落庫的候選、擬合與公式組出可 ACCEPT 的凍結情境；版本文件為副本。"""
        candidate = rows[0]
        fit = FitRun.objects.get(pk=UUID(candidate.document["fit_run_ids"][0]))
        equation = candidate.equation_version
        representation = RepresentationSpec.objects.get(pk=fit.representation_artifact_id)
        parameters: dict[str, str] = dict(fit.document["parameters"])
        frozen_id = str(uuid4())
        frozen: JsonObject = {"id": frozen_id, "candidate_id": str(candidate.id), "fit_run_id": str(fit.id),
            "equation_version_id": str(equation.id), "dataset_version_id": str(fit.dataset_version_id),
            "observation_split_id": str(fit.observation_split_id), "representation_artifact_id": str(representation.id),
            "dsl_identity_hash": equation.identity_hash, "parameters": parameters,
            "parameter_binding_hash": binding_hash(parameters), "development_rank": candidate.development_rank}
        plan: JsonObject = {"id": str(uuid4()), "tenant_id": str(self.version.tenant_id),
            "research_version_id": str(self.version.id), "purpose": self.version.document["purpose"]}
        submission: JsonObject = {"sealed_test_id": None, "metric_version": "2.0",
            "evaluation_policy_hash": self.version.document["evaluation_policy_hash"],
            "verification_plan_artifact_id": plan["id"], "verification_plan_hash": identity_hash(plan),
            "frozen_candidate_ids": [frozen_id]}
        payload: JsonObject = {"research_version_id": str(self.version.id), "sealed_test_id": submission["sealed_test_id"],
            "metric_version": submission["metric_version"], "evaluation_policy_hash": submission["evaluation_policy_hash"],
            "verification_plan_artifact_id": submission["verification_plan_artifact_id"],
            "verification_plan_hash": submission["verification_plan_hash"], "frozen_candidates": [frozen]}
        submission["snapshot_hash"] = identity_hash(payload)
        return {"research_version": json.loads(json.dumps(self.version.document)), "submission": submission,
            "verification_plan": plan, "representation": representation.document, "fit": fit.document,
            "equation": equation.document, "candidate": candidate.document, "frozen_candidate": frozen}

    def register_plan(self, version: ResearchVersion) -> tuple[JsonObject, Artifact]:
        content: JsonObject = {"id": str(uuid4()), "tenant_id": str(version.tenant_id),
            "research_version_id": str(version.id), "purpose": version.document["purpose"]}
        source = Provenance.objects.get(pk=version.provenance_id, tenant_id=version.tenant_id)
        artifact = register_artifact(self.actor, version.dataset_version, UUID(content["id"]), content, source, research_version=version)
        return content, artifact

    def register_sibling_plan(self, version: ResearchVersion) -> tuple[JsonObject, Artifact]:
        """在同一研究容器下另建版本並為它登記驗證計畫，用於計畫不符研究版本的拒絕路徑。"""
        with transaction.atomic():
            actor = actor_for(self.actor.user_id)
            research = research_for(actor, version.research_id)
            document = create_version(actor, research, draft_data(version.dataset_version_id))
        return self.register_plan(ResearchVersion.objects.get(pk=UUID(document["id"])))

    def register_seal(self, version: ResearchVersion) -> SealRegistration:
        run = RuntimeRun.objects.filter(document__type="INGEST").order_by("id").first()
        self.assertIsNotNone(run)
        return SealRegistration.objects.create(tenant_id=version.tenant_id, research_version=version, run=run,
            sealed_test_id=uuid4(), source_sha256="1" * 64, protocol_hash="2" * 64, authority_epoch=uuid4(),
            authority_sequence=1, attestation_hash="3" * 64, available=True)

    def test_candidates_are_ranked_deduplicated_and_bound_to_their_fit_runs(self) -> None:
        report = self.report()
        rows = self.store()
        self.assertGreater(len(rows), 0)
        self.assertEqual(len(rows), len(report["candidates"]))
        self.assertEqual([row.development_rank for row in rows], list(range(1, len(rows) + 1)))
        self.assertEqual([row.equation_version.identity_hash for row in rows], [entry["identity_hash"] for entry in report["candidates"]])
        self.assertEqual(len({row.equation_version_id for row in rows}), len(rows))
        self.assertEqual((Candidate.objects.count(), EquationVersion.objects.count(), FitRun.objects.count()), (len(rows), len(rows), len(rows)))
        self.assertEqual((ObservationSplit.objects.count(), RepresentationSpec.objects.count()), (1, 1))
        search_runs = RuntimeRun.objects.filter(document__type="SEARCH")
        self.assertEqual(search_runs.count(), 1)
        for rank, row in enumerate(rows, start=1):
            self.assertEqual(row.document["development_rank"], rank)
            self.assertEqual(row.document["search_run_id"], str(search_runs.get().id))
            self.assertEqual((row.document["validation_status"], row.document["validation_run_ids"]), ("NOT_RUN", []))
            fit = FitRun.objects.get(pk=UUID(row.document["fit_run_ids"][0]))
            self.assertEqual(fit.equation_version_id, row.equation_version_id)
            self.assertEqual((fit.document["split_role"], fit.document["refit_policy_artifact_id"]), ("FIT", None))
            self.assertEqual(fit.document["fit_rows_hash"], rows_hash(self.version.document["observation_split"]["fit"]))
            self.assertEqual(fit.document["optimizer"], row.document["source"])
            self.assertEqual(UUID(fit.document["representation_artifact_id"]), RepresentationSpec.objects.get().id)
            self.assertEqual(FitRun.objects.get(pk=fit.id).document["fit_row_ids"], [0, 1, 2, 3, 4, 5])

    def test_equivalent_structures_collapse_into_one_candidate_each(self) -> None:
        report = search(request([(-1.0, 4.0), (0.0, 4.0), (1.0, 4.0)], [(2.0, 4.0)]))
        self.assertEqual((report["proposed_count"], report["duplicate_count"], len(report["candidates"])), (4, 2, 2))
        with transaction.atomic():
            rows = persist(self.actor, self.version, self.budget, report)
        self.assertEqual((len(rows), Candidate.objects.count(), EquationVersion.objects.count()), (2, 2, 2))

    def test_database_rejects_duplicate_keys_and_every_mutation(self) -> None:
        rows = self.store()
        candidate = rows[0]
        fit = FitRun.objects.get(pk=UUID(candidate.document["fit_run_ids"][0]))
        split = ObservationSplit.objects.get()
        representation = RepresentationSpec.objects.get()
        identity = uuid4()
        duplicates: list[Callable[[], object]] = [
            lambda: Candidate.objects.create(id=identity, tenant_id=self.actor.tenant_id, search_run_id=candidate.search_run_id,
                equation_version_id=candidate.equation_version_id, development_rank=2,
                document=candidate.document | {"id": str(identity), "development_rank": 2}),
            lambda: FitRun.objects.create(id=identity, tenant_id=self.actor.tenant_id, run_id=fit.run_id,
                equation_version_id=fit.equation_version_id, dataset_version_id=fit.dataset_version_id,
                observation_split_id=fit.observation_split_id, representation_artifact_id=fit.representation_artifact_id,
                document=fit.document | {"id": str(identity)}),
            lambda: ObservationSplit.objects.create(id=identity, tenant_id=self.actor.tenant_id,
                dataset_version_id=split.dataset_version_id, row_ids_hash=split.row_ids_hash,
                document=split.document | {"id": str(identity)}),
            lambda: RepresentationSpec.objects.create(id=identity, tenant_id=self.actor.tenant_id,
                research_version_id=representation.research_version_id, dataset_version_id=representation.dataset_version_id,
                observation_split_id=representation.observation_split_id, fit_rows_hash=representation.fit_rows_hash,
                document=representation.document | {"id": str(identity)})]
        for index, action in enumerate(duplicates):
            with self.subTest(duplicate=index), self.assertRaises(IntegrityError):
                enforce(action)
        mutations: list[Callable[[], object]] = [
            lambda: Candidate.objects.filter(pk=candidate.id).update(development_rank=5),
            lambda: FitRun.objects.filter(pk=fit.id).delete(),
            lambda: ObservationSplit.objects.filter(pk=split.id).update(row_ids_hash="0" * 64),
            lambda: RepresentationSpec.objects.filter(pk=representation.id).delete()]
        for index, action in enumerate(mutations):
            with self.subTest(mutation=index), self.assertRaises(IntegrityError):
                enforce(action)

    def test_cross_tenant_references_are_rejected_by_composite_foreign_keys(self) -> None:
        rows = self.store()
        candidate = rows[0]
        foreign = register_equation(self.other, compile_dsl(canonical_bytes(candidate.equation_version.document["dsl"])), db_now())
        self.assertNotEqual(foreign.tenant_id, self.actor.tenant_id)
        identity = uuid4()
        forged = candidate.document | {"id": str(identity), "equation_version_id": str(foreign.id)}
        with self.assertRaises(IntegrityError):
            enforce(lambda: Candidate.objects.create(id=identity, tenant_id=self.actor.tenant_id,
                search_run_id=candidate.search_run_id, equation_version_id=foreign.id, development_rank=9, document=forged))

    def test_zero_candidates_persist_nothing_and_report_the_stable_diagnostic(self) -> None:
        with transaction.atomic():
            self.assertEqual(persist(self.actor, self.version, self.budget, self.report() | {"candidates": []}), [])
        for model in (Candidate, FitRun, ObservationSplit, RepresentationSpec):
            self.assertFalse(model.objects.exists())
        self.assertFalse(RuntimeRun.objects.filter(document__type__in=["SEARCH", "FIT"]).exists())
        self.assertEqual(empty_search_decision(True, 0, True), "FAILED")
        self.assertEqual(empty_search_decision(False, 0, True), "SUCCEEDED:INSUFFICIENT_EVIDENCE:NO_VALID_CANDIDATE")
        self.assertEqual(empty_search_decision(False, 3, False), "SUCCEEDED:INSUFFICIENT_EVIDENCE:BUDGET_EXHAUSTED")
        self.assertEqual(empty_search_decision(False, 3, True), "FREEZE_AND_EVALUATE")

    def test_final_test_never_appears_in_any_batch_interface(self) -> None:
        rows = self.store()
        fit = FitRun.objects.get(pk=UUID(rows[0].document["fit_run_ids"][0]))
        representation = RepresentationSpec.objects.get()
        for document in (rows[0].document, fit.document, representation.document):
            self.assertNotIn("final_test", json.dumps(document))
        self.assertEqual(fit.document["fit_row_ids"], self.version.document["observation_split"]["fit"])
        self.assertIn("final_test", self.version.document["observation_split"])
        self.assertFalse(hasattr(Request, "final_test"))

    def test_offline_search_and_fit_roots_stay_queued_without_snapshots(self) -> None:
        rows = self.store()
        runs = RuntimeRun.objects.filter(document__type__in=["SEARCH", "FIT"])
        self.assertEqual(runs.count(), len(rows) + 1)
        self.assertEqual({row.document["type"] for row in runs}, {"SEARCH", "FIT"})
        self.assertTrue(all(not row.control_only for row in runs))
        self.assertTrue(all(row.document["status"] == "QUEUED" for row in runs))
        self.assertFalse(RuntimeRun.objects.filter(pk__in=runs, control_only=False, document__type="INGEST",
            document__status__in=["QUEUED", "RUNNING"]).exists())
        self.assertFalse(ProfileBinding.objects.filter(run__in=runs).exists())
        for model in (InputSnapshot, RuntimeAttempt, RunEvent, RootBudget):
            self.assertFalse(model.objects.filter(run__in=runs).exists())
        self.assertFalse(Reservation.objects.filter(root__run__in=runs).exists())
        self.assertTrue(RuntimeRun.objects.filter(document__type="INGEST").exists())
        from catalog.tasks import relay_search
        from unittest.mock import patch
        with patch("catalog.tasks.app.send_task") as send:
            self.assertEqual(relay_search(), 0)
            send.assert_not_called()

    def test_parameter_binding_hash_matches_the_conformance_example(self) -> None:
        self.assertEqual(binding_hash({"a": "2", "b": "1"})[:8], "f7a837dc")
        self.assertEqual(binding_hash({"b": "1.0", "a": "2.000"}), binding_hash({"a": "2", "b": "1"}))
        self.assertEqual(canonical_decimal("2.500"), "2.5")
        self.assertEqual(canonical_decimal("-0"), "0")
        self.assertEqual(canonical_decimal("-3.10"), "-3.1")
        for value in ("1e3", "NaN", "", "01"):
            with self.subTest(value=value), self.assertRaises(ApiError):
                canonical_decimal(value)

    def test_freeze_decision_accepts_and_reports_every_rejection_code(self) -> None:
        context = self.freeze_context(self.store())
        self.assertEqual(freeze_decision(context), "ACCEPT")
        cases: list[tuple[str, Callable[[JsonObject], None]]] = [
            ("EVALUATION_POLICY_MISMATCH", lambda c: c["research_version"].update(evaluation_policy_hash="0" * 64)),
            ("VERIFICATION_PLAN_MISMATCH", lambda c: c["verification_plan"].update(research_version_id=str(uuid4()))),
            ("REPRESENTATION_MISMATCH", lambda c: c["representation"].update(fit_rows_hash="0" * 64)),
            ("FIT_REFERENCE_MISMATCH", lambda c: c["frozen_candidate"].update(fit_run_id=str(uuid4()))),
            ("EQUATION_MISMATCH", lambda c: c["frozen_candidate"].update(dsl_identity_hash="0" * 64)),
            ("BINDING_MISMATCH", lambda c: c["frozen_candidate"].update(parameters={"c0": "9"})),
            ("PARAMETER_NOT_CANONICAL", non_canonical),
            ("BINDING_HASH_MISMATCH", lambda c: c["frozen_candidate"].update(parameter_binding_hash="0" * 64)),
            ("SNAPSHOT_MISMATCH", lambda c: c["submission"].update(snapshot_hash="0" * 64)),
            ("RANK_MISMATCH", lambda c: c["submission"].update(frozen_candidate_ids=[]))]
        for code, mutate in cases:
            with self.subTest(code=code):
                broken = json.loads(json.dumps(context))
                mutate(broken)
                self.assertEqual(freeze_decision(broken), code)

    def test_frozen_candidate_is_persisted_idempotently_and_rejects_wrong_references(self) -> None:
        rows = self.store()
        candidate = rows[0]
        fit = FitRun.objects.get(pk=UUID(candidate.document["fit_run_ids"][0]))
        equation = candidate.equation_version
        representation = RepresentationSpec.objects.get(pk=fit.representation_artifact_id)
        with transaction.atomic():
            frozen = frozen_candidate(self.actor, candidate, fit, equation, representation, self.version)
        self.assertEqual((frozen.candidate_id, frozen.fit_run_id, frozen.development_rank), (candidate.id, fit.id, candidate.development_rank))
        self.assertEqual((frozen.dsl_identity_hash, frozen.parameter_binding_hash), (equation.identity_hash, binding_hash(dict(fit.document["parameters"]))))
        self.assertEqual(frozen.document["parameters"], fit.document["parameters"])
        self.assertEqual(frozen.document["parameter_binding_hash"], frozen.parameter_binding_hash)
        self.assertNotIn("final_test", json.dumps(frozen.document))
        with transaction.atomic():
            self.assertEqual(frozen_candidate(self.actor, candidate, fit, equation, representation, self.version).id, frozen.id)
        self.assertEqual(FrozenCandidate.objects.count(), 1)
        identity = uuid4()
        duplicate = frozen.document | {"id": str(identity)}
        with self.assertRaises(IntegrityError):
            enforce(lambda: FrozenCandidate.objects.create(id=identity, tenant_id=self.actor.tenant_id, candidate_id=candidate.id,
                fit_run_id=fit.id, equation_version_id=equation.id, dataset_version_id=frozen.dataset_version_id,
                observation_split_id=frozen.observation_split_id, representation_artifact_id=representation.id,
                development_rank=candidate.development_rank, dsl_identity_hash=equation.identity_hash,
                parameter_binding_hash=frozen.parameter_binding_hash, document=duplicate))
        other = rows[1]
        other_fit = FitRun.objects.get(pk=UUID(other.document["fit_run_ids"][0]))
        with self.assertRaises(ApiError) as mismatch:
            frozen_candidate(self.actor, candidate, other_fit, other.equation_version, representation, self.version)
        self.assertEqual(mismatch.exception.code, "EQUATION_MISMATCH")

    def test_frozen_submission_is_persisted_idempotently_and_projected(self) -> None:
        rows = self.store()
        candidate = rows[0]
        fit = FitRun.objects.get(pk=UUID(candidate.document["fit_run_ids"][0]))
        representation = RepresentationSpec.objects.get(pk=fit.representation_artifact_id)
        with transaction.atomic():
            frozen = frozen_candidate(self.actor, candidate, fit, candidate.equation_version, representation, self.version)
        plan, artifact = self.register_plan(self.version)
        seal = self.register_seal(self.version)
        with transaction.atomic():
            submission = frozen_submission(self.actor, self.version, [frozen], artifact)
        self.assertEqual((submission.research_version_id, submission.verification_plan_artifact_id), (self.version.id, artifact.id))
        self.assertEqual((submission.sealed_test_id, submission.metric_version, submission.status), (seal.sealed_test_id, "2.0", "FROZEN"))
        self.assertEqual(submission.document["frozen_candidate_ids"], [str(frozen.id)])
        self.assertEqual(submission.document["verification_plan_hash"], identity_hash(plan))
        self.assertEqual(submission.snapshot_hash, identity_hash(snapshot_payload(self.version, str(seal.sealed_test_id), artifact, [frozen])))
        with transaction.atomic():
            self.assertEqual(frozen_submission(self.actor, self.version, [frozen], artifact).id, submission.id)
        self.assertEqual(FrozenSubmission.objects.count(), 1)
        projected = document_for(self.version)
        self.assertEqual(projected["frozen_submission_ids"], [str(submission.id)])
        identity = uuid4()
        duplicate = submission.document | {"id": str(identity)}
        with self.assertRaises(IntegrityError):
            enforce(lambda: FrozenSubmission.objects.create(id=identity, tenant_id=self.actor.tenant_id,
                research_version_id=self.version.id, verification_plan_artifact_id=artifact.id, sealed_test_id=seal.sealed_test_id,
                metric_version="2.0", snapshot_hash=submission.snapshot_hash, status="FROZEN", document=duplicate))

    def test_frozen_submission_rejects_missing_seal_and_bad_plan(self) -> None:
        rows = self.store()
        candidate = rows[0]
        fit = FitRun.objects.get(pk=UUID(candidate.document["fit_run_ids"][0]))
        representation = RepresentationSpec.objects.get(pk=fit.representation_artifact_id)
        with transaction.atomic():
            frozen = frozen_candidate(self.actor, candidate, fit, candidate.equation_version, representation, self.version)
        _content, artifact = self.register_plan(self.version)
        with self.assertRaises(ApiError) as missing:
            frozen_submission(self.actor, self.version, [frozen], artifact)
        self.assertEqual(missing.exception.code, "SEALED_TEST_NOT_REGISTERED")
        self.register_seal(self.version)
        foreign_plan = Artifact.objects.get(pk=artifact.id)
        foreign_plan.content = dict(foreign_plan.content or {}) | {"research_version_id": str(uuid4())}
        with self.assertRaises(ApiError) as bad_plan:
            frozen_submission(self.actor, self.version, [frozen], foreign_plan)
        self.assertEqual(bad_plan.exception.code, "VERIFICATION_PLAN_MISMATCH")

    def store_many(self) -> list[Candidate]:
        """確定性產生兩個同結構去重後的候選，供分頁切片的 HTTP 測試使用。"""
        report = search(request([(-1.0, 4.0), (0.0, 4.0), (1.0, 4.0)], [(2.0, 4.0)]))
        with transaction.atomic():
            return persist(self.actor, self.version, self.budget, report)

    def search_run(self) -> RuntimeRun:
        return RuntimeRun.objects.get(document__type="SEARCH")

    def freeze_path(self) -> str:
        return f"/api/v2/research-versions/{self.version.id}/frozen-submissions"

    def freeze_payload(self, candidate_ids: list[str], plan_id: str) -> JsonObject:
        return {"frozen_candidate_ids": candidate_ids, "verification_plan_artifact_id": plan_id}

    def make_ready(self) -> int:
        """登記封存並在同一次遞增中綁定狀態、切到 READY；回傳可帶入 If-Control-Revision 的控制 revision。"""
        seal = self.register_seal(self.version)
        with transaction.atomic():
            state = state_for(self.version)
            state.seal = seal
            transition(state, "READY")
            return state_for(self.version).revision

    def current_revision(self) -> int:
        """讀取目前控制 revision，供不帶同冪等鍵的重送帶入正確前置條件。"""
        with transaction.atomic():
            return state_for(self.version).revision

    def post_freeze(self, payload: JsonObject, *, revision: int | str | None, key: str | None = None) -> tuple[int, JsonObject]:
        """以真 HTTP 送出派送觸發的凍結，回傳狀態碼與解碼後的 JSON；key／revision 給定才附相應標頭。"""
        headers: dict[str, str] = {}
        if key is not None:
            headers["Idempotency-Key"] = key
        if revision is not None:
            headers["If-Control-Revision"] = str(revision)
        response = self.client.post(self.freeze_path(), data=json.dumps(payload), content_type="application/json", headers=headers)
        return response.status_code, json.loads(response.content)

    def test_candidates_http_page_is_ranked_paged_and_owner_scoped(self) -> None:
        rows = self.store_many()
        self.assertEqual(len(rows), 2)
        run = self.search_run()
        self.client.force_login(self.actor.user)
        response = self.client.get(f"/api/v2/runs/{run.id}/candidates")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual([item["id"] for item in body["items"]], [str(row.id) for row in rows])
        self.assertIsNone(body["next_cursor"])
        first = self.client.get(f"/api/v2/runs/{run.id}/candidates?limit=1").json()
        self.assertEqual([item["id"] for item in first["items"]], [str(rows[0].id)])
        self.assertIsNotNone(first["next_cursor"])
        second = self.client.get(f"/api/v2/runs/{run.id}/candidates?limit=1&cursor={first['next_cursor']}").json()
        self.assertEqual([item["id"] for item in second["items"]], [str(rows[1].id)])
        self.assertIsNone(second["next_cursor"])
        self.client.force_login(self.other.user)
        self.assertEqual(self.client.get(f"/api/v2/runs/{run.id}/candidates").status_code, 404)

    def test_candidates_http_rejects_bad_params_and_unknown_runs(self) -> None:
        self.store()
        run = self.search_run()
        fit_run = RuntimeRun.objects.filter(document__type="FIT").first()
        assert fit_run is not None
        self.client.force_login(self.actor.user)
        for query in ("limit=0", "limit=201", "limit=x", "offset=1"):
            with self.subTest(query=query):
                self.assertEqual(self.client.get(f"/api/v2/runs/{run.id}/candidates?{query}").status_code, 422)
        self.assertEqual(self.client.get(f"/api/v2/runs/{run.id}/candidates?cursor=bogus").status_code, 400)
        self.assertEqual(self.client.get(f"/api/v2/runs/{uuid4()}/candidates").status_code, 404)
        self.assertEqual(self.client.get(f"/api/v2/runs/{fit_run.id}/candidates").status_code, 404)

    def test_formula_fit_and_frozen_reads_are_owner_scoped(self) -> None:
        rows = self.store()
        candidate = rows[0]
        fit = FitRun.objects.get(pk=UUID(candidate.document["fit_run_ids"][0]))
        representation = RepresentationSpec.objects.get(pk=fit.representation_artifact_id)
        with transaction.atomic():
            frozen = frozen_candidate(self.actor, candidate, fit, candidate.equation_version, representation, self.version)
        routes = ((f"/api/v2/equation-versions/{candidate.equation_version_id}", candidate.equation_version_id),
            (f"/api/v2/fit-runs/{fit.id}", fit.id), (f"/api/v2/frozen-candidates/{frozen.id}", frozen.id))
        self.client.force_login(self.actor.user)
        for path, identity in routes:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["id"], str(identity))
        self.client.force_login(self.other.user)
        for path, _identity in routes:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)
        self.assertEqual(self.client.get(f"/api/v2/equation-versions/{uuid4()}").status_code, 404)

    def test_frozen_submission_http_detail_requires_owner_scope(self) -> None:
        rows = self.store()
        candidate = rows[0]
        fit = FitRun.objects.get(pk=UUID(candidate.document["fit_run_ids"][0]))
        representation = RepresentationSpec.objects.get(pk=fit.representation_artifact_id)
        with transaction.atomic():
            frozen = frozen_candidate(self.actor, candidate, fit, candidate.equation_version, representation, self.version)
        _plan, artifact = self.register_plan(self.version)
        self.register_seal(self.version)
        with transaction.atomic():
            submission = frozen_submission(self.actor, self.version, [frozen], artifact)
        self.client.force_login(self.actor.user)
        response = self.client.get(f"/api/v2/frozen-submissions/{submission.id}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], str(submission.id))
        self.client.force_login(self.other.user)
        self.assertEqual(self.client.get(f"/api/v2/frozen-submissions/{submission.id}").status_code, 404)

    def test_freeze_submission_http_builds_snapshot_event_and_projection(self) -> None:
        rows = self.store()
        _plan, artifact = self.register_plan(self.version)
        revision = self.make_ready()
        self.client.force_login(self.actor.user)
        status, document = self.post_freeze(self.freeze_payload([str(rows[0].id)], str(artifact.id)), revision=revision, key=uuid4().hex)
        self.assertEqual(status, 201)
        self.assertEqual((document["kind"], document["status"]), ("FrozenSubmission", "FROZEN"))
        submission = FrozenSubmission.objects.get(pk=UUID(str(document["id"])))
        self.assertEqual(submission.document, document)
        self.assertEqual(submission.document["frozen_candidate_ids"], [str(FrozenCandidate.objects.get().id)])
        self.assertEqual((FrozenCandidate.objects.count(), FrozenSubmission.objects.count()), (1, 1))
        event = ResearchEvent.objects.get(research_version_id=self.version.id, document__event_type="SubmissionFrozen")
        self.assertEqual(event.document["payload"], {"submission_id": str(submission.id), "snapshot_hash": submission.snapshot_hash})
        projected = document_for(self.version)
        self.assertEqual(projected["frozen_submission_ids"], [str(submission.id)])
        self.assertEqual(projected["revision"], revision + 1)

    def test_freeze_submission_http_replays_key_and_resend_stays_idempotent(self) -> None:
        rows = self.store()
        _plan, artifact = self.register_plan(self.version)
        revision = self.make_ready()
        self.client.force_login(self.actor.user)
        payload = self.freeze_payload([str(rows[0].id)], str(artifact.id))
        key = uuid4().hex
        first_status, first = self.post_freeze(payload, revision=revision, key=key)
        self.assertEqual(first_status, 201)
        self.assertEqual(self.post_freeze(payload, revision=revision, key=key), (201, first))
        conflict = self.post_freeze(self.freeze_payload([str(rows[1].id)], str(artifact.id)), revision=revision, key=key)
        self.assertEqual((conflict[0], conflict[1]["code"]), (409, "IDEMPOTENCY_CONFLICT"))
        resent = self.post_freeze(payload, revision=self.current_revision(), key=uuid4().hex)
        self.assertEqual(resent, (201, first))
        self.assertEqual((FrozenSubmission.objects.count(), ResearchEvent.objects.filter(document__event_type="SubmissionFrozen").count()), (1, 1))

    def test_freeze_submission_http_enforces_precondition_revision_and_ready_state(self) -> None:
        rows = self.store()
        _plan, artifact = self.register_plan(self.version)
        payload = self.freeze_payload([str(rows[0].id)], str(artifact.id))
        self.client.force_login(self.actor.user)
        missing = self.post_freeze(payload, revision=None, key=uuid4().hex)
        self.assertEqual((missing[0], missing[1]["code"]), (428, "PRECONDITION_REQUIRED"))
        malformed = self.post_freeze(payload, revision="x1", key=uuid4().hex)
        self.assertEqual((malformed[0], malformed[1]["code"]), (422, "INVALID_SCHEMA"))
        draft = self.post_freeze(payload, revision=0, key=uuid4().hex)
        self.assertEqual((draft[0], draft[1]["code"]), (409, "INVALID_TRANSITION"))
        revision = self.make_ready()
        conflict = self.post_freeze(payload, revision=revision + 5, key=uuid4().hex)
        self.assertEqual((conflict[0], conflict[1]["code"]), (412, "REVISION_CONFLICT"))
        self.assertEqual(self.post_freeze(payload, revision=revision, key=uuid4().hex)[0], 201)

    def test_freeze_submission_http_rejects_empty_missing_and_mismatched_references(self) -> None:
        rows = self.store()
        _plan, artifact = self.register_plan(self.version)
        revision = self.make_ready()
        self.client.force_login(self.actor.user)
        cases = (
            (self.freeze_payload([], str(artifact.id)), 422, "INVALID_SCHEMA"),
            (self.freeze_payload([str(uuid4())], str(artifact.id)), 404, "NOT_FOUND"),
            (self.freeze_payload([str(rows[0].id)], str(uuid4())), 404, "NOT_FOUND"),
            (self.freeze_payload([str(rows[0].id), str(rows[0].id)], str(artifact.id)), 409, "RANK_MISMATCH"),
        )
        for payload, expected_status, expected_code in cases:
            with self.subTest(code=expected_code):
                status, body = self.post_freeze(payload, revision=revision, key=uuid4().hex)
                self.assertEqual((status, body["code"]), (expected_status, expected_code))
        _content, sibling = self.register_sibling_plan(self.version)
        mismatch = self.post_freeze(self.freeze_payload([str(rows[0].id)], str(sibling.id)), revision=revision, key=uuid4().hex)
        self.assertEqual((mismatch[0], mismatch[1]["code"]), (409, "VERIFICATION_PLAN_MISMATCH"))
        seal = SealRegistration.objects.get(research_version=self.version)
        SealRegistration.objects.filter(pk=seal.id).update(available=False)
        unsealed = self.post_freeze(self.freeze_payload([str(rows[0].id)], str(artifact.id)), revision=revision, key=uuid4().hex)
        self.assertEqual((unsealed[0], unsealed[1]["code"]), (409, "SEALED_TEST_NOT_REGISTERED"))
        self.assertEqual((FrozenCandidate.objects.count(), FrozenSubmission.objects.count()), (0, 0))

    def test_freeze_submission_http_requires_owner_scope(self) -> None:
        rows = self.store()
        _plan, artifact = self.register_plan(self.version)
        revision = self.make_ready()
        payload = self.freeze_payload([str(rows[0].id)], str(artifact.id))
        self.client.force_login(self.other.user)
        status, body = self.post_freeze(payload, revision=revision, key=uuid4().hex)
        self.assertEqual((status, body["code"]), (404, "NOT_FOUND"))
        self.assertEqual(FrozenSubmission.objects.count(), 0)
