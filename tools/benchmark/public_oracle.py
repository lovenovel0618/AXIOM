"""Fixed PUBLIC_SMOKE_ONLY oracles and scoring; not a DSL engine or blind evaluator."""
from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import platform
from typing import Any, cast

# Dynamic values exist only at the validated JSON fixture boundary.
JsonObject = dict[str, Any]
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SUITE = ROOT / "docs/企劃案/contracts/benchmark-v1.json"
VISIBILITY = "PUBLIC_SMOKE_ONLY"
CASE_IDS = {"B-LINE", "B-DOMAIN", "B-AMBIG", "B-NOISE"}
SPLIT_NAMES = ("fit", "development", "final_test")
DOMAIN_ERROR = "DOMAIN_VIOLATION"
NON_FINITE = "NON_FINITE"
MISSING = "MISSING_PREDICTION"


@dataclass(frozen=True)
class Prediction:
    value: float | None
    reason: str | None = None


@dataclass(frozen=True)
class Score:
    selected_count: int
    valid_count: int
    failed_count: int
    coverage: float
    mae: float | None
    rmse: float | None
    passed: bool
    row_ids: tuple[int, ...]
    failed_rows: tuple[int, ...]
    failure_counts: dict[str, int]


@dataclass(frozen=True)
class Case:
    identifier: str
    x: tuple[float, ...]
    y: tuple[float, ...]
    splits: dict[str, tuple[int, ...]]
    expected: JsonObject
    bound: float | None


def finite_number(value: object) -> float:
    if type(value) not in {int, float}:
        raise ValueError("Expected a JSON number, excluding bool")
    try:
        number = float(cast(int | float, value))
    except OverflowError as error:
        raise ValueError("Number exceeds finite float range") from error
    if not math.isfinite(number):
        raise ValueError("Expected a finite number")
    return number


def unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def reject_constant(_value: str) -> object:
    raise ValueError("Non-standard JSON constant")


def decode_document(raw: bytes) -> JsonObject:
    if len(raw) > 2 * 1024 * 1024:
        raise ValueError("Public fixture exceeds size limit")
    value: object = json.loads(raw, object_pairs_hook=unique_pairs, parse_constant=reject_constant)
    if not isinstance(value, dict):
        raise ValueError("Fixture must be an object")
    return cast(JsonObject, value)


def load_document(path: Path) -> JsonObject:
    return decode_document(path.read_bytes())


def validate_rows(rows: Sequence[int], count: int) -> tuple[int, ...]:
    if any(type(row) is not int or row < 0 or row >= count for row in rows):
        raise ValueError("Invalid row identity")
    if len(set(rows)) != len(rows):
        raise ValueError("Duplicate row identity")
    return tuple(rows)


def parse_splits(raw: JsonObject, count: int) -> dict[str, tuple[int, ...]]:
    splits: dict[str, tuple[int, ...]] = {}
    for name in SPLIT_NAMES:
        value = raw[name]
        if not isinstance(value, list) or not value:
            raise ValueError("Split must be a nonempty row list")
        splits[name] = validate_rows(cast(list[int], value), count)
    combined = [row for rows in splits.values() for row in rows]
    if len(combined) != count or set(combined) != set(range(count)):
        raise ValueError("Splits overlap or do not cover the fixture")
    expected = {"fit": tuple(range(6)), "development": (6, 7), "final_test": (8, 9)}
    if splits != expected:
        raise ValueError("Fixed public split drifted")
    return splits


def matches_decimal(value: object, expected: str) -> bool:
    return Fraction(str(finite_number(value))) == Fraction(expected)


def case_fields(identifier: str, raw: JsonObject) -> set[str]:
    fields = {"id", "x", "y", "expected"}
    candidates = {"B-LINE": "2*x+1", "B-DOMAIN": "x/x", "B-NOISE": "10"}
    if identifier in {"B-LINE", "B-NOISE"}:
        fields.update(SPLIT_NAMES)
    if identifier == "B-AMBIG":
        fields.update({"absolute_measurement_bound", "candidates"})
        if raw["candidates"] != ["sin(x)", "x"] or not matches_decimal(raw["absolute_measurement_bound"], "0.001"):
            raise ValueError("Ambiguity fixture policy drifted")
    else:
        fields.add("candidate")
        if raw["candidate"] != candidates[identifier]:
            raise ValueError("Unregistered public candidate")
    if identifier == "B-NOISE":
        fields.add("baseline")
        if raw["baseline"] != "0":
            raise ValueError("Baseline drifted")
    return fields


def numbers(value: object) -> tuple[float, ...]:
    if not isinstance(value, list):
        raise ValueError("Observations must be lists")
    return tuple(finite_number(item) for item in cast(list[object], value))


