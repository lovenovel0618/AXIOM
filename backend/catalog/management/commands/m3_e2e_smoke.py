"""M3 端到端驗收：上傳、語意確認、研究、SEARCH、候選比較、FIT 到證據檢視的真實 HTTP 鏈路。

單一可重跑命令，走真實迴環 HTTP（`--frontend` 改走前端代理）與專用 worker；每一站都必須先
觀察到權威終態才前進，任何一站不符即中止。鏈路內容抽成 `run_chain`，供資安切片等其他命令
在同一組權威資源上重驗存取政策；此命令只蒐集證據，不宣告任何 Gate 通過。
"""
import json
import secrets
import time
from argparse import ArgumentParser
from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID, uuid4
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from catalog.management.commands.business_ingest_smoke import upload, wait_run
from catalog.management.commands.catalog_smoke import BASE, Browser, FRONTEND_BASE
from catalog.management.commands.research_draft_smoke import check, configuration
from catalog.models import Account, Candidate, FitRun, ResearchBudget, Reservation, RootBudget, Tenant
from catalog.validation import validate_api
from runtime.models import ValidationRun


@dataclass(frozen=True)
class PreparedChain:
    """M3 鏈路前兩階段（上傳落版與封印 PROFILE）完成後的權威識別碼。"""
    dataset_id: str
    dataset_version_id: str
    ingest_run_id: str
    research_id: str
    research_version_id: str
    profile_run_id: str
    sealed_test_registered: bool
    evidence_bundle_id: str
    sealed_bundle_revision: int


@dataclass(frozen=True)
class ChainResult:
    """M3 鏈路一次成功執行後可被重複使用的權威識別碼與觀測值。"""
    dataset_id: str
    dataset_version_id: str
    ingest_run_id: str
    research_id: str
    research_version_id: str
    profile_run_id: str
    sealed_test_registered: bool
    evidence_bundle_id: str
    search_run_id: str
    fit_run_id: str
    equation_version_id: str
    validation_run_ids: tuple[str, ...]
    validation_split_roles: tuple[str, ...]
    validation_scores: tuple[dict[str, object], ...]
    candidate_count: int
    candidate_ranks: tuple[int, ...]
    second_candidate_compared: bool
    evidence_proof_count: int
    search_root_budget_status: str
    fit_root_budget_status: str
    research_budget_status: str
    remaining_candidates: int


def synthetic_rows(rows: int) -> bytes:
    """固定合成的觀測序列：x 落在語意域 [0,10] 內，10 列時與既有鏈路資料逐字相同。"""
    lines: list[str] = []
    for index in range(rows):
        x = index * 10 / rows
        lines.append(f"{x:g},{2 * x + 1:g}")
    return ('時間（秒）,位移（公分）\n' + "\n".join(lines) + "\n").encode()


def chain_configuration(version_id: str, rows: int = 10) -> dict[str, object]:
    """M3 鏈路要連續跑 PROFILE、SEARCH 與逐候選 FIT，因此把版本預算放寬到足以承載三段的完整容量。

    SEARCH 要求 root 至少保留 `30 + 3 × max_strategy_seconds` 秒 CPU，且 FIT 每個根各預留 2 GiB，
    原 draft 冒煙用的 30 秒額度必然不足；這裡只調整容量，不動語意切分與評估政策。"""
    data = cast("dict[str, object]", configuration(version_id, rows))
    budget = dict(cast("dict[str, object]", data["budget"]))
    budget.update({"cpu_seconds": 120, "wall_seconds": 300, "memory_bytes": 4 * 1024**3})
    data["budget"] = budget
    return data


def read_json(browser: Browser, path: str) -> Any:
    """GET 單一資源；非 200 直接失敗，避免後續以殘缺資料誤判。"""
    status, raw = browser.request(path)
    check(status == 200, f"GET {path} -> {status}")
    return json.loads(raw)


def version_revision(browser: Browser, version_id: str) -> int:
    """控制面每次都以最新 revision fencing，不硬編版本演化後的數字。"""
    return int(read_json(browser, f"/api/v2/research-versions/{version_id}")["revision"])


