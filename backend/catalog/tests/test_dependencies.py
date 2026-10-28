"""單序列時間／群組的洩漏反例；不以 IID 測試替代相依性驗證。"""
from fractions import Fraction
from unittest import TestCase
from ingestion.dependencies import DependencyGuard, group_token, time_value
from ingestion.limits import ImportRejected
from runtime.contracts import identity_hash


def split(kind: str = "EXPLICIT") -> dict[str, object]:
    return {"kind": kind, "fit": [0, 1], "development": [2, 3], "final_test": [4, 5],
        "gap_rows": 0, "lookback_rows": 0, "horizon_rows": 0, "time_column": "t" if kind == "TIME_ORDERED" else None,
        "group_assignment_digest": identity_hash([[i, "s:" + "ABC"[i // 2], ("fit", "development", "final_test")[i // 2]] for i in range(6)])}


class DependencyTests(TestCase):
    def test_time_order_and_iso_offset_equivalence(self) -> None:
        guard = DependencyGuard({}, split("TIME_ORDERED"), 6)
        for i in range(6):
            guard.observe(i, ["t"], [i])
        self.assertTrue(guard.valid())
        self.assertEqual(time_value("2026-10-28T08:00:00+08:00"), time_value("2026-10-28T00:00:00Z"))
        self.assertEqual(time_value("0.25"), Fraction(1, 4))

    def test_duplicate_backward_and_naive_time_are_blocked(self) -> None:
        for value in (0, -1, "2026-10-28T00:00:00", "not-a-time", float("nan")):
            guard = DependencyGuard({}, split("TIME_ORDERED"), 6)
            guard.observe(0, ["t"], [0])
            guard.observe(1, ["t"], [value])
            self.assertFalse(guard.valid(), value)

    def test_gap_is_explicit_and_covers_dependencies(self) -> None:
        data = split("TIME_ORDERED")
        data.update(fit=[0, 1], development=[4, 5], final_test=[8, 9], gap_rows=2, lookback_rows=1, horizon_rows=1)
        guard = DependencyGuard({}, data, 10)
        for i in range(10):
            guard.observe(i, ["t"], [i])
        self.assertTrue(guard.valid())
        data["horizon_rows"] = 2
        with self.assertRaises(ImportRejected):
            DependencyGuard({}, data, 10)

    def test_gap_cannot_hide_arbitrary_dropped_rows(self) -> None:
        data = split("TIME_ORDERED")
        data.update(fit=[0, 2], development=[3, 4], final_test=[5, 6])
        with self.assertRaises(ImportRejected):
            DependencyGuard({}, data, 7)

    def test_group_digest_uses_real_values_and_disjoint_groups(self) -> None:
        guard = DependencyGuard({"group_column": "g"}, split("GROUPED_ROWS"), 6)
        for i in range(6):
            guard.observe(i, ["g"], ["ABC"[i // 2]])
        self.assertTrue(guard.valid())
        self.assertEqual(group_token(1), group_token(1.0))
        self.assertNotEqual(group_token("01"), group_token(1))

    def test_group_cross_partition_and_forged_digest_are_blocked(self) -> None:
        for values in (["A", "A", "B", "B", "A", "A"], ["X"] * 6):
            guard = DependencyGuard({"group_column": "g"}, split("GROUPED_ROWS"), 6)
            for i, value in enumerate(values):
                guard.observe(i, ["g"], [value])
            self.assertFalse(guard.valid())
        data = split("GROUPED_ROWS")
        data["group_assignment_digest"] = "0" * 64
        guard = DependencyGuard({"group_column": "g"}, data, 6)
        for i in range(6):
            guard.observe(i, ["g"], ["ABC"[i // 2]])
        self.assertFalse(guard.valid())
