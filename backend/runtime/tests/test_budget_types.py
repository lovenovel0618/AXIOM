"""資源型別的執行期邊界與增量算術反例。"""
from unittest import TestCase
from runtime.budget_types import accumulated, exceeds, read_limit, read_usage, zero_usage


class BudgetTypeTests(TestCase):
    def test_rejects_bool_float_string_and_out_of_range(self) -> None:
        for invalid in (True,1.5,"1",-1,2**53):
            with self.subTest(value=invalid):
                row = dict(zero_usage(),cpu_seconds=invalid)
                with self.assertRaises(ValueError):
                    read_usage(row)

    def test_rejects_missing_and_unknown_fields(self) -> None:
        for row in ({"cpu_seconds":1},dict(zero_usage(),cpu_second=1)):
            with self.assertRaises(ValueError):
                read_usage(row)

    def test_rejects_impossible_candidate_counts(self) -> None:
        row = dict(zero_usage(),candidates_accepted=1)
        with self.assertRaises(ValueError):
            read_usage(row)

    def test_increments_counters_and_takes_memory_maximum(self) -> None:
        account,previous,current = zero_usage(),zero_usage(),zero_usage()
        account.update(cpu_seconds=8,peak_memory_bytes=300)
        previous.update(cpu_seconds=3,peak_memory_bytes=100)
        current.update(cpu_seconds=5,peak_memory_bytes=200)
        result = accumulated(account,previous,current)
        self.assertEqual(result["cpu_seconds"],10)
        self.assertEqual(result["peak_memory_bytes"],300)
        self.assertEqual(account["cpu_seconds"],8)

    def test_rejects_decreasing_and_overflowing_totals(self) -> None:
        account,previous,current = zero_usage(),zero_usage(),zero_usage()
        previous["cpu_seconds"] = 1
        with self.assertRaises(ValueError):
            accumulated(account,previous,current)
        account["cpu_seconds"],current["cpu_seconds"] = 2**53-1,2
        empty = zero_usage()
        with self.assertRaises(ValueError):
            accumulated(account,empty,current)

    def test_limit_validation_and_true_overrun(self) -> None:
        limit = read_limit({"cpu_seconds":10,"gpu_seconds":0,"tokens":0,"memory_bytes":100,"wall_seconds":20,"candidate_limit":0})
        usage = zero_usage()
        self.assertFalse(exceeds(usage,limit))
        usage["cpu_seconds"] = 11
        self.assertTrue(exceeds(usage,limit))
        bad = dict(limit,memory_bytes=True)
        with self.assertRaises(ValueError):
            read_limit(bad)
