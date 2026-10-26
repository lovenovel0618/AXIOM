"""子程序輸出信任邊界：只允許固定鍵、有限有界數值及正確評分分母。
未預期欄位、final 原值／位置或不一致計數一律拒絕；SEARCH_PROJECTION 另只放行兩區有限數值字串。

Strict child allowlist; only SEARCH_PROJECTION permits fit/development observations."""
from decimal import Decimal, InvalidOperation
from fractions import Fraction
import re
import json
import math
from typing import Any, cast
from runtime.budget_types import object_fields
from ingestion.limits import require
from ingestion.research import POLICY

DEPENDENCY = "DEPENDENCY_UNAVAILABLE"
CODES = {"INVALID_SCHEMA", "IMPORT_LIMIT_EXCEEDED", "UNSUPPORTED_MEDIA_TYPE", "UNIT_MISMATCH", "DOMAIN_VIOLATION", "UNKNOWN_SYMBOL", "AST_LIMIT_EXCEEDED"}


def number(value: object) -> Fraction:
    require(isinstance(value, str) and 1 <= len(value) <= 4096, DEPENDENCY)
    text = str(value)
    try:
        if "/" in text:
            require(re.fullmatch(r"-?\d+/[1-9]\d*", text, flags=re.ASCII) is not None, DEPENDENCY)
            return Fraction(text)
        decimal = Decimal(text)
        require(decimal.is_finite() and abs(int(decimal.as_tuple().exponent)) <= 4096, DEPENDENCY)
        return Fraction(decimal)
    except (InvalidOperation, ValueError) as error:
        raise ValueError(DEPENDENCY) from error


def metrics_check(value: dict[str, Any], count: int) -> None:
    require(set(value) == {"selected_count", "valid_count", "failed_count", "coverage", "mae", "rmse"}, DEPENDENCY)
    require(all(type(value[name]) is int for name in ("selected_count", "valid_count", "failed_count")), DEPENDENCY)
    valid = value["valid_count"]
    require(value["selected_count"] == count and 0 <= valid <= count and value["failed_count"] == count - valid, DEPENDENCY)
    require(value["coverage"] == str(Fraction(valid, count)), DEPENDENCY)
    for name in ("mae", "rmse"):
        if valid < count:
            require(value[name] is None, DEPENDENCY)
        else:
            require(number(value[name]) >= 0, DEPENDENCY)


def fit_check(value: dict[str, Any], count: int) -> None:
    require(set(value) == {"selected_count", "unique_x", "target_min", "target_max", "target_mean", "target_iqr"}, DEPENDENCY)
    require(type(value["selected_count"]) is int and value["selected_count"] == count, DEPENDENCY)
    require(type(value["unique_x"]) is int and 1 <= value["unique_x"] <= count, DEPENDENCY)
    require(number(value["target_min"]) <= number(value["target_mean"]) <= number(value["target_max"]), DEPENDENCY)
    require(number(value["target_iqr"]) >= 0, DEPENDENCY)


def array_items(value: object) -> list[object]:
    """只收斂已驗證的 list 容器；元素仍為 object，必須逐項檢查。"""
    if not isinstance(value, list):
        raise ValueError(DEPENDENCY)
    return cast(list[object], value)


def projection_check(value: object, config: object) -> None:
    """SEARCH 專用數值通道只容許兩區、固定列數與有限十進位字串。"""
    document = object_fields(value)
    split = object_fields(object_fields(object_fields(config)["research"])["observation_split"])
    require(set(document) == {"kind", "precision_bits", "fit", "development"}, DEPENDENCY)
    require(type(document["precision_bits"]) is int and document["precision_bits"] == 53, DEPENDENCY)
    for role in ("fit", "development"):
        rows = array_items(document[role])
        require(len(rows) == len(array_items(split[role])), DEPENDENCY)
        for value_row in rows:
            row = array_items(value_row)
            require(len(row) == 2, DEPENDENCY)
            for cell in row:
                if not isinstance(cell, str) or not 1 <= len(cell) <= 64 or not math.isfinite(float(cell)):
                    raise ValueError(DEPENDENCY)


def report_check(value: dict[str, Any], config: dict[str, Any]) -> None:
    if config.get("mode") == "SEARCH_PROJECTION" and value.get("kind") == "SearchProjection":
        projection_check(value, config)
        return
    require(set(value) == {"policy_version", "quality", "blocking_code", "precision_bits", "fit_summary", "model_evaluation"}, DEPENDENCY)
    require(value["policy_version"] == POLICY and type(value["precision_bits"]) is int and value["precision_bits"] == 53, DEPENDENCY)
    require(value["quality"] in {"PASS", "BLOCKED"}, DEPENDENCY)
    if value["quality"] == "BLOCKED":
        require(value["blocking_code"] == "DATA_QUALITY_BLOCKED" and value["fit_summary"] is None and value["model_evaluation"] is None, DEPENDENCY)
        return
    require(value["blocking_code"] is None, DEPENDENCY)
    split = config["research"]["observation_split"]
    fit_check(value["fit_summary"], len(split["fit"]))
    model = value["model_evaluation"]
    if config["model"] is None:
        require(model is None, DEPENDENCY)
        return
    require(set(model) == {"fit", "development"}, DEPENDENCY)
    for name in model:
        metrics_check(model[name], len(split[name]))


def decode_report(raw: bytes, config: dict[str, Any]) -> dict[str, Any]:
    try:
        result: dict[str, Any] = json.loads(raw)
        require(type(result) is dict, DEPENDENCY)
        if result.get("status") == "REJECTED":
            code = result.get("code")
            if not isinstance(code, str) or code not in CODES:
                from ingestion.limits import ImportRejected
                raise ImportRejected(DEPENDENCY)
            from ingestion.limits import ImportRejected
            raise ImportRejected(code)
        require(set(result) == {"status", "report"} and result["status"] == "PASS", DEPENDENCY)
        report: dict[str, Any] = result["report"]
        report_check(report, config)
        return report
    except (ValueError, TypeError, KeyError, ZeroDivisionError, RecursionError) as error:
        from ingestion.limits import ImportRejected
        if isinstance(error, ImportRejected):
            raise
        raise ImportRejected(DEPENDENCY) from error
