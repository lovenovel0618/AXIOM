"""候選、擬合與兩個 recipe 的權威落庫與授權讀取：觀測切分、識別表徵、候選身分、擬合結果與凍結副本。

Offline candidate, fit and recipe persistence plus owner-scoped reads; no dispatch, no scoring and no final_test.

本模組只把 #3 的離線搜尋報告落成不可變列，不派送 run、不建 InputSnapshot、不建帳本列，
也不評估 final_test。`SEARCH`／`FIT` root 由 `catalog.search_run` 建立並停在 `QUEUED`，
`catalog.tasks` 的兩個 relay 只掃 INGEST 與 ProfileBinding，因此不會被撿走。"""
from collections.abc import Sequence
from uuid import UUID, uuid4
from django.core import signing
from django.db.models import Q
from catalog.equations import register as register_equation
from catalog.models import Account, Candidate, EquationVersion, FitRun, FrozenCandidate, ObservationSplit, RepresentationSpec, ResearchBudget, ResearchVersion
from catalog.research import version_for
from catalog.search_run import create as create_root_run
from catalog.validation import ApiError, validate_api
from mathematics.compiler import compile_dsl
from runtime.contracts import JsonObject, canonical_bytes, identity_hash, validate
from runtime.models import RuntimeRun
from runtime.records import db_now

PRECISION_BITS = 53
IDENTITY_METHOD = "IDENTITY"
IDENTITY_CONFIG: JsonObject = {"method": IDENTITY_METHOD, "input_dimension": 1, "output_dimension": 1,
    "inverse_kind": "EXACT", "information_loss": False}
CANDIDATES_SALT = "axiom-candidates-v1"


def rows_hash(rows: Sequence[int]) -> str:
    """fit 列陣列的 canonical SHA-256；與 PROFILE 既有 fit_rows_hash 及 conformance 同規則。"""
    return identity_hash(list(rows))


def observation_split(actor: Account, version: ResearchVersion) -> ObservationSplit:
    """把研究版本已固定的觀測切分落成不可變 recipe；同資料版本同 row_ids_hash 只留一列。"""
    document: JsonObject = version.document["observation_split"]
    validate(document, "runtime-v2.schema.json", "ObservationSplit")
    row, _created = ObservationSplit.objects.get_or_create(dataset_version_id=version.dataset_version_id,
        row_ids_hash=document["row_ids_hash"], defaults={"id": UUID(document["id"]), "tenant_id": actor.tenant_id,
        "created_at": db_now(), "document": document})
    return row


def representation(actor: Account, version: ResearchVersion, split: ObservationSplit) -> RepresentationSpec:
    """建立 M1 的識別表徵 recipe；重複呼叫讀回同一列。

    M1 不做降維，因此 `input_dimension`／`output_dimension`／`max_output_dimension` 相等，
    `inverse_kind=EXACT`、`information_loss=false`、`selection_data_role=DEVELOPMENT`。在本系統中
    `FitRun.representation_artifact_id` 正是 `catalog_representationspec` 的資料列，因此四個必填
    Artifact 引用與 inverse map 都指向這份最小 recipe 自身，不新增任何偽造的外部 Artifact。"""
    fit_rows: list[int] = list(version.document["observation_split"]["fit"])
    fit_hash = rows_hash(fit_rows)
    existing = RepresentationSpec.objects.filter(research_version_id=version.id,
        observation_split_id=split.id, fit_rows_hash=fit_hash).first()
    if existing is not None:
        return existing
    identity, created = uuid4(), db_now()
    document: JsonObject = {"kind": "RepresentationSpec", "id": str(identity), "tenant_id": str(actor.tenant_id),
        "research_version_id": str(version.id), "schema_version": "1.0", "created_at": created.isoformat(),
        "artifact_access_class": "PROJECT", "dataset_version_id": str(version.dataset_version_id),
        "observation_split_id": str(split.id), "method": IDENTITY_METHOD, "config_artifact_id": str(identity),
        "config_hash": identity_hash(IDENTITY_CONFIG), "fit_rows_hash": fit_hash, "input_dimension": 1,
        "output_dimension": 1, "max_output_dimension": 1, "inverse_kind": "EXACT", "information_loss": False,
        "forward_map_artifact_id": str(identity), "inverse_map_artifact_id": str(identity),
        "row_dependencies_artifact_id": str(identity), "unit_domain_artifact_id": str(identity),
        "selection_data_role": "DEVELOPMENT"}
    validate(document, "research-learning-v1.schema.json", "RepresentationSpec")
    return RepresentationSpec.objects.create(id=identity, tenant_id=actor.tenant_id, research_version=version,
        dataset_version=version.dataset_version, observation_split=split, fit_rows_hash=fit_hash,
        document=document, created_at=created)