def parse_case(raw: JsonObject) -> Case:
    identifier = str(raw["id"])
    if set(raw) != case_fields(identifier, raw) or not isinstance(raw["expected"], dict):
        raise ValueError("Unexpected public case fields")
    x, y = numbers(raw["x"]), numbers(raw["y"])
    if not x or len(x) != len(y):
        raise ValueError("Observation lengths differ or are empty")
    splits = parse_splits(raw, len(x)) if identifier in {"B-LINE", "B-NOISE"} else {}
    bound = finite_number(raw["absolute_measurement_bound"]) if identifier == "B-AMBIG" else None
    return Case(identifier, x, y, splits, cast(JsonObject, raw["expected"]), bound)


def load_cases(document: JsonObject) -> list[Case]:
    if set(document) != {"version", "visibility", "atol", "rtol", "cases"}:
        raise ValueError("Unexpected public suite fields")
    if document["version"] != "1.0" or document["visibility"] != VISIBILITY:
        raise ValueError("Only the fixed public smoke suite is supported")
    if not matches_decimal(document["atol"], "1e-10") or not matches_decimal(document["rtol"], "1e-10"):
        raise ValueError("Public tolerance drifted")
    rows = document["cases"]
    if not isinstance(rows, list):
        raise ValueError("Expected public case list")
    entries = cast(list[object], rows)
    if len(entries) != len(CASE_IDS):
        raise ValueError("Expected four public cases")
    if any(not isinstance(row, dict) for row in entries):
        raise ValueError("Case must be an object")
    records = cast(list[JsonObject], entries)
    if {str(row.get("id")) for row in records} != CASE_IDS:
        raise ValueError("Duplicate or unknown public case")
    return [parse_case(row) for row in records]


def prediction_error(observed: float, prediction: Prediction) -> tuple[float | None, str | None]:
    if prediction.value is None:
        reason = prediction.reason or MISSING
        if reason not in {DOMAIN_ERROR, NON_FINITE, MISSING}:
            raise ValueError("Unknown prediction failure")
        return None, reason
    if prediction.reason is not None or type(prediction.value) not in {int, float}:
        raise ValueError("Inconsistent prediction")
    error = abs(prediction.value - observed)
    if not math.isfinite(prediction.value) or not math.isfinite(error):
        return None, NON_FINITE
    return error, None


def scoring_inputs(count: int, predictions: Sequence[Prediction], row_ids: Sequence[int] | None,
                   atol: float, rtol: float) -> tuple[tuple[int, ...], float, float]:
    absolute, relative = finite_number(atol), finite_number(rtol)
    if absolute < 0 or relative < 0 or len(predictions) > count:
        raise ValueError("Invalid tolerance or excess predictions")
    identities = tuple(range(count)) if row_ids is None else tuple(row_ids)
    if len(identities) != count or any(type(row) is not int or row < 0 for row in identities):
        raise ValueError("Invalid scoring row identities")
    if len(set(identities)) != len(identities):
        raise ValueError("Scoring row identities must be unique")
    return identities, absolute, relative


@dataclass
class ScoredRows:
    errors: list[float]
    failed: list[int]
    reasons: dict[str, int]
    within: bool = True


def score_rows(observations: Sequence[float], predictions: Sequence[Prediction],
               identities: tuple[int, ...], absolute: float, relative: float) -> ScoredRows:
    result = ScoredRows([], [], {})
    for index, original in enumerate(observations):
        observed = finite_number(original)
        prediction = predictions[index] if index < len(predictions) else Prediction(None, MISSING)
        error, reason = prediction_error(observed, prediction)
        if reason is not None:
            result.failed.append(identities[index])
            result.reasons[reason] = result.reasons.get(reason, 0) + 1
            continue
        if error is None or prediction.value is None:
            raise ValueError("Prediction error result is inconsistent")
        tolerance = absolute + relative * max(abs(observed), abs(prediction.value))
        if not math.isfinite(tolerance):
            raise ValueError("Tolerance overflow")
        result.within = result.within and error <= tolerance
        result.errors.append(error)
    return result


def scaled_metrics(errors: Sequence[float]) -> tuple[float | None, float | None]:
    if not errors:
        return None, None
    scale = max(errors)
    if scale == 0:
        return 0.0, 0.0
    mae = scale * (math.fsum(error / scale for error in errors) / len(errors))
    rmse = scale * math.sqrt(math.fsum((error / scale) ** 2 for error in errors) / len(errors))
    return mae, rmse


