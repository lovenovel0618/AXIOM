"""Explicit local limits, distinct from approved production capacity."""
from dataclasses import asdict, dataclass
from typing import Any

LIMIT_CODE = "IMPORT_LIMIT_EXCEEDED"
INVALID = "INVALID_SCHEMA"


class ImportRejected(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def require(condition: bool, code: str = INVALID) -> None:
    if not condition:
        raise ImportRejected(code)


@dataclass(frozen=True)
class ImportLimits:
    max_rows: int
    max_columns: int
    max_cell_utf8_bytes: int
    max_decoded_bytes: int
    max_parse_seconds: int

    def __post_init__(self) -> None:
        maxima = (1000000, 128, 1048576, 67108864, 30)
        for value, maximum in zip(asdict(self).values(), maxima, strict=True):
            require(type(value) is int and 1 <= value <= maximum, LIMIT_CODE)

    def document(self) -> dict[str, Any]:
        return asdict(self)
