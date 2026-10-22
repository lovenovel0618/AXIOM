"""凍結與比較決策：逐條實作 contract_scenarios 的凍結鏈，並落庫 FrozenCandidate / FrozenSubmission。

Fail-closed freeze decisions mirroring contract_scenarios; final_test execution is still out of scope.

本模組的純函式裁決與 `docs/企劃案/tools/contract_scenarios.py` 逐字對齊並回傳同一組穩定代碼。
`SNAPSHOT_MISMATCH` 屬 `FrozenSubmission.snapshot_hash`；本模組會建立提交包，但仍不執行 final_test
或 FinalEvaluationSlot。"""
import re
from uuid import UUID, uuid4
from catalog.ingest_manifest import environment
from catalog.models import Account, Artifact, Candidate, EquationVersion, FitRun, FrozenCandidate, FrozenSubmission, RepresentationSpec, ResearchVersion, SealRegistration
from catalog.validation import ApiError
from runtime.contracts import JsonObject, identity_hash, validate
from runtime.records import db_now

DECIMAL = re.compile(r"^-?(0|[1-9][0-9]*)(\.[0-9]+)?$")


def canonical_decimal(value: str) -> str:
    """去尾零並把 -0 折成 0；只接受契約十進位記法，遇到指數或其他文字一律拒絕。"""
    if DECIMAL.fullmatch(value) is None:
        raise ApiError("PARAMETER_NOT_CANONICAL", 422)
    negative = value.startswith("-")
    integer, separator, fraction = value.removeprefix("-").partition(".")
    fraction = fraction.rstrip("0")
    magnitude = integer + (separator + fraction if fraction else "")
    return "-" + magnitude if negative and magnitude != "0" else magnitude


def binding_hash(parameters: dict[str, str]) -> str:
    """以名稱排序、十進位去冗餘零後算 SHA-256；canonical JSON 已排序鍵，故此處逐值正規化。"""
    return identity_hash({name: canonical_decimal(value) for name, value in parameters.items()})


def freeze_recipe_decision(recipe: JsonObject, fit: JsonObject, version: JsonObject) -> str:
    """表徵 recipe 必須與 FitRun 同租戶、同研究版本，並在三欄上完全一致。"""
    if recipe["id"] != fit["representation_artifact_id"]:
        return "REPRESENTATION_MISMATCH"
    if recipe["tenant_id"] != version["tenant_id"] or recipe["research_version_id"] != version["id"]:
        return "REPRESENTATION_MISMATCH"
    for key in ("dataset_version_id", "observation_split_id", "fit_rows_hash"):
        if recipe[key] != fit[key]:
            return "REPRESENTATION_MISMATCH"
    return "ACCEPT"


def frozen_binding_decision(frozen: JsonObject, fit: JsonObject, equation: JsonObject) -> str:
    """凍結參數必須是擬合的完整且正規副本，binding hash 與 DSL 參數名稱集合都要逐條相符。"""
    if frozen["parameters"] != fit["parameters"]:
        return "BINDING_MISMATCH"
    parameters: dict[str, str] = frozen["parameters"]
    if any(value != canonical_decimal(value) for value in parameters.values()):
        return "PARAMETER_NOT_CANONICAL"
    if frozen["parameter_binding_hash"] != binding_hash(parameters):
        return "BINDING_HASH_MISMATCH"
    declared: list[JsonObject] = equation["dsl"]["parameters"]
    if set(parameters) != {str(item["name"]) for item in declared}:
        return "BINDING_MISMATCH"
    return "ACCEPT"


def freeze_policy_decision(context: JsonObject) -> str:
    """評估政策與驗證計畫必須與研究版本及提交一致；本批不建立這兩個物件，僅供純函式對照。"""
    version, submission, plan = context["research_version"], context["submission"], context["verification_plan"]
    policy_hash = identity_hash(version["evaluation_policy"])
    if version["evaluation_policy_hash"] != policy_hash or submission["evaluation_policy_hash"] != policy_hash:
        return "EVALUATION_POLICY_MISMATCH"
    if (plan["tenant_id"] != version["tenant_id"] or plan["research_version_id"] != version["id"]
            or plan["purpose"] != version["purpose"]):
        return "VERIFICATION_PLAN_MISMATCH"
    if (submission["verification_plan_artifact_id"] != plan["id"]
            or submission["verification_plan_hash"] != identity_hash(plan)):
        return "VERIFICATION_PLAN_MISMATCH"
    return "ACCEPT"