def _origin(entry: JsonObject) -> str:
    """取報告已排序來源中的第一個；`search()` 已依來源與成本形狀定序，這裡不再重新排序。"""
    origins: list[JsonObject] = entry["origins"]
    return str(origins[0]["source"])


def _parameters(dsl: JsonObject) -> dict[str, str]:
    """候選參數即 AST 內 `lower=upper` 的綁定；不另外注入係數或改寫數值。"""
    declared: list[JsonObject] = dsl["parameters"]
    return {str(item["name"]): str(item["lower"]) for item in declared}


def _fit_run(actor: Account, version: ResearchVersion, budget: ResearchBudget, equation: EquationVersion,
             split: ObservationSplit, representation_row: RepresentationSpec, optimizer: str,
             parameters: dict[str, str], fit_rows: list[int], fit_hash: str) -> FitRun:
    """建立 FIT root 與其擬合結果；split_role 固定 FIT，因此 refit policy 必為 null。"""
    identity, created = uuid4(), db_now()
    root = create_root_run(actor, version, budget, "FIT", equation)
    document: JsonObject = {"kind": "FitRun", "id": str(identity), "tenant_id": str(actor.tenant_id),
        "schema_version": "2.0", "created_at": created.isoformat(), "run_id": str(root.id),
        "equation_version_id": str(equation.id), "dataset_version_id": str(version.dataset_version_id),
        "parameters": parameters, "optimizer": optimizer, "observation_split_id": str(split.id),
        "split_role": "FIT", "precision_bits": PRECISION_BITS, "fit_row_ids": fit_rows, "fit_rows_hash": fit_hash,
        "refit_policy_artifact_id": None, "execution_manifest_id": str(root.document["execution_manifest_id"]),
        "preprocessor_artifact_id": None, "representation_artifact_id": str(representation_row.id)}
    validate(document, "runtime-v2.schema.json", "FitRun")
    return FitRun.objects.create(id=identity, tenant_id=actor.tenant_id, run=root, equation_version=equation,
        dataset_version=version.dataset_version, observation_split=split, representation_artifact=representation_row,
        fit_rows_hash=fit_hash, document=document, created_at=created)


def _candidate(actor: Account, search_run_id: UUID, equation: EquationVersion, rank: int, source: str,
               fit: FitRun) -> Candidate:
    """建立同結構去重的候選身分；`development_rank` 依 #3 的決定性 tie-break 持久化。"""
    identity, created = uuid4(), db_now()
    document: JsonObject = {"kind": "Candidate", "id": str(identity), "tenant_id": str(actor.tenant_id),
        "schema_version": "2.0", "created_at": created.isoformat(), "search_run_id": str(search_run_id),
        "equation_version_id": str(equation.id), "source": source, "development_rank": rank,
        "validation_status": "NOT_RUN", "fit_run_ids": [str(fit.id)], "validation_run_ids": []}
    validate(document, "runtime-v2.schema.json", "Candidate")
    return Candidate.objects.create(id=identity, tenant_id=actor.tenant_id, search_run_id=search_run_id,
        equation_version=equation, development_rank=rank, document=document, created_at=created)


def persist(actor: Account, version: ResearchVersion, budget: ResearchBudget, report: JsonObject) -> list[Candidate]:
    """把 #3 的離線搜尋報告落成 SEARCH root、兩個 recipe、候選與擬合；零候選時不建立任何列。

    呼叫端須自行開啟交易。回傳的候選已依 `development_rank` 排序，與報告順序一致。"""
    entries: list[JsonObject] = report["candidates"]
    if not entries:
        return []
    split = observation_split(actor, version)
    representation_row = representation(actor, version, split)
    fit_rows: list[int] = list(version.document["observation_split"]["fit"])
    fit_hash = rows_hash(fit_rows)
    search_run = create_root_run(actor, version, budget, "SEARCH")
    rows: list[Candidate] = []
    for rank, entry in enumerate(entries, start=1):
        plan = compile_dsl(canonical_bytes(entry["dsl"]))
        equation = register_equation(actor, plan, db_now())
        optimizer = _origin(entry)
        fit = _fit_run(actor, version, budget, equation, split, representation_row, optimizer,
            _parameters(entry["dsl"]), fit_rows, fit_hash)
        rows.append(_candidate(actor, search_run.id, equation, rank, optimizer, fit))
    return rows


