"""DSL 身分正規化：精確有理數／十進位規則與有限常數折疊，不放寬定義域或創造浮點等價。

Exact, bounded rational folding without removing undefined subexpressions."""
from fractions import Fraction
from decimal import Decimal, InvalidOperation
from runtime.contracts import JsonObject, canonical_bytes
from mathematics.syntax import DslError, LIMIT, require, children


def rational(value: JsonObject) -> Fraction:
    return Fraction(int(value["numerator"]), int(value["denominator"]))


def encoded(value: Fraction) -> JsonObject:
    require(len(str(abs(value.numerator))) <= 128 and len(str(value.denominator)) <= 128, LIMIT)
    return {"numerator": str(value.numerator), "denominator": str(value.denominator)}


def decimal_value(text: str) -> Fraction:
    require(len(text) <= 128, LIMIT)
    try:
        value = Decimal(text)
        require(value.is_finite())
        scale = value.as_tuple().exponent
        if not isinstance(scale, int):
            raise DslError("INVALID_SCHEMA")
        require(abs(scale) <= 128)
        return Fraction(value)
    except (InvalidOperation, ValueError, TypeError) as error:
        if isinstance(error, DslError):
            raise
        raise DslError("INVALID_SCHEMA") from error


def decimal_text(text: str) -> str:
    value = decimal_value(text)
    if not value:
        return "0"
    result = format(Decimal(text), "f")
    return result.rstrip("0").rstrip(".") if "." in result else result


def constant(value: Fraction) -> JsonObject:
    return {"op": "const", "value": encoded(value)}


def exponent(node: JsonObject) -> int:
    require(node["op"] == "const", LIMIT)
    value = rational(node["value"])
    require(value.denominator == 1 and -8 <= value <= 8, LIMIT)
    return value.numerator


def _fold(op: str, values: list[Fraction]) -> Fraction | None:
    if op == "add":
        return sum(values, Fraction())
    if op == "mul":
        result = Fraction(1)
        for value in values:
            result *= value
            encoded(result)
        return result
    if op == "sub":
        return values[0] - values[1]
    if op == "div" and values[1]:
        return values[0] / values[1]
    if op == "pow" and (values[0] or values[1] > 0):
        return values[0] ** int(values[1])
    if op == "abs":
        return abs(values[0])
    return None


def _commutative(op: str, args: list[JsonObject]) -> list[JsonObject]:
    flattened: list[JsonObject] = []
    for arg in args:
        flattened.extend(arg["args"] if arg["op"] == op else [arg])
    constants = [rational(arg["value"]) for arg in flattened if arg["op"] == "const"]
    others = [arg for arg in flattened if arg["op"] != "const"]
    if constants:
        folded = _fold(op, constants)
        if folded is not None:
            others.append(constant(folded))
    return sorted(others, key=canonical_bytes)


def normalize(node: JsonObject) -> JsonObject:
    op = node["op"]
    if op == "const":
        return constant(rational(node["value"]))
    if op in {"var", "param"}:
        return dict(node)
    if op == "piecewise":
        branches: list[JsonObject] = []
        for branch in node["branches"]:
            when = dict(branch["when"])
            when["value"] = encoded(rational(when["value"]))
            branches.append({"when": when, "then": normalize(branch["then"])})
        return {"op": op, "branches": branches, "otherwise": normalize(node["otherwise"])}
    args = [normalize(child) for child in children(node)]
    if op in {"add", "mul"}:
        args = _commutative(op, args)
        if len(args) == 1:
            return args[0]
    if all(arg["op"] == "const" for arg in args):
        folded = _fold(op, [rational(arg["value"]) for arg in args])
        if folded is not None:
            return constant(folded)
    return {"op": op, "args": args}
