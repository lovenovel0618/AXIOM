"""每族搜尋的 Linux 隔離程序：固定程式、CPU／記憶體／輸出與 wall 上限，退出後才回傳。"""
from fractions import Fraction
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from ingestion.limits import ImportRejected, require
from ingestion.supervisor import collect_output, terminate_group
from mathematics.search import Request, Variable, Domain


def request_for(document: dict[str, object], projection: dict[str, object]) -> Request:
    """投影已經 child 白名單驗證；搜尋介面只攜 fit/development，沒有 final partition。"""
    research = json.loads(json.dumps(document))
    rows = json.loads(json.dumps(projection))
    variable = research["semantic_profile"]["inputs"][0]
    domain = research["domain"][0]
    def bound(name: str) -> Fraction:
        value = domain[name]
        return Fraction(int(value["numerator"]), int(value["denominator"]))
    return Request(Variable(variable["name"], tuple(variable["unit"])), tuple(research["semantic_profile"]["target"]["unit"]),
        Domain(bound("lower"), bound("upper"), domain["lower_closed"], domain["upper_closed"]),
        tuple((float(row[0]), float(row[1])) for row in rows["fit"]),
        tuple((float(row[0]), float(row[1])) for row in rows["development"]))


def run_strategy(document: dict[str, object], projection: dict[str, object], index: int, seconds: int) -> dict[str, object]:
    """程序群必須已 wait/reap 才離開；不能將逾時當成零成本。"""
    require(sys.platform == "linux", "DEPENDENCY_UNAVAILABLE")
    with TemporaryDirectory(prefix="axiom-search-") as temporary:
        directory = Path(temporary)
        # 不傳整份版本（內含 final row IDs），只傳搜尋所需的宣告及投影。
        research = {key: document[key] for key in ("semantic_profile", "domain")}
        (directory / "request").write_text(json.dumps({"research": research, "projection": projection, "index": index}))
        worker = Path(__file__).with_name("search_worker.py").resolve()
        with subprocess.Popen([sys.executable, "-I", "-B", str(worker), str(seconds)], cwd=directory,
                              env={"LANG": "C.UTF-8"}, stdin=subprocess.DEVNULL,
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, start_new_session=True) as process:
            try:
                raw = collect_output(process, seconds)
            finally:
                terminate_group(process)
    try:
        report = json.loads(raw)
        require(type(report) is dict and set(report) == {"policy_version", "usage_scope", "product_status", "precision_bits", "fit_rows", "development_rows", "proposed_count", "duplicate_count", "strategies", "candidates", "diagnostics"}, "DEPENDENCY_UNAVAILABLE")
        return report
    except (ValueError, TypeError) as error:
        raise ImportRejected("DEPENDENCY_UNAVAILABLE") from error
