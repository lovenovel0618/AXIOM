"""Offline schema, declaration, domain and SI dimension validation."""
from dataclasses import dataclass
from operator import itemgetter
import hashlib
from jsonschema.exceptions import ValidationError
from runtime.contracts import JsonObject, canonical_bytes, validate
from mathematics.normalization import decimal_text, decimal_value, encoded, exponent, normalize, rational
from mathematics.syntax import DslError, LIMIT, decode, preflight, require, children

Unit = tuple[int, ...]
DIMENSIONLESS: Unit = (0,) * 7
UNIT_ERROR = "UNIT_MISMATCH"
UNKNOWN = "UNKNOWN_SYMBOL"


@dataclass(frozen=True)
class Plan:
    canonical: bytes
    identity_hash: str
    output_unit: Unit
    node_count: int


def _declarations(document: JsonObject) -> tuple[dict[str, Unit], dict[str, Unit]]:
    groups: list[dict[str, Unit]] = []
    for name in ("variables", "parameters"):
        require(len(document[name]) <= 128, LIMIT)
        result: dict[str, Unit] = {}
        for declaration in document[name]:
            symbol = declaration["name"]
            require(symbol not in result)
            result[symbol] = tuple(declaration["unit"])
        document[name].sort(key=itemgetter("name"))
        groups.append(result)
    variables, parameters = groups
    require(not (variables.keys() & parameters.keys()))
    for parameter in document["parameters"]:
        parameter["lower"] = decimal_text(parameter["lower"])
        parameter["upper"] = decimal_text(parameter["upper"])
        require(decimal_value(parameter["lower"]) <= decimal_value(parameter["upper"]))
    return variables, parameters


def _domains(document: JsonObject, variables: dict[str, Unit]) -> None:
    seen: set[str] = set()
    require(len(document["domain"]) <= 128, LIMIT)
    for domain in document["domain"]:
        name = domain["name"]
        require(name in variables, UNKNOWN)
        require(name not in seen)
        seen.add(name)
        lower, upper = rational(domain["lower"]), rational(domain["upper"])
        require(lower <= upper)
        require(lower != upper or (domain["lower_closed"] and domain["upper_closed"]))
        domain["lower"], domain["upper"] = encoded(lower), encoded(upper)
    require(seen == variables.keys())
    document["domain"].sort(key=itemgetter("name"))


def _same(units: list[Unit]) -> Unit:
    require(all(unit == units[0] for unit in units), UNIT_ERROR)
    return units[0]


def _piecewise_unit(node: JsonObject, variables: dict[str, Unit], parameters: dict[str, Unit]) -> Unit:
    for branch in node["branches"]:
        require(branch["when"]["var"] in variables, UNKNOWN)
    return _same([infer(child, variables, parameters) for child in children(node)])


def _operation_unit(node: JsonObject, units: list[Unit]) -> Unit:
    op = node["op"]
    if op in {"add", "sub"}:
        return _same(units)
    if op in {"mul", "div"}:
        sign = -1 if op == "div" else 1
        return tuple(units[0][index] + sign * sum(unit[index] for unit in units[1:]) for index in range(7))
    if op == "pow":
        power = exponent(node["args"][1])
        return tuple(index * power for index in units[0])
    if op == "abs":
        return units[0]
    require(units[0] == DIMENSIONLESS, UNIT_ERROR)
    return DIMENSIONLESS


def infer(node: JsonObject, variables: dict[str, Unit], parameters: dict[str, Unit]) -> Unit:
    op = node["op"]
    if op == "const":
        return DIMENSIONLESS
    if op in {"var", "param"}:
        group = variables if op == "var" else parameters
        require(node["name"] in group, UNKNOWN)
        return group[node["name"]]
    if op == "piecewise":
        return _piecewise_unit(node, variables, parameters)
    return _operation_unit(node, [infer(child, variables, parameters) for child in children(node)])


def compile_dsl(raw: bytes) -> Plan:
    document = decode(raw)
    preflight(document)
    try:
        validate(document, "dsl-v1.schema.json")
    except ValidationError as error:
        raise DslError("INVALID_SCHEMA") from error
    variables, parameters = _declarations(document)
    _domains(document, variables)
    unit = infer(document["root"], variables, parameters)
    document["root"] = normalize(document["root"])
    canonical = canonical_bytes(document)
    return Plan(canonical, hashlib.sha256(canonical).hexdigest(), unit, preflight(document))
