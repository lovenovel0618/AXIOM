"""Reference decisions for documentation fixtures, not a worker or database implementation."""
from __future__ import annotations

from copy import deepcopy
from fractions import Fraction
import hashlib
import json
from uuid import UUID


def canonical_hash(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def freeze_decision(c):
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


def split_decision(c):
    s = c["research_version"]["observation_split"]
    parts = [s[k] for k in ["fit", "development", "final_test"]]
    rows = [i for part in parts for i in part]
    if len(rows) != len(set(rows)):
        return "SPLIT_OVERLAP"
    if any(i < 0 or i >= len(c["observation_rows"]) for i in rows):
        return "ROW_OUT_OF_RANGE"
    if s["kind"] == "TIME_ORDERED":
        if s["gap_rows"] < s["lookback_rows"] + s["horizon_rows"]:
            return "GAP_TOO_SMALL"
        ordered = [[c["observation_rows"][i][s["time_column"]] for i in part] for part in parts]
        if any(max(a) >= min(b) for a, b in zip(ordered, ordered[1:])):
            return "TIME_LEAK"
        if any(min(b) - max(a) - 1 < s["gap_rows"] for a, b in zip(parts, parts[1:])):
            return "GAP_TOO_SMALL"
    if s["kind"] == "GROUPED_ROWS":
        seen = {}
        for index, part in enumerate(parts):
            for i in part:
                group = c["observation_rows"][i][s["group_column"]]
                if group in seen and seen[group] != index:
                    return "GROUP_LEAK"
                seen[group] = index
    payload = {k: s[k] for k in ["fit", "development", "final_test", "gap_rows", "lookback_rows", "horizon_rows"]}
    if s["row_ids_hash"] != canonical_hash(payload):
        return "SPLIT_HASH_MISMATCH"
    return "ACCEPT"


def partition_decision(c):
    families, sources, cases = {}, {}, set()
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


def execute_case(c, case):
    kind = case["check"]
    if kind == "freeze":
        return freeze_decision(c)
    if kind in {"submit", "dispatch"}:
        root, child = c["root_record"], c["child_record"]
        if (child["root_run_id"] != root["id"] or child["parent_run_id"] != root["id"]
                or child["budget_account_id"] != root["budget_account_id"]
                or child["tenant_id"] != root["tenant_id"]
                or child["research_version_id"] != root["research_version_id"]):
            return "TASK_TREE_MISMATCH"
        if root["status"] != "RUNNING" or root["cancellation_epoch"] != child["root_epoch_at_dispatch"]:
            return "ROOT_CANCELLED"
        if kind == "submit":
            attempt = c["attempt_record"]
            if child["lease_generation"] != attempt["generation"] or child["active_attempt_id"] != attempt["id"]:
                return "STALE_ATTEMPT"
        return "ACCEPT"
    if kind == "split":
        return split_decision(c)
    if kind == "partition":
        return partition_decision(c)
    if kind == "usage":
        # Billing is a separate authenticated path; root cancellation is not a reason to erase costs.
        seen, by_sequence, latest, consumed = {}, {}, 0, 0
        for report in case["reports"]:
            event, seq, cpu = report["event"], report["sequence"], report["cpu"]
            if event in seen:
                if seen[event] != report:
                    return "USAGE_CONFLICT"
                continue
            if seq in by_sequence and by_sequence[seq] != cpu:
                return "USAGE_CONFLICT"
            seen[event], by_sequence[seq] = report, cpu
            if seq > latest:
                if cpu < consumed:
                    return "USAGE_CONFLICT"
                latest, consumed = seq, cpu
        if "expected_cpu" in case and consumed != case["expected_cpu"]:
            raise AssertionError("Usage cumulative/delta oracle mismatch")
        return "ACCEPT"
    if kind == "score":
        # This fixture has a known a*x+b family; it is not a general symbolic-equivalence solver.
        def ordered(node):
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
    if kind == "streams":
        closed, latest = set(), {}
        for scope, name, sequence in case["events"]:
            if scope in closed:
                return "RUN_STREAM_CLOSED"
            if sequence <= latest.get(scope, 0):
                return "SEQUENCE_CONFLICT"
            if name in {"ReviewRecorded", "EvidenceRevoked"} and scope != "RESEARCH":
                return "STREAM_SCOPE_MISMATCH"
            latest[scope] = sequence
            if scope == "RUN" and name in {"RunFinished", "RunCancelled"}:
                closed.add(scope)
        return "ACCEPT"
    if kind == "memory":
        if max(sum(sample) for sample in case["samples"]) != case["expected_peak"]:
            raise AssertionError("Concurrent memory peak oracle mismatch")
        return "ACCEPT"
    if kind == "sealed_identity":
        original = c["sealed_test"]
        duplicate = {**original, "dataset_version_id": case["new_dataset_version_id"]}
        identity_fields = ["source_content_sha256", "benchmark_partition_id", "benchmark_case_id", "final_rows_hash", "protocol_hash"]
        fingerprint = lambda item: canonical_hash({key: item[key] for key in identity_fields})
        if fingerprint(original) == fingerprint(duplicate) and original["state"] == "CONSUMED":
            return "TEST_ALREADY_CONSUMED"
        return "ACCEPT"
    if kind == "cursor":
        try:
            scope, stream, seq = case["cursor"].split(":")
            UUID(stream)
            if scope != case["scope"] or stream != case["stream_id"] or int(seq) < 0:
                return "INVALID_CURSOR"
        except (ValueError, TypeError):
            return "INVALID_CURSOR"
        return "ACCEPT"
    raise AssertionError(f"Unknown conformance check: {kind}")


def check_scenarios(data):
    if data["scope"] != "DOCUMENT_REFERENCE_ONLY" or data["product_status"] != "NOT_RUN":
        raise AssertionError("Reference fixture must not claim product testing")
    ids = set()
    for case in data["cases"]:
        if case["id"] in ids:
            raise AssertionError("Duplicate scenario ID")
        ids.add(case["id"])
        context = deepcopy(data["context"])
        for path, value in case.get("mutations", []):
            parts, target = path.split("."), context
            for part in parts[:-1]:
                target = target[int(part)] if isinstance(target, list) else target[part]
            target[int(parts[-1]) if isinstance(target, list) else parts[-1]] = value
        actual = execute_case(context, case)
        if actual != case["expected"]:
            raise AssertionError(f"{case['id']}: expected {case['expected']}, got {actual}")
    return len(ids)