def candidate_page(browser: Browser, run_id: str, cursor: str, limit: int) -> dict[str, Any]:
    """固定 limit 走簽章游標；契約驗證後才回傳，確保分頁欄位齊備。"""
    query = f"?limit={limit}" + (f"&cursor={cursor}" if cursor else "")
    document: dict[str, Any] = read_json(browser, f"/api/v2/runs/{run_id}/candidates{query}")
    validate_api(document, "CandidatePage")
    return document


def all_candidates(browser: Browser, run_id: str) -> list[dict[str, Any]]:
    """逐頁走完簽章游標，並驗證 development_rank 嚴格遞增、無重無漏。"""
    rows: list[dict[str, Any]] = []
    cursor, pages = "", 0
    while True:
        document = candidate_page(browser, run_id, cursor, 2)
        rows.extend(document["items"])
        pages += 1
        cursor = document["next_cursor"] or ""
        if cursor == "":
            break
        check(pages < 32, "Candidate pagination did not terminate")
    ranks = [row["development_rank"] for row in rows]
    check(ranks == sorted(ranks) and len(set(ranks)) == len(ranks), f"Candidate ranks not strictly ordered: {ranks}")
    return rows


def wait_fit(browser: Browser, run_id: str, total: int, seconds: float = 180.0) -> list[dict[str, Any]]:
    """輪詢候選投影直到每個 FIT 都 SUCCEEDED；INVALID 立即中止，逾時視為未收斂。"""
    deadline = time.monotonic() + seconds
    rows: list[dict[str, Any]] = []
    while time.monotonic() < deadline:
        rows = all_candidates(browser, run_id)
        states = [row["validation_status"] for row in rows]
        check("INVALID" not in states, f"FIT marked a candidate INVALID: {states}")
        if len(rows) == total and states and all(state == "FINISHED" for state in states):
            return rows
        time.sleep(0.5)
    raise CommandError(f"FIT did not converge for {run_id}: {[row['validation_status'] for row in rows]}")


def prepare_chain(browser: Browser, rows: int = 10) -> PreparedChain:
    """跑完 M3 前兩階段：真實 INGEST 落成不可變資料版本，再封印 PROFILE 讓版本 READY 並附證據包。

    需要真實資料版本與已封印研究的命令（例如壓測）共用此段，避免各自複製鏈路語意。"""
    status, dataset = browser.post("/api/v2/datasets", {"name": "m3-e2e-chain"})
    check(status == 201, "Dataset rejected")
    content = synthetic_rows(rows)
    checksum, ingest = upload(browser, dataset["id"], content, "CSV")
    check(ingest["status"] == "SUCCEEDED", "Actual INGEST failed")
    versions = read_json(browser, f'/api/v2/datasets/{dataset["id"]}/versions')
    version = next(row for row in versions["items"] if row["sha256"] == checksum)
    # 語意確認與研究：draft 只認固定切分，封印 PROFILE 後才 READY 並附證據包。
    status, research = browser.post("/api/v2/researches", {"name": "m3-e2e"})
    check(status == 201, "Research rejected")
    status, draft = browser.post(f'/api/v2/researches/{research["id"]}/versions', chain_configuration(version["id"], rows))
    check(status == 201 and draft["status"] == "DRAFT", "Semantic confirmation draft rejected")
    detail = f'/api/v2/research-versions/{draft["id"]}'
    headers = {"Content-Type": "application/json", "Idempotency-Key": "m3-e2e-profile", "If-Control-Revision": str(draft["revision"])}
    status, raw = browser.request(detail + "/validate", "POST", b"{}", headers)
    check(status == 202, f"Sealed PROFILE was not queued: {status}")
    profile_run = wait_run(browser, json.loads(raw)["id"])
    check(profile_run["status"] == "SUCCEEDED", "Sealed PROFILE did not succeed")
    ready = read_json(browser, detail)
    check(ready["status"] == "READY" and ready["observation_split"]["sealed_test_id"] is not None, "Version not sealed READY")
    check(len(ready["evidence_bundle_ids"]) == 1, "READY without exactly one evidence bundle")
    bundle_id = ready["evidence_bundle_ids"][0]
    seeded_bundle = read_json(browser, f"/api/v2/evidence-bundles/{bundle_id}")
    check(seeded_bundle["status"] == "ACTIVE", "Evidence bundle not ACTIVE after sealing")
    return PreparedChain(
        dataset_id=str(dataset["id"]), dataset_version_id=str(version["id"]), ingest_run_id=str(ingest["id"]),
        research_id=str(research["id"]), research_version_id=str(draft["id"]), profile_run_id=str(profile_run["id"]),
        sealed_test_registered=ready["observation_split"]["sealed_test_id"] is not None,
        evidence_bundle_id=str(bundle_id), sealed_bundle_revision=int(seeded_bundle["revision"]))


