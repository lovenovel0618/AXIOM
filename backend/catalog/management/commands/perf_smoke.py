"""M3 非功能壓測：以真實迴環 HTTP 量測 AX-45 的互動延遲與背景吞吐，只產生量測值。

依 AX-45 的場景與量測口徑，量測列表延遲、研究提交延遲、進度延遲與佇列等待，並強制附上
環境指紋、資料 hash、負載腳本版本與並發模型。核心拒絕以單機結果宣稱生產容量：本命令未達
規格要求的預熱／量測窗口與重複次數，且 D-06 尚未凍結錯誤率門檻，故只報測量值，
`g7_status` 固定 `BLOCKED`、`nfr_001_status` 固定 `NOT_RUN`。
"""
from argparse import ArgumentParser
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import os
import platform
import secrets
import threading
import time
from typing import Any
from uuid import uuid4
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from catalog.ingest_manifest import environment
from catalog.management.commands.catalog_smoke import BASE, Browser, FRONTEND_BASE
from catalog.management.commands.m3_e2e_smoke import prepare_chain, read_json, synthetic_rows, version_revision
from catalog.models import Account, Tenant
from catalog.validation import validate_api
from runtime.contracts import JsonObject

SCRIPT_VERSION = "perf-smoke-v1"
TERMINAL = {"SUCCEEDED", "FAILED", "CANCELLED"}
# 負載單元占比：20 個一循環即 80% 輕查詢、15% 資料上傳、5% 研究提交（AX-45 補充規格 1）。
MIX = ("QUERY",) * 16 + ("UPLOAD",) * 3 + ("SUBMIT",)
UPLOAD_BYTES = b"x,y\n1,3\n2,5\n"


def percentile(values: list[float], fraction: float) -> float | None:
    """最近秩法：排序後取第 ceil(p × n) 個樣本，不做插值，避免小樣本被拉出假分位數。"""
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[max(0, math.ceil(fraction * len(ordered)) - 1)], 3)


def series_summary(rows: list[dict[str, Any]]) -> JsonObject:
    """單一序列的成功延遲分位數、冷熱快取與錯誤分布；逾時與非 2xx 一律另計。"""
    good = [float(row["ms"]) for row in rows if row["outcome"] == "OK"]
    cold = [float(row["ms"]) for row in rows if row["outcome"] == "OK" and row["cache"] == "COLD"]
    warm = [float(row["ms"]) for row in rows if row["outcome"] == "OK" and row["cache"] == "WARM"]
    outcomes: dict[str, int] = {}
    for row in rows:
        outcomes[str(row["outcome"])] = outcomes.get(str(row["outcome"]), 0) + 1
    return {
        "samples": len(rows), "outcomes": outcomes,
        "error_rate": round((len(rows) - len(good)) / len(rows), 6) if rows else None,
        "timeout_count": outcomes.get("TIMEOUT", 0),
        "p50_ms": percentile(good, 0.50), "p95_ms": percentile(good, 0.95), "p99_ms": percentile(good, 0.99),
        "max_ms": round(max(good), 3) if good else None,
        "cold_samples": len(cold), "cold_p95_ms": percentile(cold, 0.95),
        "warm_samples": len(warm), "warm_p95_ms": percentile(warm, 0.95),
    }


