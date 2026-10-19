"""Validate documentation, contract examples and public fixture oracles; no product tests."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import sys
from urllib.parse import unquote
from collections.abc import Iterator, Mapping
from typing import Any, TypeAlias, cast

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.protocols import Validator
from openapi_spec_validator import OpenAPIV31SpecValidator
from openapi_spec_validator.schemas.types import AnySchema
from referencing import Registry, Resource
from referencing.jsonschema import Schema, SchemaRegistry
sys.dont_write_bytecode = True
from contract_scenarios import check_scenarios

# JSON documents have schema-defined dynamic keys; keep Any at this data boundary.
JsonObject: TypeAlias = dict[str, Any]
ROOT = Path(__file__).resolve().parents[1]
MANIFEST_NAME = "MANIFEST.json"
DEFINITIONS_KEY = "$defs"
DSL_SCHEMA_NAME = "dsl-v1.schema.json"
RUNTIME_SCHEMA_NAME = "runtime-v2.schema.json"
RESEARCH_SCHEMA_NAME = "research-v2.schema.json"
DOC_VERSION = "v2.6"
RELEASE_MATRIX_GLOB = "46-*.md"
DECISION_LIST_GLOB = "37-*.md"
MATRIX_ONLY_CHAPTER = "AC-46-"
REQUIREMENT_COUNTS = {"REQ": 10, "NFR": 7}
ACCEPTANCE_PATTERN = r"(AC-\d{2}-)(\d{2})(?:～(\d{2}))?"
DECISION_PATTERN = r"D-\d{2}"


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def read_json(path: Path) -> JsonObject:
    value: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return cast(JsonObject, value)


def schema_validator(schema: JsonObject, registry: SchemaRegistry | None = None) -> Validator:
    """Expose jsonschema's typed protocol instead of its dynamically generated class."""
    return cast(Validator, Draft202012Validator(
        schema, registry=registry if registry is not None else Registry(),
        format_checker=FormatChecker(),
    ))


def tracked_files() -> list[Path]:
    return sorted(
        p for p in ROOT.rglob("*")
        if p.is_file() and p.suffix in {".md", ".json", ".py", ".txt"}
        and p.name != MANIFEST_NAME and "__pycache__" not in p.parts
    )


