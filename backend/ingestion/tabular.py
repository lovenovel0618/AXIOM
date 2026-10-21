"""最小純量表格介面：格式層只保留欄名、型別與原 row，不作語意猜測或資料修補。

Shared bounded counters; metadata contains no observed cell values."""
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from ingestion.limits import ImportLimits, LIMIT_CODE, require


RowObserver = Callable[[int, list[str], Sequence[object]], None]


@dataclass
class Table:
    limits: ImportLimits
    names: list[str]
    physical_types: list[str]
    rows: int = 0
    decoded: int = 0
    observer: RowObserver | None = None

    def __post_init__(self) -> None:
        require(bool(self.names))
        require(len(self.names) <= self.limits.max_columns, LIMIT_CODE)
        require(len(self.names) == len(set(self.names)))
        require(all(name and len(name) <= 256 and "\x00" not in name for name in self.names))
        require(len(self.physical_types) == len(self.names))
        for name in self.names:
            self.account(name)

    def account(self, text: str) -> None:
        size = len(text.encode("utf-8", errors="strict"))
        require(size <= self.limits.max_cell_utf8_bytes, LIMIT_CODE)
        self.decoded += size
        require(self.decoded <= self.limits.max_decoded_bytes, LIMIT_CODE)

    def append(self, values: Sequence[object]) -> None:
        require(len(values) == len(self.names))
        require(self.rows < self.limits.max_rows, LIMIT_CODE)
        for value in values:
            self.account(scalar_text(value))
        if self.observer is not None:
            self.observer(self.rows, self.names, values)
        self.rows += 1

    def metadata(self) -> dict[str, Any]:
        return {"row_count": self.rows, "columns": [{"name": name, "physical_type": dtype}
                for name, dtype in zip(self.names, self.physical_types, strict=True)]}


def scalar_text(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        # Parquet retains nonfinite observations for later quality validation.
        return repr(value)
    require(isinstance(value, (str, int, Decimal, date, datetime, time, timedelta)))
    return str(value)
