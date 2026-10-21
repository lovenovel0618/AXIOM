"""Linux-only process resource boundary with bounded output and group cleanup."""
import hashlib
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import tempfile
import time
from typing import Any
from ingestion.limits import ImportLimits, ImportRejected, INVALID, LIMIT_CODE, require

MAX_INPUT = 50 * 1024 * 1024
MAX_OUTPUT = 512 * 1024
DEPENDENCY = "DEPENDENCY_UNAVAILABLE"
CODES = frozenset({INVALID, LIMIT_CODE, "UNSUPPORTED_MEDIA_TYPE"})


def terminate_group(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait(timeout=5)


def collect_output(process: subprocess.Popen[bytes], seconds: int) -> bytes:
    if process.stdout is None:
        raise ImportRejected(DEPENDENCY)
    output = bytearray()
    deadline = time.monotonic() + seconds
    with selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ)
        while True:
            remaining = deadline - time.monotonic()
            require(remaining > 0, LIMIT_CODE)
            if not selector.select(timeout=remaining):
                raise ImportRejected(LIMIT_CODE)
            block = os.read(process.stdout.fileno(), min(4096, MAX_OUTPUT - len(output) + 1))
            if not block:
                break
            output.extend(block)
            require(len(output) <= MAX_OUTPUT, LIMIT_CODE)
    try:
        code = process.wait(timeout=max(0.001, deadline - time.monotonic()))
    except subprocess.TimeoutExpired as error:
        raise ImportRejected(LIMIT_CODE) from error
    if code < 0 and -code in {signal.SIGKILL, signal.SIGXCPU}:
        raise ImportRejected(LIMIT_CODE)
    require(code == 0, DEPENDENCY)
    return bytes(output)


def _run(directory: Path, format_name: str, limits: ImportLimits, *, research: bool = False) -> bytes:
    worker = Path(__file__).with_name("research_worker.py" if research else "worker.py").resolve()
    environment = {"POLARS_MAX_THREADS": "1", "LANG": "C.UTF-8"}
    with subprocess.Popen([sys.executable, "-I", "-B", str(worker), format_name, json.dumps(limits.document())],
                          cwd=directory, env=environment, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL, start_new_session=True) as process:
        try:
            return collect_output(process, limits.max_parse_seconds)
        finally:
            terminate_group(process)


def decode_result(raw: bytes, limits: ImportLimits) -> dict[str, Any]:
    try:
        result: dict[str, Any] = json.loads(raw)
        require(type(result) is dict, DEPENDENCY)
        if result.get("status") == "REJECTED":
            code = result.get("code")
            if not isinstance(code, str) or code not in CODES:
                raise ImportRejected(DEPENDENCY)
            raise ImportRejected(code)
        require(set(result) == {"status", "metadata"} and result["status"] == "PASS", DEPENDENCY)
        metadata: dict[str, Any] = result["metadata"]
        require(set(metadata) == {"row_count", "columns"}, DEPENDENCY)
        rows, columns = metadata["row_count"], metadata["columns"]
        require(type(rows) is int and 0 <= rows <= limits.max_rows, DEPENDENCY)
        require(type(columns) is list and 1 <= len(columns) <= limits.max_columns, DEPENDENCY)
        _columns(columns)
        return metadata
    except (ValueError, TypeError, KeyError) as error:
        if isinstance(error, ImportRejected):
            raise
        raise ImportRejected(DEPENDENCY) from error


def _columns(columns: list[dict[str, Any]]) -> None:
    seen: set[str] = set()
    for column in columns:
        require(set(column) == {"name", "physical_type"}, DEPENDENCY)
        name, dtype = column["name"], column["physical_type"]
        require(isinstance(name, str) and 1 <= len(name) <= 256 and name not in seen, DEPENDENCY)
        require(isinstance(dtype, str) and 1 <= len(dtype) <= 128, DEPENDENCY)
        seen.add(name)


def inspect_bytes(content: bytes, format_name: str, limits: ImportLimits) -> dict[str, Any]:
    require(sys.platform == "linux", DEPENDENCY)
    require(1 <= len(content) <= MAX_INPUT, LIMIT_CODE)
    require(format_name in {"CSV", "JSON", "PARQUET"}, "UNSUPPORTED_MEDIA_TYPE")
    with tempfile.TemporaryDirectory(prefix="axiom-import-") as temporary:
        directory = Path(temporary)
        path = directory / "input"
        path.write_bytes(content)
        path.chmod(0o400)
        raw = _run(directory, format_name, limits)
    return {"scope": "T07_METADATA_ONLY_PREVIEW", "source_sha256": hashlib.sha256(content).hexdigest(),
            "format": format_name, "limits": limits.document(), "metadata": decode_result(raw, limits)}


def inspect_research(content: bytes, format_name: str, limits: ImportLimits, config: dict[str, Any]) -> dict[str, Any]:
    from ingestion.research import MAX_ROWS, model_for
    from ingestion.research_protocol import decode_report
    from runtime.contracts import canonical_bytes
    require(sys.platform == "linux", DEPENDENCY)
    require(1 <= len(content) <= MAX_INPUT, LIMIT_CODE)
    require(format_name in {"CSV", "JSON", "PARQUET"}, "UNSUPPORTED_MEDIA_TYPE")
    require(config["metadata"]["row_count"] <= min(MAX_ROWS, limits.max_rows), LIMIT_CODE)
    model_for(config)
    request = canonical_bytes(config)
    require(len(request) <= MAX_OUTPUT, LIMIT_CODE)
    with tempfile.TemporaryDirectory(prefix="axiom-research-") as temporary:
        directory = Path(temporary)
        for name, value in (("input", content), ("request", request)):
            path = directory / name
            path.write_bytes(value)
            path.chmod(0o400)
        raw = _run(directory, format_name, limits, research=True)
    return decode_report(raw, config)
