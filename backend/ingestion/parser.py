"""固定格式解析入口：依明示格式處理 CSV／JSON／Parquet，保留原列次序，不猜語意或靜默丟列。

Parser entry point: use supervisor.inspect_bytes for untrusted data."""
import csv
from pathlib import Path
from typing import Any
from ingestion.limits import ImportLimits, ImportRejected, INVALID, LIMIT_CODE, require
from ingestion.tabular import RowObserver, Table
from ingestion.text_formats import csv_table, json_table


def parse(path: Path, format_name: str, limits: ImportLimits, observer: RowObserver | None = None, *, exact_json: bool = False) -> dict[str, Any]:
    try:
        if format_name == "PARQUET":
            from ingestion.parquet_format import parquet_table
            table = parquet_table(path, limits, observer)
        else:
            table = _text(path, format_name, limits, observer, exact_json)
        return table.metadata()
    except ImportRejected:
        raise
    except csv.Error as error:
        code = LIMIT_CODE if "field larger than field limit" in str(error) else INVALID
        raise ImportRejected(code) from error
    except (ValueError, TypeError, OverflowError, RecursionError) as error:
        raise ImportRejected(INVALID) from error


def _text(path: Path, format_name: str, limits: ImportLimits, observer: RowObserver | None, exact_json: bool) -> Table:
    require(format_name in {"CSV", "JSON"}, "UNSUPPORTED_MEDIA_TYPE")
    with path.open("rb") as source:
        if format_name == "CSV":
            return csv_table(source, limits, observer)
        return json_table(source, limits, observer, exact_json)
