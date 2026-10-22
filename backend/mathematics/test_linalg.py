"""Independent exact references and degenerate inputs for the least-squares kernel."""
from fractions import Fraction
from unittest import TestCase
from mathematics.linalg import LeastSquares, solve


def normal_equations(matrix: list[list[float]], target: list[float]) -> list[Fraction]:
    """獨立參考解：以精確有理數另走一遍 normal equation，只求與實作路徑不同來源。"""
    columns = len(matrix[0])
    gram = [[Fraction(0) for _ in range(columns)] for _ in range(columns)]
    projection = [Fraction(0) for _ in range(columns)]
    for row, value in zip(matrix, target, strict=True):
        for left in range(columns):
            projection[left] += Fraction(row[left]) * Fraction(value)
            for right in range(columns):
                gram[left][right] += Fraction(row[left]) * Fraction(row[right])
    for pivot in range(columns):
        best = max(range(pivot, columns), key=lambda index: abs(gram[index][pivot]))
        gram[pivot], gram[best] = gram[best], gram[pivot]
        projection[pivot], projection[best] = projection[best], projection[pivot]
        for row in range(pivot + 1, columns):
            factor = gram[row][pivot] / gram[pivot][pivot]
            for column in range(pivot, columns):
                gram[row][column] -= factor * gram[pivot][column]
            projection[row] -= factor * projection[pivot]
    result = [Fraction(0)] * columns
    for index in range(columns - 1, -1, -1):
        total = sum(gram[index][column] * result[column] for column in range(index + 1, columns))
        result[index] = (projection[index] - total) / gram[index][index]
    return result


class LeastSquaresTests(TestCase):
    def test_exact_line_is_recovered_without_residual(self) -> None:
        result = solve([[1.0, 1.0], [1.0, 2.0], [1.0, 3.0]], [2.0, 3.0, 4.0])
        self.assertEqual((result.rank, result.columns), (2, 2))
        self.assertIsNotNone(result.coefficients)
        assert result.coefficients is not None
        self.assertEqual([round(value, 12) for value in result.coefficients], [1.0, 1.0])

    def test_overdetermined_system_matches_exact_rational_reference(self) -> None:
        matrix = [[1.0, 0.0], [1.0, 1.0], [1.0, 2.0], [1.0, 4.0]]
        target = [1.5, 2.0, 3.5, 6.0]
        reference = normal_equations(matrix, target)
        result = solve(matrix, target)
        assert result.coefficients is not None
        for value, expected in zip(result.coefficients, reference, strict=True):
            self.assertLess(abs(value - float(expected)), 1e-12)

    def test_rank_deficient_system_reports_instead_of_forcing_a_solution(self) -> None:
        result = solve([[1.0, 2.0], [2.0, 4.0], [3.0, 6.0]], [1.0, 2.0, 3.0])
        self.assertIsNone(result.coefficients)
        self.assertEqual((result.rank, result.columns), (1, 2))

    def test_column_pivot_moves_the_zero_column_out_of_the_way(self) -> None:
        result = solve([[0.0, 1.0], [0.0, 1.0], [1.0, 1.0]], [1.0, 1.0, 2.0])
        self.assertEqual((result.pivots, result.rank), (1, 2))
        assert result.coefficients is not None
        self.assertEqual([round(value, 9) for value in result.coefficients], [1.0, 1.0])

    def test_degenerate_column_set_reports_rank_instead_of_a_solution(self) -> None:
        result = solve([[0.0, 1.0], [0.0, 1.0], [0.0, 1.0]], [2.0, 2.0, 2.0])
        self.assertIsNone(result.coefficients)
        self.assertEqual((result.pivots, result.rank, result.columns), (1, 1, 2))

    def test_empty_column_set_is_a_trivial_system(self) -> None:
        self.assertEqual(solve([], []), LeastSquares((), 0, 0, 0))

    def test_ragged_and_non_finite_inputs_are_rejected(self) -> None:
        with self.assertRaises(ValueError) as ragged:
            solve([[1.0, 2.0], [3.0]], [1.0, 2.0])
        self.assertEqual(str(ragged.exception), "RAGGED_SYSTEM")
        with self.assertRaises(ValueError) as short:
            solve([[1.0, 2.0]], [1.0, 2.0])
        self.assertEqual(str(short.exception), "RAGGED_SYSTEM")
        with self.assertRaises(ValueError) as infinite:
            solve([[1.0, float("inf")], [1.0, 1.0]], [1.0, 2.0])
        self.assertEqual(str(infinite.exception), "NON_FINITE_SYSTEM")
