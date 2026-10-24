"""配對 bootstrap 比較層的獨立單元測試；不讀資料庫、不碰曝光，也不經 DSL。

Independent unit tests for the paired-bootstrap comparison layer: the practical-equivalence
scale, the deterministic resampling interval and the mapping from an interval to an outcome."""
from fractions import Fraction
from unittest import TestCase
from mathematics.comparison import baseline_losses, bound, classify, interval, scale

SEED = 7
REPLICATES = 64


class ScaleTests(TestCase):
    def test_takes_the_larger_of_iqr_and_resolution(self) -> None:
        """尺度取 fit IQR 與量測解析度較大者；解析度只補更細的位數，不取代訓練尺度。"""
        self.assertEqual(scale(Fraction(5), Fraction(1, 10), None), Fraction(5))
        self.assertEqual(scale(Fraction(1, 10), Fraction(5), None), Fraction(5))

    def test_zero_scale_needs_a_registered_positive_override(self) -> None:
        """兩項皆零時沒有可比較的帶寬；只有預先註冊的正覆寫值能確立尺度。"""
        self.assertIsNone(scale(Fraction(0), Fraction(0), None))
        self.assertEqual(scale(Fraction(0), Fraction(0), "0.5"), Fraction(1, 2))


class BoundTests(TestCase):
    def test_bound_is_the_scale_times_the_policy_ratio(self) -> None:
        """實務邊界為尺度乘上政策比例，比例在建立版本時已限定於 (0,1]。"""
        self.assertEqual(bound(Fraction(5), Fraction(1, 100)), Fraction(1, 20))


class BaselineLossTests(TestCase):
    def test_constant_prediction_scores_every_target(self) -> None:
        """baseline 是固定預測值，逐列損失即它對每個 final 目標的絕對誤差。"""
        self.assertEqual(baseline_losses(Fraction(6), [1.0, -2.0]), [5.0, 8.0])


class IntervalTests(TestCase):
    def test_repeated_call_is_identical_and_seed_sensitive(self) -> None:
        """同一政策與同一批列必須重算出同一區間；換 seed 即換一組索引。"""
        candidate, baseline = [1.0, 4.0, 2.5, 9.0], [3.0] * 4
        first = interval(candidate, baseline, SEED, REPLICATES)
        self.assertEqual(first, interval(candidate, baseline, SEED, REPLICATES))
        self.assertNotEqual(first, interval(candidate, baseline, SEED + 1, REPLICATES))

    def test_degenerate_difference_collapses_to_a_point(self) -> None:
        """逐列損失差全相同時，任何重抽樣都得到同一均值，區間退化為該點。"""
        self.assertEqual(interval([0.0, 0.0, 0.0], [10.0, 10.0, 10.0], SEED, REPLICATES), (Fraction(-10), Fraction(-10)))

    def test_pairing_keeps_both_ends_of_mixed_differences(self) -> None:
        """候選與 baseline 共用同一組索引：混合差的正負兩端都不會被互相平均掉。"""
        self.assertEqual(interval([0.0, 10.0], [10.0, 0.0], SEED, REPLICATES), (Fraction(-10), Fraction(10)))


class ClassifyTests(TestCase):
    def test_interval_position_selects_exactly_one_outcome(self) -> None:
        """全低於 -margin 才支持候選；全高於 +margin 反證；全在帶內稱等效；跨越即無法下結論。"""
        margin = Fraction(1, 2)
        cases = ((Fraction(-1), Fraction(-3, 4), "SUPPORTED"), (Fraction(3, 4), Fraction(1), "FALSIFIED"),
                 (Fraction(-1, 4), Fraction(1, 4), "AMBIGUOUS"), (Fraction(-1, 2), Fraction(1, 2), "AMBIGUOUS"),
                 (Fraction(-1), Fraction(1), "INSUFFICIENT_EVIDENCE"), (Fraction(-1), Fraction(0), "INSUFFICIENT_EVIDENCE"),
                 (Fraction(-1), Fraction(-1, 2), "INSUFFICIENT_EVIDENCE"))
        for lower, upper, expected in cases:
            with self.subTest(lower=lower, upper=upper):
                self.assertEqual(classify(lower, upper, margin), expected)