def manifest_data() -> JsonObject:
    files = tracked_files()
    return {
        "project": "AXIOM", "version": DOC_VERSION.removeprefix("v"), "created": "2026-10-20",
        "date": "2026-10-20", "documents": sum(p.suffix == ".md" for p in files),
        "file_count": len(files),
        "files": [{"path": str(p.relative_to(ROOT)), "bytes": p.stat().st_size,
                   "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in files],
    }


def markdown_prose(content: str, path: Path) -> str:
    """Separate fenced blocks in one pass, without backtracking regular expressions."""
    chunks: list[list[str]] = [[]]
    languages: list[str] = []
    in_code = False
    for line in content.splitlines(keepends=True):
        if line.startswith("```"):
            in_code = not in_code
            if in_code:
                languages.append(line[3:].strip())
            chunks.append([])
        else:
            chunks[-1].append(line)
    check(not in_code, f"Unclosed fence: {path}")
    for index, language in enumerate(languages):
        if language == "json":
            json.loads("".join(chunks[index * 2 + 1]))
    return "".join("".join(chunk) for chunk in chunks[::2])


def check_table_spacing(plain: str, path: Path) -> None:
    previous_table = False
    blank_after_table = False
    for line in plain.splitlines():
        if not line.strip():
            blank_after_table = previous_table or blank_after_table
            previous_table = False
            continue
        if blank_after_table and line.startswith("|"):
            raise AssertionError(f"Split table: {path}")
        previous_table = line.endswith("|")
        blank_after_table = False


def check_markdown_links(path: Path, plain: str) -> int:
    link_count = 0
    for match in re.finditer(r"\[[^\]\n]+\]\((?:<([^>]+)>|([^\s)]+))\)", plain):
        target = match[1] or match[2]
        if "://" in target or target.startswith("#"):
            continue
        local = unquote(target.split("#")[0])
        check((path.parent / local).is_file(), f"Broken link: {path}: {target}")
        link_count += 1
    return link_count


def acceptance_ids(plain: str) -> list[str]:
    identifiers: list[str] = []
    for line in plain.splitlines():
        if not line.startswith("| "):
            continue
        cell = line.split("|", 2)[1].strip()
        identifier = cell.split("/", 1)[0].split("／", 1)[0]
        if re.fullmatch(r"AC-\d{2}-\d{2}", identifier):
            identifiers.append(identifier)
    return identifiers


def check_markdown_document(path: Path, index: str) -> tuple[int | None, list[str], int]:
    chapter_id: int | None = None
    content = path.read_text()
    plain = markdown_prose(content, path)
    if path.name[:2].isdigit():
        number = int(path.name[:2])
        chapter_id = number
        check(f"文件 ID AX-{number:02d}" in content, f"Missing document ID: {path}")

    check("正常路徑**：給定完整合法的輸入" not in plain, f"Generic AC remains: {path}")
    check("A[前置資料與條件]" not in content, f"Generic workflow remains: {path}")
    check_table_spacing(plain, path)
    case_ids = acceptance_ids(plain)
    if path.name != "README.md":
        check(str(path.relative_to(ROOT)) in index, f"Missing from README: {path}")
    return chapter_id, case_ids, check_markdown_links(path, plain)


def check_document_header(path: Path) -> None:
    header = next((line for line in path.read_text(encoding="utf-8").splitlines()
                   if line.startswith(">")), "")
    check(DOC_VERSION in header, f"Stale document version header: {path}")


def acceptance_ranges(text: str) -> set[str]:
    covered: set[str] = set()
    for match in re.finditer(ACCEPTANCE_PATTERN, text):
        for n in range(int(match[2]), int(match[3] or match[2]) + 1):
            covered.add(match[1] + f"{n:02d}")
    return covered


def check_requirement_traces(case_ids: list[str]) -> None:
    trace = next(ROOT.rglob(RELEASE_MATRIX_GLOB)).read_text()
    for prefix, count in REQUIREMENT_COUNTS.items():
        for n in range(1, count + 1):
            check(f"| {prefix}-{n:03d} " in trace, f"Missing requirement mapping: {prefix}-{n:03d}")
    covered = acceptance_ranges(trace)
    for case_id in sorted(covered):
        check(case_id in case_ids, f"Undefined referenced test: {case_id}")
    for case_id in case_ids:
        if not case_id.startswith(MATRIX_ONLY_CHAPTER):
            check(case_id in covered, f"Acceptance case not traced in release matrix: {case_id}")


def check_decision_references() -> None:
    source = next(ROOT.rglob(DECISION_LIST_GLOB))
    defined = set(re.findall(DECISION_PATTERN, source.read_text(encoding="utf-8")))
    referenced: set[str] = set()
    for path in ROOT.rglob("*.md"):
        tokens = set(re.findall(DECISION_PATTERN, path.read_text(encoding="utf-8")))
        for token in tokens:
            check(token in defined, f"Undefined decision reference: {token} in {path}")
        if path != source:
            referenced |= tokens
    for decision in sorted(defined):
        check(decision in referenced, f"Decision lacks a blocking-document reference: {decision}")


def check_markdown() -> dict[str, int]:
    paths = sorted(ROOT.rglob("*.md"))
    chapter_ids: list[int] = []
    case_ids: list[str] = []
    link_count = 0
    index = (ROOT / "README.md").read_text()
    for path in paths:
        check_document_header(path)
        chapter_id, document_cases, links = check_markdown_document(path, index)
        if chapter_id is not None:
            chapter_ids.append(chapter_id)
        case_ids.extend(document_cases)
        link_count += links
    check(sorted(chapter_ids) == list(range(49)), "Chapter numbers must be unique AX-00..48")
    check(len(case_ids) == len(set(case_ids)), "Duplicate acceptance ID")
    check_requirement_traces(case_ids)
    check_decision_references()
    return {"markdown": len(paths), "chapters": len(chapter_ids), "links": link_count,
            "acceptance_cases": len(case_ids)}

def load_schemas(folder: Path) -> tuple[dict[str, JsonObject], SchemaRegistry]:
    schemas = {p.name: read_json(p) for p in folder.glob("*.schema.json")}
    registry: SchemaRegistry = Registry()
    for name, schema in schemas.items():
        Draft202012Validator.check_schema(schema)
        resource = Resource[Schema].from_contents(schema)
        registry = registry.with_resource(schema["$id"], resource)
        registry = registry.with_resource((folder / name).as_uri(), resource)
    return schemas, registry


def check_queued_usage(prefix: str, value: JsonObject) -> None:
    if prefix == "research-v2" and value.get("kind") == "Run" and value["status"] == "QUEUED":
        check(all(amount == 0 for amount in value["budget_usage"].values()), "Queued run usage must be zero")


def check_example_set(prefix: str, examples: JsonObject, validator: Validator) -> int:
    count = 0
    for value in examples["valid"]:
        validator.validate(value)
        check_queued_usage(prefix, value)
        count += 1
    for value in examples["invalid"]:
        check(not validator.is_valid(value["document"]), f"Invalid example accepted: {prefix}: {value['reason']}")
        count += 1
    # Structurally valid cases can still be rejected by the future semantic engine.
    for value in examples.get("semantic_invalid", []):
        validator.validate(value["document"])
        count += 1
    return count


def check_schema_examples(folder: Path, schemas: dict[str, JsonObject], registry: SchemaRegistry) -> int:
    count = 0
    for prefix in ["dsl-v1", "research-v2", "runtime-v2", "event-v2", "task-input-v2"]:
        validator = schema_validator(schemas[prefix + ".schema.json"], registry=registry)
        count += check_example_set(prefix, read_json(folder / (prefix + ".examples.json")), validator)
    return count


def bundled(value: Any, mapping: Mapping[str, str]) -> Any:
    if isinstance(value, dict):
        return {key: mapping.get(item, item) if key == "$ref" else bundled(item, mapping)
                for key, item in cast(JsonObject, value).items() if key not in {"$id", "$schema"}}
    if isinstance(value, list):
        return [bundled(item, mapping) for item in cast(list[Any], value)]
    return value


def check_bundled_schemas(schemas: dict[str, JsonObject], api: JsonObject) -> None:
    definitions = schemas[RESEARCH_SCHEMA_NAME][DEFINITIONS_KEY]
    mapping = {"#/$defs/" + name: "#/components/schemas/" + name for name in definitions}
    mapping[DSL_SCHEMA_NAME] = "#/components/schemas/DSL"
    for name, schema in definitions.items():
        check(api["components"]["schemas"][name] == bundled(schema, mapping),
              f"OpenAPI schema drift: {name}")
    dsl = schemas[DSL_SCHEMA_NAME]
    dsl_mapping = {"#/$defs/" + name: "#/components/schemas/DSL" + name for name in dsl[DEFINITIONS_KEY]}
    check(api["components"]["schemas"]["DSL"] == bundled({k: v for k, v in dsl.items() if k != DEFINITIONS_KEY}, dsl_mapping),
          "OpenAPI DSL envelope drift")
    for name, schema in dsl[DEFINITIONS_KEY].items():
        check(api["components"]["schemas"]["DSL" + name] == bundled(schema, dsl_mapping), "OpenAPI DSL node drift")
    check(api["components"]["schemas"]["Event"] == bundled(schemas["event-v2.schema.json"], {}),
          "OpenAPI event schema drift")


def check_equation_hashes(folder: Path) -> None:
    equation_examples = read_json(folder / "research-v2.examples.json")["valid"]
    for example in equation_examples:
        if example["kind"] == "EquationVersion":
            canonical = json.dumps(example["dsl"], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
            check(hashlib.sha256(canonical).hexdigest() == example["identity_hash"], "Public canonical hash drift")


def check_api_examples(folder: Path, api: JsonObject) -> int:
    count = 0
    api_examples = read_json(folder / "api-v2.examples.json")
    for polarity in ["valid", "invalid"]:
        for case in api_examples[polarity]:
            schema = {"$ref": "#/components/schemas/" + case["schema"], "components": api["components"]}
            ok = schema_validator(schema).is_valid(case["document"])
            check(ok == (polarity == "valid"), f"API example mismatch: {case['schema']}")
            count += 1
    return count


def check_operation_headers(path: str, method: str, operation: JsonObject) -> None:
    headers = {p["name"] for p in operation.get("parameters", []) if p.get("in") == "header"}
    check("If-Match" not in headers, "Business control revision must not masquerade as representation ETag")
    if method == "post" and any(path.endswith(suffix) for suffix in ["/validate", "/runs", "/cancel", "/reviews", "/revoke"]):
        check("If-Control-Revision" in headers, "Control precondition missing")


def check_api_operations(schemas: dict[str, JsonObject], api: JsonObject) -> None:
    doc = next(ROOT.rglob("21-*.md")).read_text()
    for path, item in api["paths"].items():
        for method in item:
            check(f"{method.upper()} {path}" in doc, f"Endpoint missing from AX-21: {method} {path}")
    event = schemas["event-v2.schema.json"]
    for event_type in event["properties"]["event_type"]["enum"]:
        check(event_type in doc, f"Undocumented event: {event_type}")
    # Reverse coverage catches navigation endpoints described in prose but missing in OpenAPI.
    documented = {(method.lower(), path) for method, path in re.findall(r"^\| (GET|POST|PUT|DELETE|PATCH) (/[^ |]+)", doc, re.M)}
    declared = {(method, path) for path, item in api["paths"].items() for method in item}
    check(documented == declared, f"Bidirectional endpoint drift: {documented ^ declared}")
    check(api["servers"] == [{"url": "/api/v2"}], "HTTP major version drift")


def check_api_headers(api: JsonObject) -> None:
    for path, item in api["paths"].items():
        for method, operation in item.items():
            check_operation_headers(path, method, operation)


def check_public_projection(definitions: JsonObject, runtime: JsonObject, api: JsonObject) -> None:
    for public_name, private_name in [("Run", "RunRecord"), ("Attempt", "AttemptRecord")]:
        public, private = definitions[public_name], runtime[private_name]
        check(set(public["required"]) <= set(private["required"]), "Internal DTO projection lost required fields")
        for key, value in public["properties"].items():
            if key != "kind":
                check(private["properties"].get(key) == value, f"Private/public shared field drift: {key}")
        check(private_name not in api["components"]["schemas"], "Private control record leaked into OpenAPI")


def check_scenario_context(suite: JsonObject, schemas: dict[str, JsonObject], registry: SchemaRegistry) -> None:
    for value in suite["context"].values():
        if isinstance(value, dict) and "kind" in value:
            profile = "runtime-v2" if value["kind"] in {"RunRecord", "AttemptRecord"} else "research-v2"
            schema_validator(schemas[profile + ".schema.json"], registry=registry).validate(cast(JsonObject, value))


def check_recovery_contracts(definitions: JsonObject, runtime: JsonObject, api: JsonObject, dsl: JsonObject) -> None:
    for field in ["evidence_bundle_ids", "review_ids", "quality_report_id"]:
        check(field in definitions["ResearchVersion"]["required"], "Snapshot recovery reference missing: " + field)
    check(api["paths"]["/review-decisions/{id}"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
          == {"$ref": "#/components/schemas/ReviewDecision"}, "Review history cannot be recovered")
    check(definitions["ReviewDecision"]["properties"]["decision"]["enum"] == ["APPROVE", "REJECT"], "Review enum drift")
    check("dispatch_stage" not in definitions["Run"]["properties"], "Private dispatch control leaked")
    check("outcome_status" in definitions["Run"]["required"] and "skipped_phases" in definitions["Run"]["required"],
          "Run outcome/skip projection missing")
    check("domain" in api["components"]["schemas"]["CreateResearchVersion"]["required"]
          and "domain" in definitions["ResearchVersion"]["required"], "Fixed research domain missing")
    check(definitions["ResearchDomain"] == {**dsl["properties"]["domain"], "maxItems": 1}, "Research/DSL domain shape drift")
    check("submission_id" in definitions["ValidationRun"]["required"], "Final result submission linkage missing")
    check("FinalEvaluationSlot" in runtime and "FinalEvaluationSlot" not in api["components"]["schemas"],
          "Final slot missing or leaked into HTTP")
    for path in ["/validation-runs/{id}", "/artifacts/{id}", "/artifacts/{id}/content",
                 "/evidence-bundles/{id}", "/published-artifacts/{id}"]:
        operation = api["paths"][path]["get"]
        check(operation.get("x-axiom-access-policy") == "artifact-class-and-lineage-v1"
              and "404" in operation["responses"], "Sealed-read endpoint policy missing: " + path)


def check_topology() -> None:
    topology = next(ROOT.rglob("06-*.md")).read_text()
    edges = re.findall(r"\b([A-Z][A-Z0-9]*)\s*-->\s*([A-Z][A-Z0-9]*)", topology)
    check(("SB", "OUT") in edges and ("ESB", "EV") in edges, "Controlled sandbox egress missing")
    check(all(dst not in {"DB", "PG", "OBJ"} for src, dst in edges if src in {"SB", "ESB", "W4"}),
          "Untrusted sandbox directly linked to storage")


def refs(value: object) -> Iterator[str]:
    if isinstance(value, dict):
        for key, item in cast(dict[str, object], value).items():
            if key == "$ref" and isinstance(item, str):
                yield item
            else:
                yield from refs(item)
    elif isinstance(value, list):
        for item in cast(list[object], value):
            yield from refs(item)


def check_local_schema_refs(folder: Path) -> None:
    for path in folder.glob("*.json"):
        for reference in refs(read_json(path)):
            if not reference.startswith("#"):
                check("://" not in reference, f"Unexpected network ref: {reference}")
                check((folder / reference.split("#")[0]).is_file(), f"Missing schema ref: {reference}")


def check_research_completion_contracts(schemas: dict[str, JsonObject], api: JsonObject) -> None:
    draft_revision = DOC_VERSION.removeprefix("v")
    for name in [RESEARCH_SCHEMA_NAME, RUNTIME_SCHEMA_NAME, "task-input-v2.schema.json"]:
        check(schemas[name]["x-axiom-draft-revision"] == draft_revision, "Draft schema revision drift")
    check(api["info"]["x-axiom-draft-revision"] == draft_revision, "Draft API revision drift")
    definitions = schemas[RESEARCH_SCHEMA_NAME][DEFINITIONS_KEY]
    profile = definitions["SemanticProfile"]["properties"]
    for column in [profile["inputs"]["items"], profile["target"]]:
        check("source_column" in column["required"], "Source-column binding missing")
    create_version = api["components"]["schemas"]["CreateResearchVersion"]
    check("evaluation_policy" in create_version["required"], "Evaluation policy input missing")
    for name in ["ValidationRun", "FrozenSubmission"]:
        check("evaluation_policy_hash" in definitions[name]["required"], "Policy reference missing")
    check("diagnostic_artifact_ids" in definitions["Run"]["required"], "Insufficient-result report missing")
    for name in ["ResearchBudgetAccount", "ExposureRecoveryState"]:
        check(name in schemas[RUNTIME_SCHEMA_NAME][DEFINITIONS_KEY], "Internal recovery/account schema missing")
        check(name not in api["components"]["schemas"], "Internal control record leaked into HTTP")


def check_contracts() -> dict[str, int]:
    folder = ROOT / "contracts"
    schemas, registry = load_schemas(folder)
    example_count = check_schema_examples(folder, schemas, registry)
    api = read_json(folder / "openapi-v2.json")
    # Upstream accepts Hashable-keyed mappings; JSON keys here are always strings.
    OpenAPIV31SpecValidator(cast(AnySchema, api)).validate()
    check_bundled_schemas(schemas, api)
    check_equation_hashes(folder)
    example_count += check_api_examples(folder, api)
    check_api_operations(schemas, api)
    check_api_headers(api)
    definitions = schemas[RESEARCH_SCHEMA_NAME][DEFINITIONS_KEY]
    runtime = schemas[RUNTIME_SCHEMA_NAME][DEFINITIONS_KEY]
    check_public_projection(definitions, runtime, api)
    suite = read_json(folder / "conformance-v2.examples.json")
    check_scenario_context(suite, schemas, registry)
    check_recovery_contracts(definitions, runtime, api, schemas[DSL_SCHEMA_NAME])
    check_research_completion_contracts(schemas, api)
    scenario_count = check_scenarios(suite)
    check_topology()
    check_local_schema_refs(folder)
    return {"schemas": len(schemas), "contract_examples": example_count,
            "api_operations": sum(len(v) for v in api["paths"].values()), "contract_scenarios": scenario_count}


def check_public_oracles() -> dict[str, int]:
    data = read_json(ROOT / "contracts/benchmark-v1.json")
    cases = {case["id"]: case for case in data["cases"]}
    check(len(cases) == 4, "Expected four public smoke fixtures")
    line = cases["B-LINE"]
    check(line["y"] == [2 * x + 1 for x in line["x"]], "B-LINE data drift")
    split: list[list[int]] = [line[k] for k in ["fit", "development", "final_test"]]
    split_rows = [row for part in split for row in part]
    check(len(set(split_rows)) == len(split_rows) == len(line["x"]), "Fixture split overlaps or lacks rows")
    domain = cases["B-DOMAIN"]
    check(domain["expected"]["valid_mask"] == [x != 0 for x in domain["x"]], "Domain mask drift")
    check(math.isclose(domain["expected"]["coverage"], 2 / 3), "Coverage denominator drift")
    ambiguous = cases["B-AMBIG"]
    difference = max(abs(math.sin(x) - x) for x in ambiguous["x"])
    check(difference <= ambiguous["absolute_measurement_bound"], "Candidates no longer compatible")
    check(abs(math.sin(1) - 1) > ambiguous["absolute_measurement_bound"], "Proposed distinguishing point fails")
    noise = cases["B-NOISE"]
    final = [noise["y"][i] for i in noise["final_test"]]
    for prefix, prediction in [("candidate", 10), ("baseline", 0)]:
        mae = sum(abs(prediction - y) for y in final) / len(final)
        rmse = math.sqrt(sum((prediction - y) ** 2 for y in final) / len(final))
        check(math.isclose(mae, noise["expected"][prefix + "_mae"]), "Noise MAE drift")
        check(math.isclose(rmse, noise["expected"][prefix + "_rmse"]), "Noise RMSE drift")
    return {"public_fixture_oracles": len(cases)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-manifest", action="store_true", help="Rebuild manifest after all other checks pass")
    args = parser.parse_args()
    report: dict[str, int | str] = {**check_markdown(), **check_contracts(), **check_public_oracles()}
    expected = manifest_data()
    if args.write_manifest:
        (ROOT / MANIFEST_NAME).write_text(json.dumps(expected, ensure_ascii=False, indent=2) + "\n")
    check(read_json(ROOT / MANIFEST_NAME) == expected, "Manifest stale; run with --write-manifest after reviewing changes")
    report["manifest_files"] = len(expected["files"])
    report["product_test_status"] = "NOT_RUN"
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
