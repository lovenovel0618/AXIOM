"""HTTP JSON 解碼邊界：限制 bytes／深度，拒絕重複鍵與非有限數，再驗離線 OpenAPI。
框架傳入的動態值不得被當作已具體型別化的核心資料。

Bounded request decoding and offline OpenAPI component validation."""
from functools import lru_cache
import json
import math
from pathlib import Path
from typing import Any, cast
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.protocols import Validator
from jsonschema.exceptions import ValidationError
from runtime.contracts import JsonObject, catalog, canonical_bytes


class ApiError(ValueError):
    def __init__(self, code: str, status: int, details: list[dict[str, object]] | None = None) -> None:
        """保留穩定錯誤碼與 HTTP 狀態；details 僅能帶契約允許的欄位級說明。"""
        self.code, self.status = code, status
        self.details: list[dict[str, object]] = [] if details is None else details
        super().__init__(code)


def _pairs(items: list[tuple[str, Any]]) -> JsonObject:
    result: JsonObject = {}
    for key, value in items:
        if key in result:
            raise ValueError("Duplicate JSON member")
        result[key] = value
    return result


def _invalid_constant(_value: str) -> None:
    raise ValueError("Nonfinite JSON")


def _finite_float(value: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("Nonfinite JSON")
    return result


def _bounded_depth(raw: bytes) -> None:
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
            if depth > 32:
                raise ValueError("JSON depth exceeded")
        elif not quoted and byte in (93, 125):
            depth -= 1


def decode(raw: bytes) -> JsonObject:
    if len(raw) > 65536:
        raise ApiError("UPLOAD_TOO_LARGE", 413)
    try:
        _bounded_depth(raw)
        result: object = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_invalid_constant, parse_float=_finite_float)
        if not isinstance(result, dict):
            raise ApiError("INVALID_SCHEMA", 422)
        return cast(JsonObject, result)
    except (ValueError, RecursionError) as error:
        if isinstance(error, ApiError):
            raise
        raise ApiError("INVALID_JSON", 400) from error


@lru_cache(maxsize=1)
def api_components() -> JsonObject:
    directory = Path(__file__).resolve().parents[1] / "contracts"
    if not directory.is_dir():
        directory = directory.parent.parent / "docs" / "企劃案" / "contracts"
    data: JsonObject = json.loads((directory / "openapi-v2.json").read_text(encoding="utf-8"))
    return data["components"]


def validate_api(document: JsonObject, name: str) -> None:
    registry, _ = catalog()
    validator = cast(Validator, Draft202012Validator({"$ref": "#/components/schemas/" + name, "components": api_components()}, registry=registry, format_checker=FormatChecker()))
    try:
        validator.validate(document)
        canonical_bytes(document)
    except ValidationError as error:
        if name == "CreateUpload" and list(error.absolute_path) == ["size_bytes"] and error.validator == "maximum":
            raise ApiError("UPLOAD_TOO_LARGE", 413) from error
        if name == "CreateUpload" and list(error.absolute_path) == ["format"] and error.validator == "enum":
            raise ApiError("UNSUPPORTED_MEDIA_TYPE", 415) from error
        raise ApiError("INVALID_SCHEMA", 422) from error
    except ValueError as error:
        raise ApiError("INVALID_JSON", 400) from error
