"""Offline contract validation and the AX-48 restricted identity encoding."""
from functools import lru_cache
import hashlib
import json
from pathlib import Path
from typing import Any, cast
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.protocols import Validator
from referencing.jsonschema import Schema
from referencing import Registry, Resource

JsonObject = dict[str, Any]
MAX_BYTES = 2 * 1024 * 1024
MAX_DEPTH = 32
MAX_INTEGER = 2**53 - 1


def _check_identity(value: object, depth: int = 0) -> None:
    if depth > MAX_DEPTH:
        raise ValueError("Canonical JSON depth exceeded")
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, int) and abs(value) <= MAX_INTEGER:
        return
    if isinstance(value, str):
        if len(value) > MAX_BYTES:
            raise ValueError("Canonical JSON size exceeded")
        value.encode("utf-8", errors="strict")
        return
    if isinstance(value, list):
        for item in cast(list[object], value):
            _check_identity(item, depth + 1)
        return
    if isinstance(value, dict):
        _check_mapping(cast(dict[object, object], value), depth)
        return
    raise ValueError("Canonical JSON requires safe integers and JSON values")


def _check_mapping(value: dict[object, object], depth: int) -> None:
    for key, item in value.items():
        if not isinstance(key, str):
            raise ValueError("Canonical object keys must be strings")
        _check_identity(key, depth + 1)
        _check_identity(item, depth + 1)


def canonical_bytes(value: object) -> bytes:
    _check_identity(value)
    encoder = json.JSONEncoder(ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    chunks: list[bytes] = []
    size = 0
    for chunk in encoder.iterencode(value):
        encoded = chunk.encode("utf-8")
        size += len(encoded)
        if size > MAX_BYTES:
            raise ValueError("Canonical JSON size exceeded")
        chunks.append(encoded)
    return b"".join(chunks)


def identity_hash(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


@lru_cache(maxsize=1)
def catalog() -> tuple[Registry[Schema], dict[str, JsonObject]]:
    root = Path(__file__).resolve().parents[1]
    directory = root / "contracts"
    if not directory.is_dir():
        directory = root.parent / "docs" / "企劃案" / "contracts"
    schemas: dict[str, JsonObject] = {}
    resources: list[tuple[str, Resource[Schema]]] = []
    for path in sorted(directory.glob("*.schema.json")):
        schema: JsonObject = json.loads(path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        schemas[path.name] = schema
        resources.append((schema["$id"], Resource.from_contents(schema)))
    return Registry[Schema]().with_resources(resources), schemas


def validate(document: JsonObject, filename: str, definition: str | None = None) -> None:
    registry, schemas = catalog()
    reference = schemas[filename]["$id"]
    if definition is not None:
        reference += "#/$defs/" + definition
    validator = cast(Validator, Draft202012Validator({"$ref": reference}, registry=registry, format_checker=FormatChecker()))
    error = next(validator.iter_errors(document), None)
    if error is not None:
        raise error


def project(document: JsonObject, definition: str) -> JsonObject:
    _, schemas = catalog()
    allowed = schemas["research-v2.schema.json"]["$defs"][definition]["properties"]
    # JSON roundtrip detaches nested values from the mutable internal record.
    result: JsonObject = json.loads(json.dumps({key: value for key, value in document.items() if key in allowed}))
    result["kind"] = definition
    validate(result, "research-v2.schema.json", definition)
    return result
