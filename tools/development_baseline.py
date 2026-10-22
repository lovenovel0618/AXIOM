"""Validate the T01 development baseline without approving milestones or decisions."""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, field
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any, cast

from jsonschema import Draft202012Validator
from jsonschema.protocols import Validator
from jsonschema.exceptions import SchemaError

# Any is confined to schema-validated JSON records.
JsonObject = dict[str, Any]
REPOSITORY = Path(__file__).resolve().parents[1]
PLAN = "docs/企劃案/"
TECHNICAL = "docs/技術文件/M0/"
BASELINE_PATH = TECHNICAL + "t01-baseline.json"
SCHEMA_PATH = TECHNICAL + "t01-baseline.schema.json"
WBS_PATH = PLAN + "11-交付/31-工作拆解WBS與依賴.md"
DECISIONS_PATH = PLAN + "12-附錄/37-決策待確認清單.md"
MATRIX_PATH = PLAN + "13-專題深化/46-驗收矩陣與交付證據.md"
SOURCE_PATHS = {
    PLAN + "01-需求/02-需求規格與使用情境.md",
    PLAN + "11-交付/30-里程碑與分階段開發計畫.md",
    WBS_PATH, DECISIONS_PATH, MATRIX_PATH,
    PLAN + "15-工程/53-工程治理與開發者工作流.md",
    PLAN + "contracts/capability-registry-v1.json",
    PLAN + "contracts/policy-registry-v1.json",
}
FUTURE_REQUIREMENTS = {"REQ-004", "REQ-005", "REQ-006", "REQ-007", "REQ-008", "REQ-014"}
REQUIREMENT_IDS = {f"REQ-{n:03d}" for n in range(1, 15)} | {f"NFR-{n:03d}" for n in range(1, 8)}
DEPENDENCIES: dict[str, set[str]] = {
    "T01": set(), "T02": {"T01"}, "T03": {"T01"}, "T04": {"T02"},
    "T05": {"T04"}, "T06": {"T02", "T03"}, "T07": {"T05", "T06"}, "T08": {"T07"},
}


@dataclass
class Report:
    validation_status: str = "FAIL"
    m0_ready: bool = False
    development_mode: str | None = None
    review_method: str | None = None
    product_status: str = "NOT_RUN"
    requirements: int = 0
    decisions: int = 0
    tickets: int = 0
    errors: list[str] = field(default_factory=list[str])
    blockers: list[str] = field(default_factory=list[str])


def unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key: " + key)
        result[key] = value
    return result


def finite_float(raw: str) -> float:
    number = float(raw)
    if not math.isfinite(number):
        raise ValueError("Non-finite JSON number")
    return number


def reject_constant(_raw: str) -> object:
    raise ValueError("Non-standard JSON constant")


def read_object(path: Path) -> JsonObject:
    value: object = json.loads(
        path.read_text(encoding="utf-8"), object_pairs_hook=unique_pairs,
        parse_float=finite_float, parse_constant=reject_constant,
    )
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object")
    return cast(JsonObject, value)


