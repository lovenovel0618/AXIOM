"""SEARCH 容量政策：限制列數、每族時限與候選預算；解析器容量另外固定封閉。"""
from dataclasses import asdict, dataclass
import json
import platform
from django.conf import settings
from catalog.models import ResearchVersion
from catalog.validation import ApiError
from ingestion.limits import ImportLimits


@dataclass(frozen=True)
class SearchLimits:
    max_rows: int
    max_strategy_seconds: int
    max_candidates: int

    def __post_init__(self) -> None:
        for value, maximum in ((self.max_rows, 4096), (self.max_strategy_seconds, 30), (self.max_candidates, 1000)):
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError("Invalid SEARCH capacity")

    def document(self) -> dict[str, int]:
        return asdict(self)

    def parsing(self) -> ImportLimits:
        return ImportLimits(self.max_rows, 128, 1048576, 67108864, 30)


def limits_for(version: ResearchVersion) -> SearchLimits:
    """只有 Linux 且明確啟用、完整配置的專用 worker 才可接受新工作。"""
    if not settings.SEARCH_ENABLED or platform.system() != "Linux":
        raise ApiError("DEPENDENCY_UNAVAILABLE", 503)
    try:
        limits = SearchLimits(**json.loads(settings.SEARCH_LIMITS_JSON))
    except (TypeError, ValueError) as error:
        raise ApiError("DEPENDENCY_UNAVAILABLE", 503) from error
    if version.dataset_version.document["row_count"] > limits.max_rows:
        raise ApiError("IMPORT_LIMIT_EXCEEDED", 413)
    return limits