def run_chain(browser: Browser) -> ChainResult:
    """在已登入的瀏覽器上跑完 M3 七階段；每一站都先觀察權威終態才前進。"""
    prepared = prepare_chain(browser)
    dataset_id, version_id, bundle_id = prepared.dataset_id, prepared.research_version_id, prepared.evidence_bundle_id
    # 3. SEARCH：冪等入列、專用 queue 執行，帳本與預留各自收斂。
    runs_path = f'/api/v2/research-versions/{version_id}/runs'
    payload = json.dumps({"type": "SEARCH", "seed": 42}).encode()
    search_headers = {"Content-Type": "application/json", "Idempotency-Key": "m3-e2e-search", "If-Control-Revision": str(version_revision(browser, version_id))}
    status, raw = browser.request(runs_path, "POST", payload, search_headers)
    check(status == 202, f"SEARCH enqueue rejected: {status}")
    queued = json.loads(raw)
    status, replay = browser.request(runs_path, "POST", payload, search_headers)
    check(status == 202 and json.loads(replay) == queued, "SEARCH idempotency replay differs")
    search = wait_run(browser, queued["id"])
    check(search["status"] == "SUCCEEDED" and search["phase"] == "SEARCHING", "SEARCH worker failed")
    search_root = RootBudget.objects.get(run_id=UUID(search["id"]))
    research_account = ResearchBudget.objects.get(research_version_id=UUID(version_id))
    check(search_root.document["status"] == "CLOSED" and research_account.document["status"] == "CLOSING", "Search settlement boundary differs")
    check(Reservation.objects.get(root=search_root).state == "RELEASED", "Reservation retained after SEARCH")
    # 4. 候選比較：簽章游標穩定分頁，候選數與帳本一致，FIT 尚未宣告完成。
    accepted = int(search["budget_usage"]["candidates_accepted"])
    rows = all_candidates(browser, search["id"])
    check(len(rows) == accepted and len(rows) > 0, "Candidate count differs from SEARCH ledger")
    check(all(row["validation_status"] != "INVALID" for row in rows), "Candidate invalidated before comparison")
    # 5. FIT：專用佇列隔離重算，逐候選落 FIT／DEVELOPMENT 兩筆不可變結果。
    fitted = wait_fit(browser, search["id"], len(rows))
    first = fitted[0]
    check(len(first["fit_run_ids"]) == 1 and len(first["validation_run_ids"]) == 2, "Candidate did not record one FIT and two results")
    fit_row = FitRun.objects.get(pk=UUID(str(first["fit_run_ids"][0])))
    check(fit_row.run.document["status"] == "SUCCEEDED", "FIT root did not succeed")
    fit_budget = RootBudget.objects.get(run_id=fit_row.run_id)
    check(fit_budget.document["status"] == "CLOSED", "FIT root budget not settled")
    check(ValidationRun.objects.filter(run_id=fit_row.run_id, split_role="FIT").count() == 1, "FIT validation result missing")
    roles: list[str] = []
    scores: list[dict[str, object]] = []
    for validation_id in first["validation_run_ids"]:
        document = read_json(browser, f"/api/v2/validation-runs/{validation_id}")
        roles.append(str(document["split_role"]))
        scores.append({"split_role": str(document["split_role"]), "mae": document["metrics"]["mae"], "rmse": document["metrics"]["rmse"]})
    check(sorted(roles) == ["DEVELOPMENT", "FIT"], f"Validation split roles differ: {roles}")
    compared = read_json(browser, f'/api/v2/fit-runs/{first["fit_run_ids"][0]}')
    check(compared["split_role"] == "FIT" and compared["equation_version_id"] == first["equation_version_id"], "FIT readback differs from candidate")
    read_json(browser, f'/api/v2/equation-versions/{first["equation_version_id"]}')
    second = read_json(browser, f'/api/v2/fit-runs/{fitted[1]["fit_run_ids"][0]}') if len(fitted) > 1 else None
    # 6. 證據檢視：封存證據包與其證明產物在 FIT 完成後仍可讀且未變形。
    final_bundle = read_json(browser, f"/api/v2/evidence-bundles/{bundle_id}")
    check(final_bundle["status"] == "ACTIVE" and final_bundle["revision"] == prepared.sealed_bundle_revision, "Evidence bundle changed after FIT")
    check(len(final_bundle["proof_artifact_ids"]) >= 2, "Evidence bundle lost its sealed proof artifacts")
    for artifact_id in final_bundle["proof_artifact_ids"]:
        read_json(browser, f"/api/v2/artifacts/{artifact_id}")
    research_account.refresh_from_db()
    return ChainResult(
        dataset_id=dataset_id, dataset_version_id=prepared.dataset_version_id, ingest_run_id=prepared.ingest_run_id,
        research_id=prepared.research_id, research_version_id=version_id, profile_run_id=prepared.profile_run_id,
        sealed_test_registered=prepared.sealed_test_registered,
        evidence_bundle_id=bundle_id, search_run_id=str(search["id"]), fit_run_id=str(first["fit_run_ids"][0]),
        equation_version_id=str(first["equation_version_id"]),
        validation_run_ids=tuple(str(value) for value in first["validation_run_ids"]),
        validation_split_roles=tuple(roles), validation_scores=tuple(scores),
        candidate_count=len(rows), candidate_ranks=tuple(int(row["development_rank"]) for row in rows),
        second_candidate_compared=second is not None, evidence_proof_count=len(final_bundle["proof_artifact_ids"]),
        search_root_budget_status=str(search_root.document["status"]), fit_root_budget_status=str(fit_budget.document["status"]),
        research_budget_status=str(research_account.document["status"]),
        remaining_candidates=Candidate.objects.filter(search_run_id=UUID(search["id"])).count())