def contained_path(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve()
    if not candidate.is_relative_to(root.resolve()):
        raise ValueError("Source path escapes repository: " + relative)
    return candidate


def table_rows(path: Path, identifier_pattern: str) -> dict[str, list[str]]:
    rows: dict[str, list[str]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.split("|")[1:-1]]
        if not cells or not cells[0]:
            continue
        identifier = cells[0].split()[0]
        if re.fullmatch(identifier_pattern, identifier):
            if identifier in rows:
                raise ValueError("Duplicate authority row: " + identifier)
            rows[identifier] = cells
    return rows


def index_records(records: list[JsonObject], expected: set[str], label: str) -> dict[str, JsonObject]:
    indexed = {str(row["id"]): row for row in records}
    if len(indexed) != len(records) or set(indexed) != expected:
        raise ValueError("Duplicate or incomplete " + label)
    return indexed


def check_sources(root: Path, records: list[JsonObject]) -> None:
    paths = [str(row["path"]) for row in records]
    if len(set(paths)) != len(paths) or set(paths) != SOURCE_PATHS:
        raise ValueError("Duplicate or incomplete authority sources")
    for row in records:
        source = contained_path(root, row["path"])
        actual = hashlib.sha256(source.read_bytes()).hexdigest()
        if actual != row["sha256"]:
            raise ValueError("Authority hash changed; review baseline: " + row["path"])


def check_requirements(root: Path, records: list[JsonObject]) -> None:
    indexed = index_records(records, REQUIREMENT_IDS, "requirements")
    authority = table_rows(contained_path(root, MATRIX_PATH), r"(?:REQ|NFR)-\d{3}")
    if set(authority) != REQUIREMENT_IDS:
        raise ValueError("Authority requirement coverage changed")
    for identifier, row in indexed.items():
        expected = dict(zip(("delivery", "documents", "acceptance", "gates"), authority[identifier][1:5]))
        if any(row[key] != value for key, value in expected.items()):
            raise ValueError("Requirement trace drift: " + identifier)
        scope = "FUTURE" if identifier in FUTURE_REQUIREMENTS else "MVP_BASELINE"
        if row["scope"] != scope:
            raise ValueError("MVP scope drift: " + identifier)


def check_decisions(root: Path, records: list[JsonObject]) -> list[str]:
    indexed = index_records(records, {f"D-{n:02d}" for n in range(1, 10)}, "decisions")
    authority = table_rows(contained_path(root, DECISIONS_PATH), r"D-\d{2}")
    for identifier, row in indexed.items():
        expected = dict(zip(("description", "owner_role", "deadline", "restriction"), authority[identifier][1:5]))
        if any(row[key] != value for key, value in expected.items()):
            raise ValueError("Decision authority drift: " + identifier)
    return [f"{identifier}: OPEN; {row['deadline']}" for identifier, row in indexed.items()]


def check_graph(graph: dict[str, set[str]]) -> None:
    remaining = {key: set(value) for key, value in graph.items()}
    if any(deps.difference(graph) for deps in remaining.values()):
        raise ValueError("Unknown ticket dependency")
    while remaining:
        ready = {key for key, deps in remaining.items() if not deps}
        if not ready:
            raise ValueError("Cyclic ticket dependencies")
        remaining = {key: deps - ready for key, deps in remaining.items() if key not in ready}


def check_solo_assignment(row: JsonObject, developer_id: str) -> None:
    identifier = str(row["id"])
    for role in ("owner", "reviewer"):
        name = str(row[role])
        if name != name.strip():
            raise ValueError("Assignment name has surrounding whitespace: " + identifier)
        if name != developer_id:
            raise ValueError("SOLO ticket must use the project developer: " + identifier)


def check_ticket(row: JsonObject, authority: list[str], developer_id: str) -> None:
    identifier = str(row["id"])
    if row["summary"] != authority[1] or row["deliverable"] != authority[3]:
        raise ValueError("Ticket authority drift: " + identifier)
    if set(row["depends_on"]) != DEPENDENCIES[identifier]:
        raise ValueError("Required ticket dependencies changed: " + identifier)
    expected_status = "IN_PROGRESS" if identifier == "T01" else "NOT_STARTED"
    if row["status"] != expected_status:
        raise ValueError("Ticket progress requires a separate delivery review: " + identifier)
    check_solo_assignment(row, developer_id)


def check_tickets(root: Path, records: list[JsonObject], developer_id: str) -> None:
    if developer_id != developer_id.strip():
        raise ValueError("Developer ID has surrounding whitespace")
    indexed = index_records(records, set(DEPENDENCIES), "tickets")
    authority = table_rows(contained_path(root, WBS_PATH), r"T\d{2}")
    graph = {identifier: set(row["depends_on"]) for identifier, row in indexed.items()}
    check_graph(graph)
    for identifier, row in indexed.items():
        check_ticket(row, authority[identifier], developer_id)


def validate_baseline(root: Path, baseline_path: Path) -> Report:
    report = Report()
    try:
        baseline = read_object(baseline_path)
        schema = read_object(root / SCHEMA_PATH)
        Draft202012Validator.check_schema(schema)
        validator = cast(Validator, Draft202012Validator(schema))
        report.errors = [f"{error.json_path}: {error.message}" for error in validator.iter_errors(baseline)]
        if report.errors:
            return report
        check_sources(root, baseline["sources"])
        check_requirements(root, baseline["requirements"])
        report.blockers = check_decisions(root, baseline["decisions"])
        check_tickets(root, baseline["tickets"], baseline["development"]["developer_id"])
        report.development_mode = baseline["development"]["mode"]
        report.review_method = baseline["development"]["review_method"]
        report.blockers.append("M0 closure requires decision evidence and remaining deliveries; SOLO development may continue")
        report.requirements = len(baseline["requirements"])
        report.decisions = len(baseline["decisions"])
        report.tickets = len(baseline["tickets"])
        report.validation_status = "PASS"
    except SchemaError:
        report.errors.append("SchemaError: Invalid baseline schema")
    except (OSError, ValueError, KeyError, IndexError, RecursionError) as error:
        report.errors.append(f"{type(error).__name__}: {error}")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, default=REPOSITORY / BASELINE_PATH)
    parser.add_argument("--require-m0-ready", action="store_true")
    args = parser.parse_args()
    report = validate_baseline(REPOSITORY, args.baseline)
    print(json.dumps(asdict(report), ensure_ascii=False, indent=2))
    if report.validation_status != "PASS":
        return 1
    return 2 if args.require_m0_ready and not report.m0_ready else 0


if __name__ == "__main__":
    raise SystemExit(main())
