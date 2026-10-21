"""Parquet 解析邊界：先驗 metadata 與容量，再有界解碼；拒絕巢狀／非純量資料以防記憶體擴張。

Local-file scalar Parquet, bounded streaming batches inside the worker."""
from pathlib import Path
import polars as pl
from ingestion.limits import ImportLimits, ImportRejected, require
from ingestion.tabular import RowObserver, Table


def _scalar(dtype: pl.DataType) -> bool:
    return (dtype.is_integer() or dtype.is_float() or
            dtype.base_type() in {pl.String, pl.Boolean, pl.Null, pl.Date, pl.Datetime, pl.Duration, pl.Time, pl.Decimal})


def parquet_table(path: Path, limits: ImportLimits, observer: RowObserver | None = None) -> Table:
    try:
        return _parquet_table(path, limits, observer)
    except pl.exceptions.PolarsError as error:
        raise ImportRejected("INVALID_SCHEMA") from error


def _parquet_table(path: Path, limits: ImportLimits, observer: RowObserver | None) -> Table:
    with path.open("rb") as source:
        require(source.read(4) == b"PAR1")
        source.seek(-4, 2)
        require(source.read(4) == b"PAR1")
    schema = pl.read_parquet_schema(path)
    require(all(_scalar(dtype) for dtype in schema.values()))
    table = Table(limits, list(schema), [str(dtype) for dtype in schema.values()], observer=observer)
    query = pl.scan_parquet(path, n_rows=limits.max_rows + 1, parallel="none", hive_partitioning=False,
                            glob=False, low_memory=True, cache=False, credential_provider=None, retries=0)
    for batch in query.collect_batches(chunk_size=64, maintain_order=True, lazy=True, engine="streaming"):
        for row in batch.iter_rows():
            table.append(row)
    return table
