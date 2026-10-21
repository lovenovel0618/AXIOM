"""DSL 解碼與語法前置檢查：限制 bytes、深度、節點與字串，拒絕未知節點及任意 Python 表達式。

Untrusted JSON preflight before recursive schema validation."""
import json
from typing import Any, cast
from runtime.contracts import JsonObject, canonical_bytes

LIMIT = "AST_LIMIT_EXCEEDED"
DOMAIN = "DOMAIN_VIOLATION"
INVALID = "INVALID_SCHEMA"
OPERATORS = frozenset({"const", "var", "param", "add", "sub", "mul", "div", "pow", "sin", "cos", "exp", "log", "abs", "piecewise"})
MAX_SIZE = 256 * 1024


class DslError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def require(condition: bool, code: str = INVALID) -> None:
    if not condition:
        raise DslError(code)


def _pairs(items: list[tuple[str, Any]]) -> JsonObject:
    result: JsonObject = {}
    for key, value in items:
        require(key not in result)
        result[key] = value
    return result


def _reject_number(_text: str) -> None:
    raise DslError(INVALID)


def _json_depth(raw: bytes) -> None:
    depth, quoted, escaped = 0, False, False
    for byte in raw:
        if escaped:
            escaped = False
        elif quoted and byte == 92:
            escaped = True
        elif byte == 34:
            quoted = not quoted
        elif not quoted and byte in (91, 123):
            depth += 1
            require(depth <= 32, LIMIT)
        elif not quoted and byte in (93, 125):
            depth -= 1


def decode(raw: bytes) -> JsonObject:
    require(len(raw) <= MAX_SIZE, LIMIT)
    _json_depth(raw)
    try:
        document: object = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs,
                                         parse_float=_reject_number, parse_constant=_reject_number)
        require(isinstance(document, dict))
        canonical_bytes(document)
        return cast(JsonObject, document)
    except (ValueError, RecursionError) as error:
        if isinstance(error, DslError):
            raise
        raise DslError(INVALID) from error


def children(node: JsonObject) -> list[JsonObject]:
    if node.get("op") == "piecewise":
        return [branch["then"] for branch in node["branches"]] + [node["otherwise"]]
    return node.get("args", [])


def preflight(document: JsonObject) -> int:
    # Walk generic containers first; malformed nodes are left to the schema.
    count = 0
    pending: list[tuple[Any, int]] = [(document.get("root"), 1)]
    while pending:
        node, depth = pending.pop()
        require(isinstance(node, dict))
        require(isinstance(node.get("op"), str))
        require(node["op"] in OPERATORS, "UNSUPPORTED_OPERATOR")
        count += 1
        require(count <= 1024 and depth <= 10, LIMIT)
        try:
            pending.extend((child, depth + 1) for child in children(node))
        except (KeyError, TypeError) as error:
            raise DslError(INVALID) from error
    return count
