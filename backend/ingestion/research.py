"""研究品質核心：先按固定 row ID 切分，再做精確 canonical 單位轉換及 float64 邊界檢查。
只計 fit 統計與 fit／development 已知公式評分；任一區品質失敗只回同一遮罩，不暴露 final 細節。

Fixed split quality checks and fit/development-only known-model inspection."""
from collections.abc import Sequence
from decimal import Decimal, InvalidOperation
from fractions import Fraction
import json
import math
from pathlib import Path
import re
from typing import Any
from ingestion.limits import ImportLimits, ImportRejected, require
from ingestion.parser import parse
from mathematics.compiler import Plan, compile_dsl
from mathematics.evaluator import evaluate
from mathematics.metrics import metrics, quantile
from mathematics.syntax import DslError
from runtime.contracts import canonical_bytes, identity_hash

MAX_ROWS = 4096
POLICY = "local-research-inspection-v1"
PARTITIONS = ("fit", "development", "final_test")
HASH_FIELDS = PARTITIONS + ("gap_rows", "lookback_rows", "horizon_rows")
NUMBER = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", flags=re.ASCII)


def model_for(config: dict[str, Any]) -> Plan | None:
    model = config["model"]
    if model is None:
        require(not config["parameters"])
        return None
    plan = compile_dsl(canonical_bytes(model))
    document = json.loads(plan.canonical)
    research = config["research"]
    variable = research["semantic_profile"]["inputs"][0]
    require(document["variables"] == [{"name": variable["name"], "unit": variable["unit"]}], "UNIT_MISMATCH")
    require(list(plan.output_unit) == research["semantic_profile"]["target"]["unit"], "UNIT_MISMATCH")
    require(document["domain"] == research["domain"], "DOMAIN_VIOLATION")
    evaluate(plan, [], config["parameters"])  # Check all bindings before reading observations.
    return plan


def scalar(value: object) -> Fraction:
    if isinstance(value, float):
        require(math.isfinite(value))
        return Fraction(value)
    if type(value) is int:
        return Fraction(value)
    require(isinstance(value, (str, Decimal)))
    text = str(value)
    require(len(text) <= 256 and NUMBER.fullmatch(text) is not None)
    number = Decimal(text)
    require(number.is_finite() and abs(int(number.as_tuple().exponent)) <= 1024)
    return Fraction(number)


def converted(value: object, mapping: dict[str, Any]) -> tuple[Fraction, float]:
    rule = mapping["conversion"]
    exact = scalar(value) * Fraction(rule["scale"]) + Fraction(rule["offset"])
    rounded = float(exact)
    require(math.isfinite(rounded) and (not exact or rounded != 0))
    return exact, rounded


def in_domain(value: Fraction, domain: dict[str, Any]) -> bool:
    lower = Fraction(int(domain["lower"]["numerator"]), int(domain["lower"]["denominator"]))
    upper = Fraction(int(domain["upper"]["numerator"]), int(domain["upper"]["denominator"]))
    return lower <= value <= upper and (value != lower or domain["lower_closed"]) and (value != upper or domain["upper_closed"])


class Inspector:
    def __init__(self, config: dict[str, Any]) -> None:
        self.projection = config.get("mode") == "SEARCH_PROJECTION"
        self.research = config["research"]
        split = self.research["observation_split"]
        self.members = {row: name for name in PARTITIONS for row in split[name]}
        count = sum(len(split[name]) for name in PARTITIONS)
        require(count <= MAX_ROWS and len(self.members) == count)
        require(set(self.members) == set(range(count)))
        require(split["row_ids_hash"] == identity_hash({name: split[name] for name in HASH_FIELDS}))
        require(split["kind"] in {"IID_ROWS", "EXPLICIT"} and not self.research["semantic_profile"]["time_ordered"])
        require(self.research["semantic_profile"]["group_column"] is None)
        self.plan = model_for(config)
        if self.plan is not None:
            require(self.plan.node_count * max(len(split["fit"]), len(split["development"])) <= 262144, "AST_LIMIT_EXCEEDED")
        self.parameters = config["parameters"]
        self.bad = False
        self.selected: dict[str, list[tuple[Fraction, float, float]]] = {"fit": [], "development": []}

    def observe(self, row: int, names: list[str], values: Sequence[object]) -> None:
        require(row in self.members)
        profile = self.research["semantic_profile"]
        source, target = profile["inputs"][0], profile["target"]
        require(source["source_column"] in names and target["source_column"] in names)
        try:
            exact_x, x = converted(values[names.index(source["source_column"])], source)
            exact_y, y = converted(values[names.index(target["source_column"])], target)
            domain = self.research["domain"][0]
            require(in_domain(exact_x, domain) and in_domain(Fraction(x), domain))
        except (InvalidOperation, OverflowError, ValueError):
            self.bad = True
            return
        partition = self.members[row]
        if partition != "final_test":
            self.selected[partition].append((exact_y, x, y))

    def result(self) -> dict[str, Any]:
        result: dict[str, Any] = {"policy_version": POLICY, "quality": "BLOCKED" if self.bad else "PASS", "blocking_code": "DATA_QUALITY_BLOCKED" if self.bad else None,
            "precision_bits": 53, "fit_summary": None, "model_evaluation": None}
        if self.bad:
            return result
        if self.projection:
            return {"kind": "SearchProjection", "precision_bits": 53,
                "fit": [[repr(row[1]), repr(row[2])] for row in self.selected["fit"]],
                "development": [[repr(row[1]), repr(row[2])] for row in self.selected["development"]]}
        fit = self.selected["fit"]
        targets = sorted(row[0] for row in fit)
        result["fit_summary"] = {"selected_count": len(fit), "unique_x": len({row[1] for row in fit}), "target_min": str(targets[0]), "target_max": str(targets[-1]),
            "target_mean": str(sum(targets, Fraction(0)) / len(targets)), "target_iqr": str(quantile(targets, Fraction(3,4)) - quantile(targets, Fraction(1,4)))}
        if self.plan is not None:
            result["model_evaluation"] = {name: metrics(self.plan, self.parameters, rows, self.research["semantic_profile"]["inputs"][0]["name"])
                for name, rows in self.selected.items()}
        return result


def inspect_file(path: Path, format_name: str, limits: ImportLimits, config: dict[str, Any]) -> dict[str, Any]:
    try:
        inspector = Inspector(config)
        metadata = parse(path, format_name, limits, inspector.observe, exact_json=True)
        require(metadata == config["metadata"] and metadata["row_count"] == len(inspector.members))
        return inspector.result()
    except DslError as error:
        raise ImportRejected(error.code) from error