class Evidence:
    """執行緒安全地收集樣本、回復 id 與工作層失敗；不讓任何單一請求掩蓋整體分布。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._samples: dict[str, list[dict[str, Any]]] = {}
        self._seen: set[str] = set()
        self._run_ids: set[str] = set()
        self._failures: list[str] = []

    def record(self, series: str, outcome: str, elapsed_ms: float, path: str) -> None:
        with self._lock:
            cache = "WARM" if path in self._seen else "COLD"
            self._seen.add(path)
            self._samples.setdefault(series, []).append({"outcome": outcome, "ms": elapsed_ms, "cache": cache})

    def remember_run(self, identity: str) -> None:
        with self._lock:
            self._run_ids.add(identity)

    def fail(self, message: str) -> None:
        with self._lock:
            self._failures.append(message)

    def report(self) -> JsonObject:
        with self._lock:
            return {
                "series": {name: series_summary(rows) for name, rows in sorted(self._samples.items())},
                "distinct_submitted_runs": len(self._run_ids),
                "worker_failures": list(self._failures),
            }


@dataclass(frozen=True)
class LoadPlan:
    """一輪壓測的固定輸入；所有工作層共用同一組權威資源與同一把冪等鍵。"""
    base: str
    username: str
    password: str
    dataset_id: str
    research_version_id: str
    runs_path: str
    revision: int
    idempotency_key: str
    payload: bytes
    run_id: str
    concurrency: int


def probe(browser: Browser, path: str, method: str = "GET", data: bytes | None = None,
          headers: dict[str, str] | None = None) -> tuple[str, float, int | None, bytes]:
    """量測單次 HTTP 往返；網路層失敗歸為 TIMEOUT，其餘狀態碼照實回報而不掩蓋。"""
    started = time.monotonic()
    try:
        status, raw = browser.request(path, method, data, headers)
    except OSError:
        return "TIMEOUT", (time.monotonic() - started) * 1000, None, b""
    return ("OK" if 200 <= status < 300 else f"HTTP_{status}"), (time.monotonic() - started) * 1000, status, raw


def load_units(total: int, concurrency: int) -> list[list[str]]:
    """以 80／15／5 排出固定順序的負載單元，再等分給每個併發客戶端以求可重現。"""
    plan = [MIX[index % len(MIX)] for index in range(total)]
    size = math.ceil(len(plan) / concurrency)
    return [plan[index * size:(index + 1) * size] for index in range(concurrency)]


def worker(plan: LoadPlan, units: list[str], evidence: Evidence, barrier: threading.Barrier) -> None:
    """單一併發客戶端：固定私人身分登入後依序送出負載單元，並量測每個互動端點延遲。"""
    browser = Browser(plan.base)
    try:
        browser.login(plan.username, plan.password)
    except CommandError as error:
        evidence.fail(f"login: {error}")
        return
    try:
        barrier.wait(timeout=60)
    except threading.BrokenBarrierError:
        pass
    for unit in units:
        if unit == "QUERY":
            path = "/api/v2/datasets"
            outcome, elapsed, _, _ = probe(browser, path)
            evidence.record("GET /api/v2/datasets", outcome, elapsed, path)
        elif unit == "UPLOAD":
            path = f"/api/v2/datasets/{plan.dataset_id}/uploads"
            body = json.dumps({"filename": "synthetic", "format": "CSV", "size_bytes": len(UPLOAD_BYTES),
                               "sha256": hashlib.sha256(UPLOAD_BYTES).hexdigest()}).encode()
            outcome, elapsed, status, raw = probe(browser, path, "POST", body,
                                                  {"Content-Type": "application/json", "Idempotency-Key": uuid4().hex})
            evidence.record("POST /api/v2/datasets/{id}/uploads", outcome, elapsed, path)
            if status != 201:
                continue
            # 只有真的建立 session 才續傳位元組，避免錯誤樣本產生假的 PUT 量測。
            try:
                session: JsonObject = json.loads(raw)
            except json.JSONDecodeError:
                evidence.fail("upload session body was not JSON")
                continue
            storage_path = "/storage/uploads/" + str(session["id"])
            put_outcome, put_elapsed, _, _ = probe(browser, storage_path, "PUT", UPLOAD_BYTES, session["required_headers"])
            evidence.record("PUT /storage/uploads/{id}", put_outcome, put_elapsed, storage_path)
        else:
            headers = {"Content-Type": "application/json", "Idempotency-Key": plan.idempotency_key,
                       "If-Control-Revision": str(plan.revision)}
            outcome, elapsed, status, raw = probe(browser, plan.runs_path, "POST", plan.payload, headers)
            evidence.record("POST /api/v2/research-versions/{id}/runs [REPLAY]", outcome, elapsed, plan.runs_path)
            if status != 202:
                continue
            try:
                replay: JsonObject = json.loads(raw)
            except json.JSONDecodeError:
                evidence.fail("research submission body was not JSON")
                continue
            evidence.remember_run(str(replay["id"]))


def watch_progress(plan: LoadPlan, seconds: float) -> JsonObject:
    """以伺服器宣告的 retry 節奏重連有界 SSE，量測事件產生到可見的延遲與遺漏／重複。

    事件與客戶端同在一台主機，因此 `occurred_at` 可直接對照；跨機時鐘未校正，
    若換到多主機部署此列必須重做，不得沿用。"""
    browser = Browser(plan.base)
    browser.login(plan.username, plan.password)
    cursor, retry_ms, reconnects = 0, 2000, 0
    delays: list[float] = []
    events: list[JsonObject] = []
    seen: set[int] = set()
    highest, lost, duplicates, malformed = 0, 0, 0, 0
    path = f"/api/v2/runs/{plan.run_id}/events"
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        status, raw = browser.request(path, headers={"Last-Event-ID": f"RUN:{plan.run_id}:{cursor}"})
        received = datetime.now(timezone.utc)
        reconnects += 1
        if status != 200:
            break
        batch = 0
        for line in raw.decode("utf-8", "replace").splitlines():
            if line.startswith("retry: "):
                retry_ms = int(line[7:])
                continue
            if not line.startswith("data: "):
                continue
            try:
                event: JsonObject = json.loads(line[6:])
            except json.JSONDecodeError:
                # 讀取上限可能截斷尾端事件；不推進游標，下一輪重新取得同一批。
                malformed += 1
                break
            sequence = int(event["sequence"])
            if sequence in seen:
                duplicates += 1
                continue
            if highest and sequence > highest + 1:
                lost += sequence - highest - 1
            seen.add(sequence)
            highest = max(highest, sequence)
            cursor = max(cursor, sequence)
            batch += 1
            occurred = datetime.fromisoformat(str(event["occurred_at"]))
            delays.append((received - occurred).total_seconds() * 1000)
            events.append(event)
        if batch == 0:
            time.sleep(retry_ms / 1000)
        state, raw = browser.request(f"/api/v2/runs/{plan.run_id}")
        if state != 200:
            break
        document: JsonObject = json.loads(raw)
        validate_api(document, "Run")
        drained = cursor >= int(str(document["current_event_cursor"]).rsplit(":", 1)[1])
        if document["status"] in TERMINAL and drained:
            break
    return {"delays_ms": delays, "events": events, "lost_events": lost, "duplicate_events": duplicates,
            "malformed_frames": malformed, "reconnects": reconnects, "server_retry_ms": retry_ms}


def run_timing(events: list[JsonObject]) -> JsonObject:
    """由不可變事件推導佇列等待與端到端時間；缺事件時據實標為未取得。"""
    def occurred(event_type: str) -> datetime | None:
        event = next((row for row in events if row["event_type"] == event_type), None)
        return None if event is None else datetime.fromisoformat(str(event["occurred_at"]))

    queued, started, finished = occurred("RunQueued"), occurred("RunStarted"), occurred("RunFinished")
    if queued is None:
        return {"queue_wait_ms": None, "run_wall_ms": None, "background_tasks_per_minute": None, "reason": "未取得佇列事件"}
    wall = None if finished is None else (finished - queued).total_seconds() * 1000
    return {
        "queue_wait_ms": None if started is None else round((started - queued).total_seconds() * 1000, 3),
        "run_wall_ms": None if wall is None else round(wall, 3),
        "background_tasks_per_minute": None if not wall else round(60000 / wall, 3),
    }


def machine_memory() -> int | str:
    """容器內的實體記憶體總量；讀不到時依 Fail-Closed 回未取得，不用推測數字。"""
    try:
        with open("/proc/meminfo", encoding="ascii") as handle:
            for line in handle:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) * 1024
    except OSError:
        pass
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (AttributeError, OSError, ValueError):
        return "未取得"


def environment_report(rows: int, content_sha256: str, requests: int, concurrency: int) -> JsonObject:
    """AX-45 量測口徑要求的必要欄位；無法取得者一律標未取得並附原因，嚴禁推測。"""
    return {
        "os": f"{platform.system()} {platform.release()}", "machine": platform.machine(),
        "python": platform.python_version(), "cpu_count": os.cpu_count(), "memory_bytes": machine_memory(),
        "gpu": "未取得", "gpu_reason": "執行環境未提供 GPU 探測能力，依 Fail-Closed 不推測",
        "container_image_digest": "未取得",
        "container_image_reason": "未注入映像 digest，改以 environment_digest 作為可比較指紋",
        "environment_digest": environment(),
        "data_rows": rows, "data_sha256": content_sha256,
        "load_script": SCRIPT_VERSION,
        "arrival_model": {"kind": "CLOSED_LOOP", "in_flight_requests": concurrency, "total_units": requests,
                          "mix": {"query": 0.80, "upload": 0.15, "submit": 0.05}},
        "clock_model": "SINGLE_HOST_WALL_CLOCK",
    }


class Command(BaseCommand):
    help = "Measure AX-45 interaction latency and background throughput over real loopback HTTP without claiming any gate"

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--frontend", action="store_true")
        parser.add_argument("--concurrency", type=int, default=20)
        parser.add_argument("--requests", type=int, default=600)
        parser.add_argument("--rows", type=int, default=100)

    def handle(self, *args: Any, **options: Any) -> None:
        concurrency, requests, rows = int(options["concurrency"]), int(options["requests"]), int(options["rows"])
        if concurrency < 1 or requests < 1 or rows < 10:
            raise CommandError("concurrency/requests 需為正整數，rows 至少 10 列以容納 60／20／20 切分")
        base = FRONTEND_BASE if options["frontend"] else BASE
        password = secrets.token_urlsafe(24)
        user = User.objects.create_user(username="perf-" + uuid4().hex, password=password)
        account = Account.objects.create(user=user, tenant=Tenant.objects.create(name="perf-synthetic"))
        browser = Browser(base)
        browser.login(user.get_username(), password)
        content = synthetic_rows(rows)
        prepared = prepare_chain(browser, rows)
        # 研究提交先做一次真實建立（冷），取得權威 run_id；其後負載只做冪等重送（熱）。
        runs_path = f"/api/v2/research-versions/{prepared.research_version_id}/runs"
        revision = version_revision(browser, prepared.research_version_id)
        idempotency_key = "perf-smoke-search"
        payload = json.dumps({"type": "SEARCH", "seed": 42}).encode()
        headers = {"Content-Type": "application/json", "Idempotency-Key": idempotency_key, "If-Control-Revision": str(revision)}
        evidence = Evidence()
        create_outcome, create_ms, create_status, raw = probe(browser, runs_path, "POST", payload, headers)
        evidence.record("POST /api/v2/research-versions/{id}/runs [CREATE]", create_outcome, create_ms, runs_path)
        if create_status != 202:
            raise CommandError(f"SEARCH enqueue rejected: {create_status}")
        run_id = str(json.loads(raw)["id"])
        plan = LoadPlan(base=base, username=user.get_username(), password=password, dataset_id=prepared.dataset_id,
                        research_version_id=prepared.research_version_id, runs_path=runs_path, revision=revision,
                        idempotency_key=idempotency_key, payload=payload, run_id=run_id, concurrency=concurrency)
        barrier = threading.Barrier(concurrency)
        started = time.monotonic()
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = [pool.submit(worker, plan, chunk, evidence, barrier) for chunk in load_units(requests, concurrency)]
            progress = watch_progress(plan, 900.0)
            for future in futures:
                future.result()
        elapsed = time.monotonic() - started
        try:
            document: JsonObject = read_json(browser, f"/api/v2/runs/{run_id}")
        except CommandError as error:
            raise CommandError(f"Submitted research run unreadable after the load: {error}")
        evidence.report()
        report = evidence.report()
        series = report["series"]
        if not isinstance(series, dict):
            raise CommandError("Evidence report malformed")
        results: dict[str, Any] = series
        unit_total = sum(int(row["samples"]) for row in results.values() if isinstance(row, dict))
        self.stdout.write(json.dumps({
            "scope": "M3_PERFORMANCE", "status": "PASS", "via_frontend": bool(options["frontend"]),
            "environment": environment_report(rows, hashlib.sha256(content).hexdigest(), requests, concurrency),
            "measurements": results,
            "units_completed": unit_total, "wall_seconds": round(elapsed, 3),
            "achieved_rps": round(unit_total / elapsed, 3) if elapsed else None,
            "progress_latency": {
                "events_seen": len(progress["delays_ms"]),
                "p50_ms": percentile(list(progress["delays_ms"]), 0.50),
                "p95_ms": percentile(list(progress["delays_ms"]), 0.95),
                "p99_ms": percentile(list(progress["delays_ms"]), 0.99),
                "lost_events": progress["lost_events"], "duplicate_events": progress["duplicate_events"],
                "malformed_frames": progress["malformed_frames"], "reconnects": progress["reconnects"],
                "server_retry_ms": progress["server_retry_ms"],
            },
            "run_timing": run_timing(progress["events"]),
            "submitted_run_id": run_id, "submitted_run_status": document["status"],
            "resubmit_created_one_run": report["distinct_submitted_runs"] == 1,
            "worker_failures": report["worker_failures"],
            "protocol": {
                "spec": "AX-45 執行程序：預熱 5 分鐘／量測 15 分鐘／至少 3 次獨立執行",
                "warmup_seconds": 0, "measure_seconds": round(elapsed, 3), "independent_runs": 1, "compliant": False,
                "reason": f"單機開發環境；以 {rows} 列確認腳本正確，容量規劃需另在目標硬體重跑",
            },
            "error_rate_threshold": None,
            "slo_verdict": "NOT_RUN",
            "slo_reason": "D-06 尚未凍結錯誤率／量測窗口／error budget，且協定未達規格要求，只報測量值",
            "g7_status": "BLOCKED", "nfr_001_status": "NOT_RUN",
            "account_tenant": str(account.tenant_id), "product_gate_status": "NOT_RUN",
        }, indent=2, ensure_ascii=False))