def freeze_decision(context: JsonObject) -> str:
    """凍結鏈的權威裁決；順序與代碼和 contract_scenarios 的 `freeze_decision` 逐字一致。"""
    policy = freeze_policy_decision(context)
    if policy != "ACCEPT":
        return policy
    recipe = freeze_recipe_decision(context["representation"], context["fit"], context["research_version"])
    if recipe != "ACCEPT":
        return recipe
    frozen, fit, equation = context["frozen_candidate"], context["fit"], context["equation"]
    candidate, submission = context["candidate"], context["submission"]
    if frozen["candidate_id"] != candidate["id"] or frozen["fit_run_id"] != fit["id"] or fit["id"] not in candidate["fit_run_ids"]:
        return "FIT_REFERENCE_MISMATCH"
    for key in ("equation_version_id", "dataset_version_id", "observation_split_id", "representation_artifact_id"):
        if frozen[key] != fit[key]:
            return "FIT_REFERENCE_MISMATCH"
    if frozen["equation_version_id"] != equation["id"] or frozen["dsl_identity_hash"] != equation["identity_hash"]:
        return "EQUATION_MISMATCH"
    binding = frozen_binding_decision(frozen, fit, equation)
    if binding != "ACCEPT":
        return binding
    payload = {"research_version_id": context["research_version"]["id"], "sealed_test_id": submission["sealed_test_id"],
        "metric_version": submission["metric_version"], "evaluation_policy_hash": submission["evaluation_policy_hash"],
        "verification_plan_artifact_id": submission["verification_plan_artifact_id"],
        "verification_plan_hash": submission["verification_plan_hash"], "frozen_candidates": [frozen]}
    if submission["snapshot_hash"] != identity_hash(payload):
        return "SNAPSHOT_MISMATCH"
    if submission["frozen_candidate_ids"] != [frozen["id"]] or frozen["development_rank"] != candidate["development_rank"]:
        return "RANK_MISMATCH"
    return "ACCEPT"


def empty_search_decision(infrastructure_failed: bool, eligible_candidates: int, final_budget_available: bool) -> str:
    """零候選與預算不足的權威裁決；結果只落在服務層回報並帶 product_status=NOT_RUN。"""
    if infrastructure_failed:
        return "FAILED"
    if eligible_candidates == 0:
        return "SUCCEEDED:INSUFFICIENT_EVIDENCE:NO_VALID_CANDIDATE"
    if not final_budget_available:
        return "SUCCEEDED:INSUFFICIENT_EVIDENCE:BUDGET_EXHAUSTED"
    return "FREEZE_AND_EVALUATE"


def snapshot_payload(version: ResearchVersion, sealed_test_id: str, verification_plan: Artifact,
                     frozen: list[FrozenCandidate]) -> JsonObject:
    ordered = sorted(frozen, key=lambda row: (row.development_rank, str(row.id)))
    return {"research_version_id": str(version.id), "sealed_test_id": sealed_test_id, "metric_version": "2.0",
        "evaluation_policy_hash": version.document["evaluation_policy_hash"],
        "verification_plan_artifact_id": str(verification_plan.id),
        "verification_plan_hash": identity_hash(verification_plan.content), "frozen_candidates": [row.document for row in ordered]}


def _verification_plan_document(version: ResearchVersion, artifact: Artifact) -> JsonObject:
    content = artifact.content
    if (artifact.tenant_id != version.tenant_id or artifact.research_version_id != version.id
            or content is None or content.get("id") != str(artifact.id)
            or content.get("tenant_id") != str(version.tenant_id)
            or content.get("research_version_id") != str(version.id)
            or content.get("purpose") != version.document["purpose"]):
        raise ApiError("VERIFICATION_PLAN_MISMATCH", 409)
    return content