def _search_run(actor: Account, identity: UUID) -> RuntimeRun:
    """SEARCH root 授權：租戶分區、非 control probe，且研究版本必須屬於 actor。"""
    row = RuntimeRun.objects.filter(pk=identity, tenant_id=actor.tenant_id, control_only=False).first()
    if row is None or row.document["type"] != "SEARCH":
        raise ApiError("NOT_FOUND", 404)
    version_for(actor, UUID(row.document["research_version_id"]))
    return row


def candidates_page(actor: Account, identity: UUID, cursor: str, limit: int) -> JsonObject:
    """依 development_rank 穩定分頁同一 SEARCH 的候選；游標綁 actor／run 且 15 分鐘到期。"""
    _search_run(actor, identity)
    if not 1 <= limit <= 200:
        raise ApiError("INVALID_SCHEMA", 422)
    rows = Candidate.objects.filter(search_run_id=identity, tenant_id=actor.tenant_id).order_by("development_rank", "id")
    if cursor:
        try:
            value = signing.loads(cursor, salt=CANDIDATES_SALT, max_age=900)
            if value["actor"] != str(actor.id) or value["run"] != str(identity):
                raise ValueError("Cursor scope")
            rank, last = int(value["rank"]), UUID(value["id"])
            rows = rows.filter(Q(development_rank__gt=rank) | Q(development_rank=rank, id__gt=last))
        except (signing.BadSignature, ValueError, TypeError, KeyError) as error:
            raise ApiError("INVALID_CURSOR", 400) from error
    selected = list(rows[:limit + 1])
    next_cursor = None
    if len(selected) > limit:
        last_row = selected[limit - 1]
        next_cursor = signing.dumps({"actor": str(actor.id), "run": str(identity),
            "rank": last_row.development_rank, "id": str(last_row.id)}, salt=CANDIDATES_SALT)
    result: JsonObject = {"items": [row.document for row in selected[:limit]], "next_cursor": next_cursor}
    validate_api(result, "CandidatePage")
    return result


def authorized_equation(actor: Account, identity: UUID) -> EquationVersion:
    """公式版本只經其所屬候選的研究 owner 讀取；無候選引用或跨 owner 一律 404。"""
    row = EquationVersion.objects.filter(pk=identity, tenant_id=actor.tenant_id).first()
    if row is None:
        raise ApiError("NOT_FOUND", 404)
    candidate = Candidate.objects.select_related("search_run").filter(tenant_id=actor.tenant_id, equation_version_id=row.id).first()
    if candidate is None:
        raise ApiError("NOT_FOUND", 404)
    version_for(actor, UUID(candidate.search_run.document["research_version_id"]))
    validate_api(row.document, "EquationVersion")
    return row


def authorized_fit_run(actor: Account, identity: UUID) -> FitRun:
    """擬合結果經表徵 recipe 回到研究版本驗 owner；跨租戶或跨 owner 一律 404。"""
    row = FitRun.objects.filter(pk=identity, tenant_id=actor.tenant_id).first()
    if row is None:
        raise ApiError("NOT_FOUND", 404)
    version_for(actor, row.representation_artifact.research_version_id)
    validate_api(row.document, "FitRun")
    return row


def authorized_frozen_candidate(actor: Account, identity: UUID) -> FrozenCandidate:
    """凍結副本經表徵 recipe 回到研究版本驗 owner；不因知道 UUID 就放行。"""
    row = FrozenCandidate.objects.filter(pk=identity, tenant_id=actor.tenant_id).first()
    if row is None:
        raise ApiError("NOT_FOUND", 404)
    version_for(actor, row.representation_artifact.research_version_id)
    validate_api(row.document, "FrozenCandidate")
    return row