def score(observations: Sequence[float], predictions: Sequence[Prediction], *,
          row_ids: Sequence[int] | None = None, atol: float = 1e-10, rtol: float = 1e-10) -> Score:
    identities, absolute, relative = scoring_inputs(len(observations), predictions, row_ids, atol, rtol)
    result = score_rows(observations, predictions, identities, absolute, relative)
    mae, rmse = scaled_metrics(result.errors)
    selected, valid = len(observations), len(result.errors)
    return Score(selected, valid, selected - valid, valid / selected if selected else 0,
                 mae, rmse, bool(selected and valid == selected and result.within),
                 identities, tuple(result.failed), result.reasons)


def sine_reference(value: Fraction) -> Fraction:
    if abs(value) > 1:
        raise ValueError("Reference sine is restricted to [-1,1]")
    return sum(((-1) ** n * value ** (2 * n + 1) / math.factorial(2 * n + 1)
                for n in range(12)), Fraction(0))


def reference_value_matches(actual: object, reference: object) -> bool:
    if type(reference) in {int, float}:
        return math.isclose(finite_number(actual), finite_number(reference), rel_tol=1e-12, abs_tol=1e-12)
    if isinstance(reference, list):
        if not isinstance(actual, list):
            return False
        values = cast(list[object], actual)
        return all(type(item) is bool for item in values) and actual == reference
    if isinstance(reference, bool):
        return type(actual) is bool and actual is reference
    return actual == reference


def expected_matches(expected: JsonObject, reference: JsonObject) -> None:
    if set(expected) != set(reference):
        raise ValueError("Expected oracle fields drifted")
    for key, value in reference.items():
        if not reference_value_matches(expected[key], value):
            raise ValueError("Expected oracle value drifted")


def fixed_observations(case: Case, x: Sequence[float], y: Sequence[float]) -> None:
    if case.x != tuple(x) or len(case.y) != len(y):
        raise ValueError("Fixed observations drifted")
    if any(not math.isclose(left, right, rel_tol=0, abs_tol=1e-15) for left, right in zip(case.y, y, strict=True)):
        raise ValueError("Reference observations drifted")


def line_case(case: Case) -> JsonObject:
    reference = [float(2 * Fraction(n) + 1) for n in range(10)]
    fixed_observations(case, list(range(10)), reference)
    expected_matches(case.expected, {"coverage": 1, "mae": 0, "rmse": 0})
    scores = {name: score([case.y[i] for i in rows], [Prediction(2.0 * case.x[i] + 1.0) for i in rows], row_ids=rows)
              for name, rows in case.splits.items()}
    for result in scores.values():
        expected_matches({"mae": result.mae, "rmse": result.rmse, "coverage": result.coverage},
                         {"mae": 0, "rmse": 0, "coverage": 1})
    if not all(result.passed for result in scores.values()):
        raise ValueError("Linear reference failed")
    return {"id": case.identifier, "status": "PASS", "scores": {key: asdict(value) for key, value in scores.items()}}


def quotient_prediction(numerator: float, denominator: float) -> Prediction:
    try:
        return Prediction(numerator / denominator)
    except ZeroDivisionError:
        return Prediction(None, DOMAIN_ERROR)


def domain_case(case: Case) -> JsonObject:
    fixed_observations(case, [-1, 0, 1], [1, 1, 1])
    expected_matches(case.expected, {"valid_mask": [True, False, True], "coverage": 2 / 3, "error": DOMAIN_ERROR})
    predictions = [quotient_prediction(x, x) for x in case.x]
    result = score(case.y, predictions)
    expected_matches({"mae": result.mae, "rmse": result.rmse, "coverage": result.coverage},
                     {"mae": 0, "rmse": 0, "coverage": 2 / 3})
    if result.passed or result.failed_rows != (1,):
        raise ValueError("Domain failure was discarded")
    return {"id": case.identifier, "status": "PASS", "score": asdict(result)}


def ambiguity_case(case: Case) -> JsonObject:
    x = [Fraction(n, 100) for n in [-10, -5, 0, 5, 10]]
    fixed_observations(case, [float(value) for value in x], [float(sine_reference(value)) for value in x])
    expected_matches(case.expected, {"outcome_status": "AMBIGUOUS", "max_prediction_difference_upper_bound": 0.001, "suggested_x": 1})
    sine = score(case.y, [Prediction(math.sin(value)) for value in case.x], atol=0.001, rtol=0)
    identity = score(case.y, [Prediction(value) for value in case.x], atol=0.001, rtol=0)
    difference = abs(float(sine_reference(Fraction(1))) - 1)
    if not sine.passed or not identity.passed or difference <= 0.001:
        raise ValueError("Ambiguity or distinguishing observation failed")
    return {"id": case.identifier, "status": "PASS", "outcome": "AMBIGUOUS",
            "scores": {"sine": asdict(sine), "identity": asdict(identity)},
            "suggested_x": 1, "distinguishing_difference": difference, "unique": False}