def frozen_submission(actor: Account, version: ResearchVersion, frozen: list[FrozenCandidate],
                      verification_plan: Artifact) -> FrozenSubmission:
    """以 development_rank 固定候選排序並建立 FrozenSubmission；同一 snapshot_hash 重送讀回原列。"""
    if len(frozen) == 0:
        raise ApiError("INVALID_SCHEMA", 422)
    seal = SealRegistration.objects.filter(research_version=version, tenant_id=actor.tenant_id, available=True).first()
    if seal is None:
        raise ApiError("SEALED_TEST_NOT_REGISTERED", 409)
    plan = _verification_plan_document(version, verification_plan)
    policy_hash = identity_hash(version.document["evaluation_policy"])
    if version.document["evaluation_policy_hash"] != policy_hash:
        raise ApiError("EVALUATION_POLICY_MISMATCH", 409)
    ordered = sorted(frozen, key=lambda row: (row.development_rank, str(row.id)))
    if len({row.id for row in ordered}) != len(ordered) or len({row.development_rank for row in ordered}) != len(ordered):
        raise ApiError("RANK_MISMATCH", 409)
    for row in ordered:
        if (row.tenant_id != actor.tenant_id or row.representation_artifact.research_version_id != version.id
                or row.dataset_version_id != version.dataset_version_id):
            raise ApiError("FIT_REFERENCE_MISMATCH", 409)
    identity, created = uuid4(), db_now()
    payload = snapshot_payload(version, str(seal.sealed_test_id), verification_plan, ordered)
    snapshot = identity_hash(payload)
    existing = FrozenSubmission.objects.filter(research_version=version, snapshot_hash=snapshot).first()
    if existing is not None:
        return existing
    document: JsonObject = {"kind": "FrozenSubmission", "id": str(identity), "tenant_id": str(actor.tenant_id),
        "schema_version": "2.0", "created_at": created.isoformat(), "research_version_id": str(version.id),
        "sealed_test_id": str(seal.sealed_test_id), "frozen_candidate_ids": [str(row.id) for row in ordered],
        "metric_version": "2.0", "snapshot_hash": snapshot, "status": "FROZEN",
        "evaluation_policy_hash": policy_hash, "verification_plan_artifact_id": str(verification_plan.id),
        "verification_plan_hash": identity_hash(plan)}
    validate(document, "research-v2.schema.json", "FrozenSubmission")
    return FrozenSubmission.objects.create(id=identity, tenant_id=actor.tenant_id, research_version=version,
        verification_plan_artifact=verification_plan, sealed_test_id=seal.sealed_test_id, metric_version="2.0",
        snapshot_hash=snapshot, status="FROZEN", document=document, created_at=created)


def authorized_submission(actor: Account, identity: UUID) -> FrozenSubmission:
    """重新驗租戶與研究 owner 後回 FrozenSubmission；不因知道 UUID 就放行。"""
    row = FrozenSubmission.objects.filter(pk=identity, tenant_id=actor.tenant_id).first()
    if row is None:
        raise ApiError("NOT_FOUND", 404)
    from catalog.research import version_for
    version_for(actor, row.research_version_id)
    validate(row.document, "research-v2.schema.json", "FrozenSubmission")
    return row


def frozen_candidate(actor: Account, candidate: Candidate, fit: FitRun, equation: EquationVersion,
                     representation: RepresentationSpec, version: ResearchVersion) -> FrozenCandidate:
    """驗證 AX-47 凍結不變條件後落庫；任一不符即 Fail-Closed 拒絕，不寫入任何列。

    凍結副本只在通過 recipe、公式、引用與 binding 檢查後才建立，且 `parameters` 是該 FitRun 的
    完整正規副本；`dsl_identity_hash` 直接取自 EquationVersion，不接受呼叫端另行宣稱。"""
    existing = FrozenCandidate.objects.filter(candidate_id=candidate.id, fit_run_id=fit.id).first()
    if existing is not None:
        return existing
    if candidate.equation_version_id != equation.id or fit.equation_version_id != equation.id:
        raise ApiError("EQUATION_MISMATCH", 409)
    if str(fit.id) not in {str(item) for item in candidate.document["fit_run_ids"]}:
        raise ApiError("FIT_REFERENCE_MISMATCH", 409)
    recipe = freeze_recipe_decision(representation.document, fit.document, version.document)
    if recipe != "ACCEPT":
        raise ApiError(recipe, 409)
    parameters: dict[str, str] = dict(fit.document["parameters"])
    for value in parameters.values():
        if value != canonical_decimal(value):
            raise ApiError("PARAMETER_NOT_CANONICAL", 409)
    identity, created = uuid4(), db_now()
    document: JsonObject = {"kind": "FrozenCandidate", "id": str(identity), "tenant_id": str(actor.tenant_id),
        "schema_version": "2.0", "created_at": created.isoformat(), "candidate_id": str(candidate.id),
        "equation_version_id": str(equation.id), "fit_run_id": str(fit.id),
        "dataset_version_id": str(fit.dataset_version_id), "observation_split_id": str(fit.observation_split_id),
        "dsl_identity_hash": equation.identity_hash, "parameters": parameters,
        "parameter_binding_hash": binding_hash(parameters), "development_rank": candidate.development_rank,
        "environment_digest": environment(), "representation_artifact_id": str(representation.id)}
    validate(document, "runtime-v2.schema.json", "FrozenCandidate")
    return FrozenCandidate.objects.create(id=identity, tenant_id=actor.tenant_id, candidate=candidate, fit_run=fit,
        equation_version=equation, dataset_version=fit.dataset_version, observation_split=fit.observation_split,
        representation_artifact=representation, development_rank=candidate.development_rank,
        dsl_identity_hash=equation.identity_hash, parameter_binding_hash=document["parameter_binding_hash"],
        document=document, created_at=created)
