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

from jsonschema import Draft202012Validator, FormatChecker
from openapi_spec_validator import OpenAPIV31SpecValidator
from referencing import Registry, Resource
sys.dont_write_bytecode = True
from contract_scenarios import check_scenarios

ROOT = Path(__file__).resolve().parents[1]


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def tracked_files():
    return sorted(
        p for p in ROOT.rglob("*")
        if p.is_file() and p.suffix in {".md", ".json", ".py", ".txt"}
        and p.name != "MANIFEST.json" and "__pycache__" not in p.parts
    )


def manifest_data():
    files = tracked_files()
    return {
        "project": "AXIOM", "version": "2.4", "created": "2026-10-20",
        "date": "2026-10-20", "documents": sum(p.suffix == ".md" for p in files),
        "file_count": len(files),
        "files": [{"path": str(p.relative_to(ROOT)), "bytes": p.stat().st_size,
                   "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in files],
    }


def check_markdown():
    paths = sorted(ROOT.rglob("*.md"))
    chapter_ids = []
    case_ids = []
    link_count = 0
    index = (ROOT / "README.md").read_text()
    for path in paths:
        content = path.read_text()
        check(len(re.findall(r"^```", content, re.M)) % 2 == 0, f"Unclosed fence: {path}")
        if path.name[:2].isdigit():
            number = int(path.name[:2])
            chapter_ids.append(number)
            check(f"文件 ID AX-{number:02d}" in content, f"Missing document ID: {path}")
        for block in re.finditer(r"```json\s*\n(.*?)\n```", content, re.S):
            json.loads(block[1])
        plain = re.sub(r"```[\s\S]*?```", "", content)
        check("正常路徑**：給定完整合法的輸入" not in plain, f"Generic AC remains: {path}")
        check("A[前置資料與條件]" not in content, f"Generic workflow remains: {path}")
        check(not re.search(r"\|\n\s*\n\|", plain), f"Split table: {path}")
        case_ids += re.findall(r"^\| (AC-\d{2}-\d{2})(?:[／/][^|]*)?\s*\|", plain, re.M)
        for match in re.finditer(r"\[[^\]\n]+\]\((?:<([^>]+)>|([^\s)]+))\)", plain):
            target = match[1] or match[2]
            if "://" in target or target.startswith("#"):
                continue
            local = unquote(target.split("#")[0])
            check((path.parent / local).is_file(), f"Broken link: {path}: {target}")
            link_count += 1
        if path.name != "README.md":
            check(str(path.relative_to(ROOT)) in index, f"Missing from README: {path}")
    check(sorted(chapter_ids) == list(range(49)), "Chapter numbers must be unique AX-00..48")
    check(len(case_ids) == len(set(case_ids)), "Duplicate acceptance ID")
    trace = next(ROOT.rglob("46-*.md")).read_text()
    for n in range(1, 11):
        check(f"| REQ-{n:03d} " in trace, f"Missing requirement mapping: REQ-{n:03d}")
    for match in re.finditer(r"(AC-\d{2}-)(\d{2})(?:～(\d{2}))?", trace):
        for n in range(int(match[2]), int(match[3] or match[2]) + 1):
            check(match[1] + f"{n:02d}" in case_ids, f"Missing referenced test: {match[0]}")
    return {"markdown": len(paths), "chapters": len(chapter_ids), "links": link_count,
            "acceptance_cases": len(case_ids)}


def check_contracts():
    folder = ROOT / "contracts"
    schemas = {p.name: read_json(p) for p in folder.glob("*.schema.json")}
    registry = Registry()
    for name, schema in schemas.items():
        Draft202012Validator.check_schema(schema)
        resource = Resource.from_contents(schema)
        registry = registry.with_resource(schema["$id"], resource)
        registry = registry.with_resource((folder / name).as_uri(), resource)
    count = 0
    for prefix in ["dsl-v1", "research-v2", "runtime-v2", "event-v2", "task-input-v2"]:
        validator = Draft202012Validator(schemas[prefix + ".schema.json"],
                                         registry=registry, format_checker=FormatChecker())
        examples = read_json(folder / (prefix + ".examples.json"))
        for value in examples["valid"]:
            validator.validate(value)
            if prefix == "research-v2" and value.get("kind") == "Run" and value["status"] == "QUEUED":
                check(all(amount == 0 for amount in value["budget_usage"].values()), "Queued run usage must be zero")
            count += 1
        for value in examples["invalid"]:
            check(not validator.is_valid(value["document"]), f"Invalid example accepted: {prefix}: {value['reason']}")
            count += 1
        # These are structurally valid; semantic rejection belongs to the future DSL engine.
        for value in examples.get("semantic_invalid", []):
            validator.validate(value["document"])
            count += 1
    api = read_json(folder / "openapi-v2.json")
    OpenAPIV31SpecValidator(api).validate()
    def bundled(value, mapping):
        if isinstance(value, dict):
            return {key: mapping.get(item, item) if key == "$ref" else bundled(item, mapping)
                    for key, item in value.items() if key not in {"$id", "$schema"}}
        if isinstance(value, list):
            return [bundled(item, mapping) for item in value]
        return value
    definitions = schemas["research-v2.schema.json"]["$defs"]
    mapping = {"#/$defs/" + name: "#/components/schemas/" + name for name in definitions}
    mapping["dsl-v1.schema.json"] = "#/components/schemas/DSL"
    for name, schema in definitions.items():
        check(api["components"]["schemas"][name] == bundled(schema, mapping),
              f"OpenAPI schema drift: {name}")
    dsl = schemas["dsl-v1.schema.json"]
    dsl_mapping = {"#/$defs/" + name: "#/components/schemas/DSL" + name for name in dsl["$defs"]}
    check(api["components"]["schemas"]["DSL"] == bundled({k: v for k, v in dsl.items() if k != "$defs"}, dsl_mapping),
          "OpenAPI DSL envelope drift")
    for name, schema in dsl["$defs"].items():
        check(api["components"]["schemas"]["DSL" + name] == bundled(schema, dsl_mapping), "OpenAPI DSL node drift")
    check(api["components"]["schemas"]["Event"] == bundled(schemas["event-v2.schema.json"], {}),
          "OpenAPI event schema drift")
    equation_examples = read_json(folder / "research-v2.examples.json")["valid"]
    for example in equation_examples:
        if example["kind"] == "EquationVersion":
            canonical = json.dumps(example["dsl"], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
            check(hashlib.sha256(canonical).hexdigest() == example["identity_hash"], "Public canonical hash drift")
    api_examples = read_json(folder / "api-v2.examples.json")
    for polarity in ["valid", "invalid"]:
        for case in api_examples[polarity]:
            schema = {"$ref": "#/components/schemas/" + case["schema"], "components": api["components"]}
            ok = Draft202012Validator(schema, format_checker=FormatChecker()).is_valid(case["document"])
            check(ok == (polarity == "valid"), f"API example mismatch: {case['schema']}")
            count += 1
    doc = next(ROOT.rglob("21-*.md")).read_text()
    for path, item in api["paths"].items():
        for method in item:
            check(f"{method.upper()} {path}" in doc, f"Endpoint missing from AX-21: {method} {path}")
    for path, item in api["paths"].items():
        for method, operation in item.items():
            headers = {p["name"] for p in operation.get("parameters", []) if p.get("in") == "header"}
            check("If-Match" not in headers, "Business control revision must not masquerade as representation ETag")
            if method == "post" and any(path.endswith(suffix) for suffix in ["/validate", "/runs", "/cancel", "/reviews", "/revoke"]):
                check("If-Control-Revision" in headers, "Control precondition missing")
    event = schemas["event-v2.schema.json"]
    for event_type in event["properties"]["event_type"]["enum"]:
        check(event_type in doc, f"Undocumented event: {event_type}")
    # Reverse coverage catches navigation endpoints described in prose but missing in OpenAPI.
    documented = {(method.lower(), path) for method, path in re.findall(r"^\| (GET|POST|PUT|DELETE|PATCH) (/[^ |]+)", doc, re.M)}
    declared = {(method, path) for path, item in api["paths"].items() for method in item}
    check(documented == declared, f"Bidirectional endpoint drift: {documented ^ declared}")
    check(api["servers"] == [{"url": "/api/v2"}], "HTTP major version drift")
    runtime = schemas["runtime-v2.schema.json"]["$defs"]
    for public_name, private_name in [("Run", "RunRecord"), ("Attempt", "AttemptRecord")]:
        public, private = definitions[public_name], runtime[private_name]
        check(set(public["required"]) <= set(private["required"]), "Internal DTO projection lost required fields")
        for key, value in public["properties"].items():
            if key != "kind":
                check(private["properties"].get(key) == value, f"Private/public shared field drift: {key}")
        check(private_name not in api["components"]["schemas"], "Private control record leaked into OpenAPI")
    suite = read_json(folder / "conformance-v2.examples.json")
    for value in suite["context"].values():
        if isinstance(value, dict) and "kind" in value:
            profile = "runtime-v2" if value["kind"] in {"RunRecord", "AttemptRecord"} else "research-v2"
            Draft202012Validator(schemas[profile + ".schema.json"], registry=registry, format_checker=FormatChecker()).validate(value)
    for field in ["evidence_bundle_ids", "review_ids", "quality_report_id"]:
        check(field in definitions["ResearchVersion"]["required"], "Snapshot recovery reference missing: " + field)
    check(api["paths"]["/review-decisions/{id}"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
          == {"$ref": "#/components/schemas/ReviewDecision"}, "Review history cannot be recovered")
    check(definitions["ReviewDecision"]["properties"]["decision"]["enum"] == ["APPROVE", "REJECT"], "Review enum drift")
    check("dispatch_stage" not in definitions["Run"]["properties"], "Private dispatch control leaked")
    check("outcome_status" in definitions["Run"]["required"] and "skipped_phases" in definitions["Run"]["required"],
          "Run outcome/skip projection missing")
    conformance_count = check_scenarios(suite)
    topology = next(ROOT.rglob("06-*.md")).read_text()
    edges = re.findall(r"\b([A-Z][A-Z0-9]*)\s*-->\s*([A-Z][A-Z0-9]*)", topology)
    check(("SB", "OUT") in edges and ("ESB", "EV") in edges, "Controlled sandbox egress missing")
    check(all(dst not in {"DB", "PG", "OBJ"} for src, dst in edges if src in {"SB", "ESB", "W4"}),
          "Untrusted sandbox directly linked to storage")
    # Every external schema ref in standalone JSON resolves within local contracts.
    def refs(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key == "$ref":
                    yield item
                else:
                    yield from refs(item)
        elif isinstance(value, list):
            for item in value:
                yield from refs(item)
    for path in folder.glob("*.json"):
        for reference in refs(read_json(path)):
            if not reference.startswith("#"):
                check("://" not in reference, f"Unexpected network ref: {reference}")
                check((folder / reference.split("#")[0]).is_file(), f"Missing schema ref: {reference}")
    return {"schemas": len(schemas), "contract_examples": count,
            "api_operations": sum(len(v) for v in api["paths"].values()), "contract_scenarios": conformance_count}


def check_public_oracles():
    data = read_json(ROOT / "contracts/benchmark-v1.json")
    cases = {case["id"]: case for case in data["cases"]}
    check(len(cases) == 4, "Expected four public smoke fixtures")
    line = cases["B-LINE"]
    check(line["y"] == [2 * x + 1 for x in line["x"]], "B-LINE data drift")
    split = [line[k] for k in ["fit", "development", "final_test"]]
    check(len(set(sum(split, []))) == len(sum(split, [])) == len(line["x"]), "Fixture split overlaps or lacks rows")
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-manifest", action="store_true", help="Rebuild manifest after all other checks pass")
    args = parser.parse_args()
    report = {**check_markdown(), **check_contracts(), **check_public_oracles()}
    expected = manifest_data()
    if args.write_manifest:
        (ROOT / "MANIFEST.json").write_text(json.dumps(expected, ensure_ascii=False, indent=2) + "\n")
    check(read_json(ROOT / "MANIFEST.json") == expected, "Manifest stale; run with --write-manifest after reviewing changes")
    report["manifest_files"] = len(expected["files"])
    report["product_test_status"] = "NOT_RUN"
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
