"""Streaming CSV and flat JSON records with strict shape and JSON semantics."""
from collections.abc import Iterator
import csv
import io
import json
import math
from typing import Any, TextIO
from ingestion.limits import ImportLimits, LIMIT_CODE, require, ImportRejected
from ingestion.tabular import Table


def _lines(source: TextIO, limits: ImportLimits) -> Iterator[str]:
    bound = min(50 * 1024 * 1024, 2 * limits.max_decoded_bytes + 4 * limits.max_columns)
    while True:
        line = source.readline(bound + 1)
        if not line:
            return
        require(len(line) <= bound, LIMIT_CODE)
        yield line


def csv_table(source: io.BufferedReader, limits: ImportLimits) -> Table:
    csv.field_size_limit(limits.max_cell_utf8_bytes)
    reader = csv.reader(_lines(io.TextIOWrapper(source, encoding="utf-8", newline=""), limits), strict=True)
    header = next(reader, None)
    if header is None:
        raise ImportRejected("INVALID_SCHEMA")
    table = Table(limits, header, ["CSV_TEXT"] * len(header))
    for values in reader:
        table.append(values)
    return table


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        require(key not in result)
        result[key] = value
    return result


def _constant(_text: str) -> None:
    raise ImportRejected("INVALID_SCHEMA")


def _float(text: str) -> float:
    result = float(text)
    require(math.isfinite(result))
    return result


def _characters(source: TextIO) -> Iterator[str]:
    while block := source.read(4096):
        yield from block


def _nonspace(characters: Iterator[str]) -> str:
    return next((char for char in characters if char not in " \t\r\n"), "")


def _record(characters: Iterator[str], limits: ImportLimits) -> dict[str, Any]:
    parts = io.StringIO()
    parts.write("{")
    quoted, escaped, size = False, False, 1
    bound = min(50 * 1024 * 1024, 12 * limits.max_decoded_bytes + 32 * limits.max_columns)
    for char in characters:
        size += len(char.encode("utf-8", errors="strict"))
        require(size <= bound, LIMIT_CODE)
        parts.write(char)
        if escaped:
            escaped = False
        elif quoted and char == "\\":
            escaped = True
        elif char == '"':
            quoted = not quoted
        elif not quoted and char in "[{":
            raise ImportRejected("INVALID_SCHEMA")
        elif not quoted and char == "}":
            result: dict[str, Any] = json.loads(parts.getvalue(), object_pairs_hook=_pairs, parse_float=_float, parse_constant=_constant)
            return result
    raise ImportRejected("INVALID_SCHEMA")


def json_table(source: io.BufferedReader, limits: ImportLimits) -> Table:
    characters = _characters(io.TextIOWrapper(source, encoding="utf-8"))
    require(_nonspace(characters) == "[")
    table: Table | None = None
    while True:
        require(_nonspace(characters) == "{")
        row = _record(characters, limits)
        if table is None:
            table = Table(limits, list(row), ["JSON_SCALAR"] * len(row))
        require(row.keys() == set(table.names))
        table.append([row[name] for name in table.names])
        separator = _nonspace(characters)
        if separator == "]":
            break
        require(separator == ",")
    require(_nonspace(characters) == "")
    return table