def noise_case(case: Case) -> JsonObject:
    fixed_observations(case, list(range(10)), [1 if i % 2 == 0 else -1 for i in range(10)])
    expected_matches(case.expected, {"candidate_mae": 10, "candidate_rmse": math.sqrt(float(Fraction(101))),
                                   "baseline_mae": 1, "baseline_rmse": 1, "outcome_status": "INSUFFICIENT_EVIDENCE"})
    rows = case.splits["final_test"]
    observations = [case.y[i] for i in rows]
    candidate = score(observations, [Prediction(10) for _ in rows], row_ids=rows)
    baseline = score(observations, [Prediction(0) for _ in rows], row_ids=rows)
    expected_matches({"candidate_mae": candidate.mae, "candidate_rmse": candidate.rmse,
                      "baseline_mae": baseline.mae, "baseline_rmse": baseline.rmse},
                     {"candidate_mae": 10, "candidate_rmse": math.sqrt(float(Fraction(101))),
                      "baseline_mae": 1, "baseline_rmse": 1})
    if candidate.mae is None or baseline.mae is None or candidate.mae <= baseline.mae:
        raise ValueError("Baseline comparison failed")
    return {"id": case.identifier, "status": "PASS", "outcome": "INSUFFICIENT_EVIDENCE",
            "candidate": asdict(candidate), "baseline": asdict(baseline), "randomness_proven": False}


HANDLERS: dict[str, Callable[[Case], JsonObject]] = {
    "B-LINE": line_case, "B-DOMAIN": domain_case, "B-AMBIG": ambiguity_case, "B-NOISE": noise_case,
}


def solver_projection(cases: Sequence[Case]) -> JsonObject:
    projected: list[JsonObject] = []
    for case in cases:
        if case.identifier not in {"B-LINE", "B-NOISE"}:
            continue
        if set(case.splits) != set(SPLIT_NAMES):
            raise ValueError("Projection requires complete validated splits")
        splits = parse_splits({name: list(rows) for name, rows in case.splits.items()}, len(case.x))
        observations = {name: [{"row_id": i, "x": case.x[i], "y": case.y[i]} for i in splits[name]]
                        for name in ("fit", "development")}
        projected.append({"case_id": case.identifier, "observations": observations})
    return {"visibility": VISIBILITY, "scope": "PUBLIC_PROJECTION_ONLY", "cases": projected}


def validate_output_paths(suite: Path, output: Path | None, projection: Path | None) -> None:
    targets = [path.resolve() for path in (output, projection) if path is not None]
    existing = [path for path in (suite, output, projection) if path is not None and path.exists()]
    aliases = any(left.samefile(right) for i, left in enumerate(existing) for right in existing[i + 1:])
    if suite.resolve() in targets or len(set(targets)) != len(targets) or aliases:
        raise ValueError("Output paths must be distinct and cannot overwrite the source fixture")


def serialize_report(report: JsonObject, output: Path | None) -> str:
    serialized = json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2) + "\n"
    if output is not None:
        try:
            output.write_text(serialized, encoding="utf-8")
        except OSError as error:
            report.update(status="FAIL", errors=[type(error).__name__ + ": unable to write report"])
            serialized = json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2) + "\n"
    return serialized


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", type=Path, default=DEFAULT_SUITE)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--projection-output", type=Path)
    args = parser.parse_args()
    report: JsonObject = {"scope": "PUBLIC_REFERENCE_ONLY", "product_status": "NOT_RUN", "status": "FAIL",
                          "python": platform.python_version(), "platform": platform.system(), "machine": platform.machine()}
    output: Path | None = None
    try:
        validate_output_paths(args.suite, args.output, args.projection_output)
        output = args.output
        raw = args.suite.read_bytes()
        document = decode_document(raw)
        cases = load_cases(document)
        results = [HANDLERS[case.identifier](case) for case in cases]
        report.update(status="PASS", visibility=VISIBILITY, version=document["version"],
                      source_sha256=hashlib.sha256(raw).hexdigest(),
                      atol=document["atol"], rtol=document["rtol"], cases=results)
        if args.projection_output:
            args.projection_output.write_text(json.dumps(solver_projection(cases), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError, TypeError, KeyError, OverflowError, RecursionError) as error:
        report.update(status="FAIL", errors=[str(error)])
    serialized = serialize_report(report, output)
    print(serialized, end="")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
