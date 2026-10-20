"""Parser entry point: use supervisor.inspect_bytes for untrusted data."""
import csv
from pathlib import Path
from typing import Any
from ingestion.limits import ImportLimits, ImportRejected, INVALID, LIMIT_CODE, require
from ingestion.tabular import Table
from ingestion.text_formats import csv_table, json_table


def parse(path: Path, format_name: str, limits: ImportLimits) -> dict[str, Any]:
    try:
        if format_name == "PARQUET":
            from ingestion.parquet_format import parquet_table
            table = parquet_table(path, limits)
        else:
            table = _text(path, format_name, limits)
        return table.metadata()
    except ImportRejected:
        raise
    except csv.Error as error:
        code = LIMIT_CODE if "field larger than field limit" in str(error) else INVALID
        raise ImportRejected(code) from error
    except (ValueError, TypeError, OverflowError, RecursionError) as error:
        raise ImportRejected(INVALID) from error


def _text(path: Path, format_name: str, limits: ImportLimits) -> Table:
    require(format_name in {"CSV", "JSON"}, "UNSUPPORTED_MEDIA_TYPE")
    with path.open("rb") as source:
        if format_name == "CSV":
            return csv_table(source, limits)
        return json_table(source, limits)
