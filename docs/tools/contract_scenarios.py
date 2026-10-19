"""Reference decisions for documentation fixtures, not a worker or database implementation."""
from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from fractions import Fraction
import hashlib
import hmac
import json
from uuid import UUID
from typing import Any, TypeAlias, cast

# Fixture objects are validated against JSON Schemas before reference decisions.
JsonObject: TypeAlias = dict[str, Any]


@dataclass(frozen=True)
class Scenario:
    context: JsonObject
    case: JsonObject


def canonical_hash(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def freeze_decision(c: JsonObject) -> str:
    f, fit, eq = c["frozen_candidate"], c["fit"], c["equation"]
    candidate, sub = c["candidate"], c["submission"]
    if f["candidate_id"] != candidate["id"] or f["fit_run_id"] != fit["id"] or fit["id"] not in candidate["fit_run_ids"]:
        return "FIT_REFERENCE_MISMATCH"
    for key in ["equation_version_id", "dataset_version_id", "observation_split_id"]:
        if f[key] != fit[key]:
            return "FIT_REFERENCE_MISMATCH"
    if f["equation_version_id"] != eq["id"] or f["dsl_identity_hash"] != eq["identity_hash"]:
        return "EQUATION_MISMATCH"
    if f["parameters"] != fit["parameters"]:
        return "BINDING_MISMATCH"
    if f["parameter_binding_hash"] != canonical_hash(f["parameters"]):
        return "BINDING_HASH_MISMATCH"
    if set(f["parameters"]) != {p["name"] for p in eq["dsl"]["parameters"]}:
        return "BINDING_MISMATCH"
    payload = {"research_version_id": c["research_version"]["id"], "sealed_test_id": sub["sealed_test_id"],
               "metric_version": sub["metric_version"], "frozen_candidates": [f]}
    if sub["snapshot_hash"] != canonical_hash(payload):
        return "SNAPSHOT_MISMATCH"
    if sub["frozen_candidate_ids"] != [f["id"]] or f["development_rank"] != candidate["development_rank"]:
        return "RANK_MISMATCH"
    return "ACCEPT"


def time_split_decision(split: JsonObject, observations: list[JsonObject], parts: list[list[int]]) -> str:
    if split["gap_rows"] < split["lookback_rows"] + split["horizon_rows"]:
        return "GAP_TOO_SMALL"
    ordered = [[observations[i][split["time_column"]] for i in part] for part in parts]
    if any(max(a) >= min(b) for a, b in zip(ordered, ordered[1:])):
        return "TIME_LEAK"
    # row_id is source identity, not chronological rank; equal timestamps stay together.
    chronological = sorted(range(len(observations)),
                           key=lambda i: (observations[i][split["time_column"]], i))
    rank = {row: position for position, row in enumerate(chronological)}
    positions = [[rank[i] for i in part] for part in parts]
    if any(part != sorted(part) for part in positions):
        return "TIME_ORDER_INVALID"
    if any(min(b) - max(a) - 1 < split["gap_rows"] for a, b in zip(positions, positions[1:])):
        return "GAP_TOO_SMALL"
    return "ACCEPT"


def group_split_decision(split: JsonObject, observations: list[JsonObject], parts: list[list[int]]) -> str:
    seen = {}
    for index, part in enumerate(parts):
        for i in part:
            group = observations[i][split["group_column"]]
            if group in seen and seen[group] != index:
                return "GROUP_LEAK"
            seen[group] = index
    return "ACCEPT"


def split_decision(c: JsonObject) -> str:
    s = c["research_version"]["observation_split"]
    parts = [s[k] for k in ["fit", "development", "final_test"]]
    rows = [i for part in parts for i in part]
    if len(rows) != len(set(rows)):
        return "SPLIT_OVERLAP"
    if any(i < 0 or i >= len(c["observation_rows"]) for i in rows):
        return "ROW_OUT_OF_RANGE"
    if s["kind"] == "TIME_ORDERED":
        decision = time_split_decision(s, c["observation_rows"], parts)
        if decision != "ACCEPT":
            return decision
    if s["kind"] == "GROUPED_ROWS":
        decision = group_split_decision(s, c["observation_rows"], parts)
        if decision != "ACCEPT":
            return decision
    payload = {k: s[k] for k in ["fit", "development", "final_test", "gap_rows", "lookback_rows", "horizon_rows"]}
    if s["row_ids_hash"] != canonical_hash(payload):
        return "SPLIT_HASH_MISMATCH"
    return "ACCEPT"


def partition_decision(c: JsonObject) -> str:
    families: dict[str, str] = {}
    sources: dict[str, str] = {}
    cases: set[str] = set()
    for row in c["benchmark_partition"]["assignments"]:
        if row["case_id"] in cases:
            return "CASE_DUPLICATED"
        cases.add(row["case_id"])
        for field, seen, error in [("family_id", families, "FAMILY_LEAK"),
                                   ("source_group", sources, "SOURCE_LEAK")]:
            value = row[field]
            if value in seen and seen[value] != row["partition"]:
                return error
            seen[value] = row["partition"]
    return "ACCEPT"

def access_decision(scenario: Scenario) -> str:
    case = scenario.case
    if not case["acl_read"]:
        return "NOT_FOUND"
    access = "SEALED_DETAIL" if case.get("inherited_sealed") else case["access_class"]
    if case["actor"] == "solver" and not case.get("task_bound"):
        return "NOT_FOUND"
    if case["actor"] == "solver" and access != "PROJECT":
        return "NOT_FOUND"
    if access == "SEALED_DETAIL":
        human = (case["actor"] == "reviewer" and case.get("isolated_grant")
                 and case.get("independent_reviewer"))
        evaluator = case["actor"] == "evaluator" and case.get("submission_bound")
        return "ACCEPT" if human or evaluator else "NOT_FOUND"
    if access == "RELEASED_AGGREGATE" and not case.get("release_checked"):
        return "NOT_FOUND"
    return "ACCEPT"


def final_slot_decision(scenario: Scenario) -> str:
    case = scenario.case
    existing, incoming = case["existing"], case["incoming"]
    keys = ["tenant_id", "submission_id", "frozen_candidate_id", "metric_version"]
    if all(existing[key] == incoming[key] for key in keys):
        if existing["status"] == "COMPLETED":
            return "EXISTING_RESULT"
        if existing["status"] == "FAILED":
            return "INVALID_TRANSITION"
        return "REUSE_EVALUATION_RUN"
    return "NEW_SLOT"


def rational_value(value: dict[str, str]) -> Fraction:
    return Fraction(value["numerator"]) / Fraction(value["denominator"])


def valid_domain_bounds(bound: JsonObject) -> bool:
    low, high = rational_value(bound["lower"]), rational_value(bound["upper"])
    if low < high:
        return True
    return low == high and bound["lower_closed"] and bound["upper_closed"]


def domain_contains(bound: JsonObject, value: str) -> bool:
    low, high = rational_value(bound["lower"]), rational_value(bound["upper"])
    point = Fraction(value)
    lower_ok = point > low or (point == low and bound["lower_closed"])
    upper_ok = point < high or (point == high and bound["upper_closed"])
    return lower_ok and upper_ok


def domain_decision(scenario: Scenario) -> str:
    c, case = scenario.context, scenario.case
    domain = c["research_version"]["domain"]
    if len(domain) != 1 or domain[0]["name"] != c["research_version"]["semantic_profile"]["inputs"][0]["name"]:
        return "INVALID_RESEARCH_DOMAIN"
    if not valid_domain_bounds(domain[0]):
        return "INVALID_RESEARCH_DOMAIN"
    if any(not domain_contains(domain[0], value) for value in case["input_values"]):
        return "DOMAIN_VIOLATION"
    if case.get("equation_domain") is not None and case["equation_domain"] != domain:
        return "EQUATION_DOMAIN_MISMATCH"
    return "ACCEPT"


def profile_transition_decision(scenario: Scenario) -> str:
    case = scenario.case
    action = case["action"]
    if case.get("stopping") and action == "validate":
        return "INVALID_TRANSITION"
    return {"cancel_confirmed": "CANCELLED:DRAFT", "permanent_failure": "FAILED:DRAFT",
            "quality_failure": "SUCCEEDED:DRAFT", "retry": "RUNNING:VALIDATING",
            "validate": "QUEUED:VALIDATING"}[action]


def stage_decision(scenario: Scenario) -> str:
    case = scenario.case
    stage, operation = case["stage"], case["operation"]
    if case.get("cancelled"):
        return "ROOT_CANCELLED"
    if operation == "freeze":
        return "ACCEPT" if stage == "SEARCH_OPEN" and case["active_exploration"] == 0 else "INVALID_TRANSITION"
    if stage == "CLOSED":
        return "DISPATCH_STAGE_VIOLATION"
    if stage == "FINAL_ONLY" and (operation != "final_validate" or not case.get("matching_submission")):
        return "DISPATCH_STAGE_VIOLATION"
    return "ACCEPT"


def retry_seal_decision(case: JsonObject, state: str) -> str:
    if not case["same_submission"]:
        return "TEST_ALREADY_CONSUMED" if state == "CONSUMED" else "TEST_ALREADY_RESERVED"
    if case.get("root_terminal"):
        return "INVALID_TRANSITION"
    return "REQUEST_IN_PROGRESS" if case.get("lease_active") else "RECOVER_SAME_RUN"


def seal_recovery_decision(scenario: Scenario) -> str:
    case = scenario.case
    state, action = case["state"], case["action"]
    if action == "retry" and case.get("has_result") and case.get("same_submission"):
        return "EXISTING_RESULT"
    if state == "RETIRED":
        return "TEST_RETIRED"
    if action == "retry":
        return retry_seal_decision(case, state)
    if action == "read_labels":
        return "COMMIT_CONSUMED_BEFORE_READ" if state == "RESERVED" else "INVALID_TRANSITION"
    if action in {"cancel", "permanent_failure"}:
        return "RETIRED" if state == "RESERVED" else "CONSUMED"
    raise AssertionError(f"Unknown seal recovery action: {action}")


def refit_decision(scenario: Scenario) -> str:
    c = scenario.context
    case = scenario.case
    fit, split = case["fit"], c["research_version"]["observation_split"]
    role = fit["split_role"]
    if role not in {"FIT", "FIT_DEVELOPMENT"}:
        return "REFIT_POLICY_INVALID"
    expected = sorted(split["fit"] + (split["development"] if role == "FIT_DEVELOPMENT" else []))
    if fit["fit_row_ids"] != expected or fit["fit_rows_hash"] != canonical_hash(expected):
        return "REFIT_ROWS_MISMATCH"
    if role == "FIT_DEVELOPMENT" and (not fit["refit_policy_artifact_id"] or not case["preregistered"]
            or fit["refit_policy_artifact_id"] != c["research_version"]["refit_policy_artifact_id"]):
        return "REFIT_POLICY_INVALID"
    if role == "FIT" and fit["refit_policy_artifact_id"] is not None:
        return "REFIT_POLICY_INVALID"
    return "ACCEPT"


def submit_decision(scenario: Scenario) -> str:
    c = scenario.context
    root, child = c["root_record"], c["child_record"]
    if (child["root_run_id"] != root["id"] or child["parent_run_id"] != root["id"]
            or child["budget_account_id"] != root["budget_account_id"]
            or child["tenant_id"] != root["tenant_id"]
            or child["research_version_id"] != root["research_version_id"]):
        return "TASK_TREE_MISMATCH"
    if root["status"] != "RUNNING" or root["cancellation_epoch"] != child["root_epoch_at_dispatch"]:
        return "ROOT_CANCELLED"
    if scenario.case["check"] == "submit":
        attempt = c["attempt_record"]
        if child["lease_generation"] != attempt["generation"] or child["active_attempt_id"] != attempt["id"]:
            return "STALE_ATTEMPT"
    return "ACCEPT"


def usage_report_conflicts(report: JsonObject, seen: dict[str, JsonObject], by_sequence: dict[int, float]) -> bool:
    event, sequence, cpu = report["event"], report["sequence"], report["cpu"]
    if event in seen:
        return seen[event] != report
    return sequence in by_sequence and by_sequence[sequence] != cpu


def usage_decision(scenario: Scenario) -> str:
    # Billing is separate from product commits; cancellation must not erase costs.
    case = scenario.case
    seen: dict[str, JsonObject] = {}
    by_sequence: dict[int, float] = {}
    latest, consumed = 0, 0.0
    for report in case["reports"]:
        if usage_report_conflicts(report, seen, by_sequence):
            return "USAGE_CONFLICT"
        event, sequence, cpu = report["event"], report["sequence"], report["cpu"]
        if event in seen:
            continue
        seen[event], by_sequence[sequence] = report, cpu
        if sequence > latest:
            if cpu < consumed:
                return "USAGE_CONFLICT"
            latest, consumed = sequence, cpu
    if "expected_cpu" in case and consumed != case["expected_cpu"]:
        raise AssertionError("Usage cumulative/delta oracle mismatch")
    return "ACCEPT"


def score_decision(scenario: Scenario) -> str:
    c = scenario.context
    case = scenario.case
    def ordered(node: JsonObject) -> JsonObject:
        node = deepcopy(node)
        if "args" in node:
            node["args"] = [ordered(item) for item in node["args"]]
            if node["op"] in {"add", "mul"}:
                node["args"].sort(key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")))
        return node
    expected_family = {"op": "add", "args": [
        {"op": "mul", "args": [{"op": "param", "name": "a"}, {"op": "var", "name": "x"}]},
        {"op": "param", "name": "b"}]}
    family = (ordered(c["equation"]["dsl"]["root"]) == ordered(expected_family)
              and {p["name"] for p in c["equation"]["dsl"]["parameters"]} == {"a", "b"})
    exact = family and Fraction(case["binding"]["a"]) == 2 and Fraction(case["binding"]["b"]) == 1
    if family != case["expected_family_match"] or exact != case["expected_exact_match"]:
        raise AssertionError("Family/parameter-binding oracle mismatch")
    return "ACCEPT"


def streams_decision(scenario: Scenario) -> str:
    case = scenario.case
    closed: set[str] = set()
    latest_by_stream: dict[str, int] = {}
    for scope, name, sequence in case["events"]:
        if scope in closed:
            return "RUN_STREAM_CLOSED"
        if sequence <= latest_by_stream.get(scope, 0):
            return "SEQUENCE_CONFLICT"
        if name in {"ReviewRecorded", "EvidenceRevoked"} and scope != "RESEARCH":
            return "STREAM_SCOPE_MISMATCH"
        latest_by_stream[scope] = sequence
        if scope == "RUN" and name in {"RunFinished", "RunCancelled"}:
            closed.add(scope)
    return "ACCEPT"


def memory_decision(scenario: Scenario) -> str:
    case = scenario.case
    if max(sum(sample) for sample in case["samples"]) != case["expected_peak"]:
        raise AssertionError("Concurrent memory peak oracle mismatch")
    return "ACCEPT"


def exposure_tokens_decision(scenario: Scenario) -> str:
    case = scenario.case
    def tokens(file: JsonObject) -> tuple[set[str], set[str]]:
        content: set[str] = set()
        lineage: set[str] = set()
        def normalized(value: str) -> str:
            fraction = Fraction(value)
            return f"{fraction.numerator}/{fraction.denominator}"
        for index in file["final_ids"]:
            row = file["rows"][index]
            payload = {"inputs": [normalized(row["input"])], "target": normalized(row["target"]),
                       "input_unit": row["input_unit"], "target_unit": row["target_unit"],
                       "time": row.get("time"), "group": row.get("group")}
            def token(kind: str, value: object) -> str:
                message = json.dumps([kind, value], sort_keys=True, separators=(",", ":")).encode()
                return hmac.new(b"public-fixture-key-not-for-production", message, hashlib.sha256).hexdigest()
            content.add(token("CONTENT", payload))
            lineage.add(token("LINEAGE", [row["source_namespace"], row["observation_id"]]))
        return content, lineage
    original, proposed = tokens(case["original"]), tokens(case["proposed"])
    return "BLIND_ELIGIBILITY_DENIED" if any(a & b for a, b in zip(original, proposed)) else "ACCEPT"


def exposure_identity_decision(scenario: Scenario) -> str:
    c = scenario.context
    case = scenario.case
    original, proposed = c["sealed_test"], case["proposed"]
    overlapping = any(set(original[key]) & set(proposed[key])
                      for key in ["final_observation_tokens", "final_lineage_tokens"])
    if overlapping and original["state"] in {"CONSUMED", "RETIRED"}:
        return "BLIND_ELIGIBILITY_DENIED"
    if overlapping and original["state"] == "RESERVED" and original["submission_id"] != proposed["submission_id"]:
        return "TEST_ALREADY_RESERVED"
    return "ACCEPT"


def sealed_identity_decision(scenario: Scenario) -> str:
    c = scenario.context
    case = scenario.case
    original = c["sealed_test"]
    duplicate = {**original, "dataset_version_id": case["new_dataset_version_id"]}
    identity_fields = ["source_content_sha256", "benchmark_partition_id", "benchmark_case_id", "final_rows_hash", "protocol_hash"]
    def fingerprint(item: JsonObject) -> str:
        return canonical_hash({key: item[key] for key in identity_fields})
    if fingerprint(original) == fingerprint(duplicate) and original["state"] == "CONSUMED":
        return "TEST_ALREADY_CONSUMED"
    return "ACCEPT"


def cursor_decision(scenario: Scenario) -> str:
    case = scenario.case
    try:
        scope, stream, seq = case["cursor"].split(":")
        UUID(stream)
        if scope != case["scope"] or stream != case["stream_id"] or int(seq) < 0:
            return "INVALID_CURSOR"
    except (ValueError, TypeError):
        return "INVALID_CURSOR"
    return "ACCEPT"


CASE_HANDLERS: dict[str, Callable[[Scenario], str]] = {
    "access": access_decision,
    "final_slot": final_slot_decision,
    "domain": domain_decision,
    "profile_transition": profile_transition_decision,
    "stage": stage_decision,
    "seal_recovery": seal_recovery_decision,
    "refit": refit_decision,
    "freeze": lambda scenario: freeze_decision(scenario.context),
    "submit": submit_decision,
    "dispatch": submit_decision,
    "split": lambda scenario: split_decision(scenario.context),
    "partition": lambda scenario: partition_decision(scenario.context),
    "usage": usage_decision,
    "score": score_decision,
    "streams": streams_decision,
    "memory": memory_decision,
    "exposure_tokens": exposure_tokens_decision,
    "exposure_identity": exposure_identity_decision,
    "sealed_identity": sealed_identity_decision,
    "cursor": cursor_decision,
}


def execute_case(context: JsonObject, case: JsonObject) -> str:
    handler = CASE_HANDLERS.get(case["check"])
    if handler is None:
        raise AssertionError(f"Unknown conformance check: {case['check']}")
    return handler(Scenario(context, case))



def apply_mutations(context: JsonObject, mutations: list[tuple[str, Any]]) -> None:
    for path, value in mutations:
        parts = path.split(".")
        target: Any = context
        for part in parts[:-1]:
            target = cast(list[Any], target)[int(part)] if isinstance(target, list) else target[part]
        target[int(parts[-1]) if isinstance(target, list) else parts[-1]] = value


def check_scenarios(data: JsonObject) -> int:
    if data["scope"] != "DOCUMENT_REFERENCE_ONLY" or data["product_status"] != "NOT_RUN":
        raise AssertionError("Reference fixture must not claim product testing")
    ids: set[str] = set()
    for case in data["cases"]:
        if case["id"] in ids:
            raise AssertionError("Duplicate scenario ID")
        ids.add(case["id"])
        context = deepcopy(data["context"])
        apply_mutations(context, case.get("mutations", []))
        actual = execute_case(context, case)
        if actual != case["expected"]:
            raise AssertionError(f"{case['id']}: expected {case['expected']}, got {actual}")
    return len(ids)
