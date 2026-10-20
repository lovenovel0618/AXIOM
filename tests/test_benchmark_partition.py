"""Synthetic case-level partition boundaries, separate from within-case row splits."""
from dataclasses import replace
import unittest

from tools.benchmark.partition import PartitionEntry, validate_partitions


class BenchmarkPartitionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.training = PartitionEntry("synthetic-a", "synthetic-family-a", "synthetic-source-a", "TRAIN")

    def test_same_family_in_same_partition_is_valid(self) -> None:
        second = replace(self.training, case_id="synthetic-b")
        sealed = PartitionEntry("synthetic-c", "synthetic-family-c", "synthetic-source-c", "SEALED_TEST")
        validate_partitions([self.training, second, sealed])

    def test_family_cannot_cross_partitions_even_with_a_different_source(self) -> None:
        sealed = replace(self.training, case_id="synthetic-b", source_group="synthetic-source-b", partition="SEALED_TEST")
        with self.assertRaisesRegex(ValueError, "crosses"):
            validate_partitions([self.training, sealed])

    def test_source_cannot_cross_partitions_even_with_a_different_family(self) -> None:
        development = replace(self.training, case_id="synthetic-b", family_id="synthetic-family-b", partition="DEVELOPMENT")
        with self.assertRaisesRegex(ValueError, "crosses"):
            validate_partitions([self.training, development])

    def test_family_and_source_namespaces_are_distinct(self) -> None:
        first = replace(self.training, family_id="synthetic-shared")
        sealed = PartitionEntry("synthetic-b", "synthetic-family-b", "synthetic-shared", "SEALED_TEST")
        validate_partitions([first, sealed])

    def test_duplicate_empty_invalid_or_noncanonical_assignments_are_rejected(self) -> None:
        malformed = [replace(self.training, partition="UNKNOWN"), replace(self.training, family_id=""),
                     replace(self.training, source_group=" "), replace(self.training, case_id=" synthetic-a")]
        for entry in malformed:
            with self.subTest(entry=entry), self.assertRaises(ValueError):
                validate_partitions([entry])
        with self.assertRaises(ValueError):
            validate_partitions([])
        with self.assertRaises(ValueError):
            validate_partitions([self.training, self.training])


if __name__ == "__main__":
    unittest.main()