class Command(BaseCommand):
    help = "Exercise the M3 chain end to end over real HTTP: upload, semantic confirmation, research, SEARCH, candidate comparison, FIT and evidence reads"

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--frontend", action="store_true")

    def handle(self, *args: Any, **options: Any) -> None:
        password = secrets.token_urlsafe(24)
        user = User.objects.create_user(username="m3-e2e-" + uuid4().hex, password=password)
        account = Account.objects.create(user=user, tenant=Tenant.objects.create(name="m3-e2e-synthetic"))
        browser = Browser(FRONTEND_BASE if options["frontend"] else BASE)
        browser.login(user.get_username(), password)
        result = run_chain(browser)
        self.stdout.write(json.dumps({"scope": "M3_END_TO_END", "status": "PASS", "via_frontend": bool(options["frontend"]),
            "dataset_id": result.dataset_id, "dataset_version_id": result.dataset_version_id, "ingest_run_id": result.ingest_run_id,
            "semantic_source_mapping": "PASS", "research_version_id": result.research_version_id, "profile_run_id": result.profile_run_id,
            "sealed_test_registered": result.sealed_test_registered, "search_run_id": result.search_run_id, "candidate_count": result.candidate_count,
            "candidate_ranks": list(result.candidate_ranks), "fit_run_id": result.fit_run_id,
            "validation_split_roles": list(result.validation_split_roles), "validation_scores": list(result.validation_scores),
            "second_candidate_compared": result.second_candidate_compared, "evidence_bundle_id": result.evidence_bundle_id,
            "evidence_proof_count": result.evidence_proof_count, "search_root_budget_status": result.search_root_budget_status,
            "fit_root_budget_status": result.fit_root_budget_status, "research_budget_status": result.research_budget_status,
            "remaining_candidates": result.remaining_candidates, "account_tenant": str(account.tenant_id),
            "product_gate_status": "NOT_RUN"}, indent=2))
