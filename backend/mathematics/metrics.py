"""離線評分：以固定分母的 MAE／RMSE 對 fit／development 列評分，失敗列不從分母消失。
研究檢視與 SEARCH 執行器共用同一份計分，不含 final_test 或任何預算帳本語意。

Shared float64 scoring for fit/development rows."""
from collections.abc import Sequence
from fractions import Fraction
import math
from typing import Any
from mathematics.compiler import Plan
from mathematics.evaluator import evaluate


def quantile(values: list[Fraction], probability: Fraction) -> Fraction:
    position = (len(values) - 1) * probability
    left = position.numerator // position.denominator
    right = min(left + 1, len(values) - 1)
    return values[left] + (values[right] - values[left]) * (position - left)


def residuals(plan: Plan, parameters: dict[str, str], alias: str, pairs: Sequence[tuple[float, float]]) -> list[tuple[float, float]]:
    """逐列回（目標值, 絕對誤差）；無法評分的列不進分母，也不出現在序列中。

    與 `score` 共用同一份求值走訪與同一條有效性規則；輸出順序與輸入列一致，因此覆蓋完整時
    能與 baseline 逐列配對，而不必重算或另存。"""
    points = evaluate(plan, [{alias: pair[0]} for pair in pairs], parameters).points
    matched: list[tuple[float, float]] = []
    for point, pair in zip(points, pairs, strict=True):
        if point.valid_mask and point.value is not None and math.isfinite(point.value - pair[1]):
            matched.append((pair[1], abs(point.value - pair[1])))
    return matched


def score(plan: Plan, parameters: dict[str, str], alias: str, pairs: Sequence[tuple[float, float]]) -> dict[str, Any]:
    """以 (x, y) 對評分；`mae`／`rmse` 只在全部列有效時給值，空集合不宣稱覆蓋率。"""
    differences = [loss for _target, loss in residuals(plan, parameters, alias, pairs)]
    selected, valid = len(pairs), len(differences)
    result: dict[str, Any] = {"selected_count": selected, "valid_count": valid, "failed_count": selected - valid,
        "coverage": None if selected == 0 else str(Fraction(valid, selected)), "mae": None, "rmse": None}
    if selected and valid == selected:
        scale = max(differences)
        mae = 0 if scale == 0 else scale * min(1.0, math.fsum(value / scale / selected for value in differences))
        result["mae"] = format(mae, ".17g")
        rmse = 0 if scale == 0 else scale * math.sqrt(min(1.0, math.fsum((value / scale) ** 2 / selected for value in differences)))
        result["rmse"] = format(rmse, ".17g")
    return result


def metrics(plan: Plan, parameters: dict[str, str], rows: list[tuple[Fraction, float, float]], alias: str) -> dict[str, Any]:
    """研究檢視用的 (exact_y, x, y) 列；評分只看 x 與 y，精確值不參與。"""
    return score(plan, parameters, alias, [(row[1], row[2]) for row in rows])
