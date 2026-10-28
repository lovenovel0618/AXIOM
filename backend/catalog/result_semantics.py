"""驗證評估結果的數值語意；結構 schema 以外仍須固定分母、覆蓋率與可比較性。"""
import math
from runtime.budget_types import integer, object_fields
from catalog.validation import ApiError


def verify(value: object, expected_count: int, policy: object) -> None:
    """不讀 labels 核對計數及數值一致性；任何拒絕都發生在曝光結算之前。"""
    result, settings = object_fields(value), object_fields(policy)
    selected, valid, failed = (integer(result[name]) for name in ("selected_count", "valid_count", "failed_count"))
    coverage = result["valid_coverage"]
    expected = 0.0 if selected == 0 else valid / selected
    metrics = object_fields(result["metrics"])
    if (selected != expected_count or valid < 0 or failed < 0 or valid + failed != selected
            or not isinstance(coverage, (int, float)) or isinstance(coverage, bool)
            or not math.isfinite(coverage) or abs(coverage - expected) > 1e-12):
        raise ApiError("INVALID_SCHEMA", 422)
    for value_metric in metrics.values():
        if value_metric is not None and (not isinstance(value_metric, (int, float)) or isinstance(value_metric, bool)
                or not math.isfinite(value_metric) or value_metric < 0 or valid < selected or selected == 0):
            raise ApiError("INVALID_SCHEMA", 422)
    if result["outcome_status"] != "INSUFFICIENT_EVIDENCE" and (selected == 0 or valid != selected
            or metrics["mae"] is None or metrics["rmse"] is None or settings["comparison_method"] == "NONE"
            or settings["error_model"] == "UNSPECIFIED"):
        raise ApiError("INVALID_SCHEMA", 422)
