"""Float64 scalar interpreter with lazy branches and bounded batch work."""
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
import json
import math
import operator
import re
import time
from typing import Callable
from runtime.contracts import JsonObject
from mathematics.compiler import Plan, compile_dsl
from mathematics.normalization import decimal_value, rational
from mathematics.syntax import DOMAIN, LIMIT, DslError, require

Numeric = int | float
UNARY: dict[str, Callable[[float], float]] = {"sin": math.sin, "cos": math.cos, "exp": math.exp, "log": math.log, "abs": abs}
COMPARATORS: dict[str, Callable[[Fraction, Fraction], bool]] = {"lt": operator.lt, "lte": operator.le, "gt": operator.gt, "gte": operator.ge}


@dataclass(frozen=True)
class Point:
    value: float | None
    valid_mask: bool
    reason: str | None


@dataclass(frozen=True)
class Evaluation:
    points: tuple[Point, ...]
    precision_bits: int = 53


@dataclass
class Budget:
    deadline: float
    remaining: int = 262144

    def visit(self) -> None:
        self.remaining -= 1
        require(self.remaining >= 0 and time.monotonic() < self.deadline, LIMIT)


def _finite(value: float) -> float:
    require(math.isfinite(value), DOMAIN)
    return value


def _float(value: Fraction) -> float:
    result = _finite(float(value))
    require(not value or result != 0, DOMAIN)
    return result


def _numeric(value: Numeric) -> Fraction:
    require(type(value) in {int, float}, DOMAIN)
    if isinstance(value, int):
        require(abs(value) <= 2**53 - 1, DOMAIN)
    else:
        _finite(value)
    return Fraction(value)


def _binding(document: JsonObject, parameters: Mapping[str, str]) -> dict[str, Fraction]:
    require(set(parameters) == {p["name"] for p in document["parameters"]}, "UNKNOWN_SYMBOL")
    result: dict[str, Fraction] = {}
    for declaration in document["parameters"]:
        text = parameters[declaration["name"]]
        require(len(text) <= 128, LIMIT)
        require(re.fullmatch(r"-?(0|[1-9]\d*)(\.\d+)?", text, flags=re.ASCII) is not None)
        value = decimal_value(text)
        require(decimal_value(declaration["lower"]) <= value <= decimal_value(declaration["upper"]), DOMAIN)
        result[declaration["name"]] = value
    return result


def _row(document: JsonObject, row: Mapping[str, Numeric]) -> dict[str, Fraction]:
    require(set(row) == {v["name"] for v in document["variables"]}, "UNKNOWN_SYMBOL")
    result = {name: _numeric(value) for name, value in row.items()}
    for domain in document["domain"]:
        value = result[domain["name"]]
        lower, upper = rational(domain["lower"]), rational(domain["upper"])
        require(lower <= value <= upper, DOMAIN)
        require(value != lower or domain["lower_closed"], DOMAIN)
        require(value != upper or domain["upper_closed"], DOMAIN)
    return result


def _arithmetic(op: str, values: list[float]) -> float:
    if op == "add":
        return math.fsum(values)
    if op == "sub":
        return values[0] - values[1]
    if op == "div":
        result = values[0] / values[1]
        require(not values[0] or result != 0, DOMAIN)
        return result
    if op == "pow":
        require(values[0] != 0 or values[1] > 0, DOMAIN)
        result = math.pow(values[0], values[1])
        require(values[0] == 0 or result != 0, DOMAIN)
        return result
    result = 1.0
    for value in values:
        product = _finite(result * value)
        require(not (result and value) or product != 0, DOMAIN)
        result = product
    return result


def _branch(node: JsonObject, values: dict[str, Fraction], budget: Budget) -> float:
    for branch in node["branches"]:
        when = branch["when"]
        if COMPARATORS[when["comparator"]](values[when["var"]], rational(when["value"])):
            return _execute(branch["then"], values, budget)
    return _execute(node["otherwise"], values, budget)


def _execute(node: JsonObject, values: dict[str, Fraction], budget: Budget) -> float:
    budget.visit()
    op = node["op"]
    if op == "const":
        return _float(rational(node["value"]))
    if op in {"var", "param"}:
        return _float(values[node["name"]])
    if op == "piecewise":
        return _branch(node, values, budget)
    args = [_execute(arg, values, budget) for arg in node["args"]]
    if op in UNARY:
        result = _finite(UNARY[op](args[0]))
        require(op != "exp" or result != 0, DOMAIN)
        return result
    return _finite(_arithmetic(op, args))


def _point(document: JsonObject, row: Mapping[str, Numeric], parameters: dict[str, Fraction], budget: Budget) -> Point:
    try:
        values = _row(document, row) | parameters
        return Point(_execute(document["root"], values, budget), True, None)
    except DslError as error:
        if error.code == LIMIT:
            raise
        return Point(None, False, error.code)
    except (ValueError, OverflowError, ZeroDivisionError):
        return Point(None, False, DOMAIN)


def evaluate(plan: Plan, rows: Sequence[Mapping[str, Numeric]], parameters: Mapping[str, str] | None = None) -> Evaluation:
    # Recompile bounded bytes: callers cannot forge a Plan to bypass validation.
    checked = compile_dsl(plan.canonical)
    require(checked == plan)
    require(len(rows) <= 4096 and checked.node_count * len(rows) <= 262144, LIMIT)
    document: JsonObject = json.loads(checked.canonical)
    binding = _binding(document, parameters if parameters is not None else {})
    budget = Budget(time.monotonic() + 1.0)
    points = tuple(_point(document, row, binding, budget) for row in rows)
    budget.visit()
    return Evaluation(points)
