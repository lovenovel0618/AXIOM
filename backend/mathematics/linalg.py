"""列主元 Householder QR 最小平方：不組 normal equation，退化時回報而不硬給唯一解。
只做確定性的 float64 運算，不含隨機與牆鐘時間；非有限輸入一律拒絕。

Column-pivoted Householder QR least squares with an explicit rank diagnostic."""
from collections.abc import Sequence
from dataclasses import dataclass
import math

RANK_TOLERANCE = 1e-12


@dataclass(frozen=True)
class LeastSquares:
    """`coefficients` 依原始行序回傳，且只在滿行秩時給值；其餘一律 None。"""
    coefficients: tuple[float, ...] | None
    rank: int
    columns: int
    pivots: int


def _finite(value: float) -> float:
    if not math.isfinite(value):
        raise ValueError("NON_FINITE_SYSTEM")
    return value


def _reflect(work: list[list[float]], rhs: list[float], k: int, length: float, rows: int, columns: int) -> float:
    """套用單一步 Householder 反射；運算及迭代順序與原求解器一致。"""
    vector = [work[index][k] for index in range(k, rows)]
    alpha = -length if vector[0] >= 0 else length
    vector[0] -= alpha
    square = math.fsum(value * value for value in vector)
    beta = 0 if square == 0 else 2 / square
    for column in range(k + 1, columns):
        dot = math.fsum(vector[index - k] * work[index][column] for index in range(k, rows))
        for index in range(k, rows):
            work[index][column] = _finite(work[index][column] - beta * vector[index - k] * dot)
    projection = math.fsum(vector[index - k] * rhs[index] for index in range(k, rows))
    for index in range(k, rows):
        rhs[index] = _finite(rhs[index] - beta * vector[index - k] * projection)
    return alpha


def _pivot(work: list[list[float]], norms: list[float], order: list[int], k: int, best: int) -> int:
    """按原順序交換主元行、範數與索引；回傳本步是否發生交換。"""
    if best == k:
        return 0
    for row in work:
        row[k], row[best] = row[best], row[k]
    norms[k], norms[best] = norms[best], norms[k]
    order[k], order[best] = order[best], order[k]
    return 1


def solve(matrix: Sequence[Sequence[float]], target: Sequence[float]) -> LeastSquares:
    """解 min ||A x - b||；A 為列乘行，rank 不足時不強行給唯一參數。"""
    rows = len(matrix)
    columns = len(matrix[0]) if rows else 0
    if len(target) != rows or any(len(row) != columns for row in matrix):
        raise ValueError("RAGGED_SYSTEM")
    work = [[_finite(value) for value in row] for row in matrix]
    rhs = [_finite(value) for value in target]
    if columns == 0:
        return LeastSquares((), 0, 0, 0)
    norms = [math.fsum(value * value for value in column) for column in zip(*work, strict=True)]
    order = list(range(columns))
    pivots = 0
    diagonal: list[float] = []
    for k in range(min(rows, columns)):
        best = max(range(k, columns), key=lambda index: norms[index])
        pivots += _pivot(work, norms, order, k, best)
        length = math.sqrt(norms[k])
        if length == 0:
            break
        alpha = _reflect(work, rhs, k, length, rows, columns)
        work[k][k] = alpha
        diagonal.append(alpha)
        for column in range(k + 1, columns):
            norms[column] = max(0, norms[column] - work[k][column] * work[k][column])
    tolerance = RANK_TOLERANCE * abs(diagonal[0]) if diagonal else 0
    rank = sum(1 for value in diagonal if abs(value) > tolerance)
    if rank != columns:
        return LeastSquares(None, rank, columns, pivots)
    solution = [0.0] * columns
    for k in range(columns - 1, -1, -1):
        total = math.fsum(work[k][column] * solution[column] for column in range(k + 1, columns))
        solution[k] = _finite((rhs[k] - total) / work[k][k])
    result = [0.0] * columns
    for k, index in enumerate(order):
        result[index] = solution[k]
    return LeastSquares(tuple(result), rank, columns, pivots)
