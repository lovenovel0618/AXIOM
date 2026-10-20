"""Public mathematical references, denominator integrity and projection regressions."""
from __future__ import annotations

from contextlib import redirect_stdout
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction
import io
import json
import math
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from tools.benchmark import public_oracle as oracle


class PublicOracleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.document = oracle.load_document(oracle.DEFAULT_SUITE)

    def test_four_public_references_are_reproduced(self) -> None:
        cases = oracle.load_cases(self.document)
        results = [oracle.HANDLERS[case.identifier](case) for case in cases]
        self.assertEqual(len(results), 4)
        self.assertTrue(all(result["status"] == "PASS" for result in results))
        self.assertEqual(results[1]["score"]["failed_count"], 1)
        self.assertFalse(results[1]["score"]["passed"])
        self.assertFalse(results[2]["unique"])
        self.assertFalse(results[3]["randomness_proven"])
        self.assertEqual(results[3]["candidate"]["mae"], 10)
        self.assertAlmostEqual(results[3]["candidate"]["rmse"], math.sqrt(101))

    def test_missing_predictions_preserve_full_denominator_and_original_ids(self) -> None:
        result = oracle.score([1, 2, 3], [oracle.Prediction(1)], row_ids=[8, 10, 20])
        self.assertEqual((result.selected_count, result.valid_count, result.failed_count), (3, 1, 2))
        self.assertEqual(result.failed_rows, (10, 20))
        self.assertEqual(result.failure_counts, {oracle.MISSING: 2})
        self.assertEqual(result.coverage, 1 / 3)
        self.assertEqual(result.mae, 0)
        self.assertFalse(result.passed)

    def test_all_failed_and_empty_sets_have_null_metrics(self) -> None:
        for observed, predicted in (([1], [oracle.Prediction(None, oracle.DOMAIN_ERROR)]), ([], [])):
            with self.subTest(observed=observed):
                result = oracle.score(observed, predicted)
                self.assertIsNone(result.mae)
                self.assertIsNone(result.rmse)
                self.assertEqual(result.coverage, 0)
                self.assertFalse(result.passed)

    def test_nonfinite_predictions_and_residual_overflow_are_failed_rows(self) -> None:
        for value in (float("nan"), float("inf"), -float("inf"), 1e308):
            with self.subTest(value=value):
                result = oracle.score([-1e308], [oracle.Prediction(value)])
                self.assertEqual(result.failure_counts, {oracle.NON_FINITE: 1})
                self.assertFalse(result.passed)
                self.assertIsNone(result.rmse)

    def test_large_representable_errors_do_not_overflow_squared_metrics(self) -> None:
        result = oracle.score([1e308, 1e308], [oracle.Prediction(0), oracle.Prediction(0)])
        self.assertEqual(result.mae, 1e308)
        self.assertEqual(result.rmse, 1e308)
        self.assertFalse(result.passed)

    def test_tolerance_is_pointwise_and_uses_the_larger_scale(self) -> None:
        accepted = oracle.score([100], [oracle.Prediction(101)], atol=0, rtol=0.01)
        rejected = oracle.score([100, 1], [oracle.Prediction(100), oracle.Prediction(2)], atol=0, rtol=0.01)
        self.assertTrue(accepted.passed)
        self.assertFalse(rejected.passed)

    def test_invalid_observations_tolerance_or_prediction_shape_are_rejected(self) -> None:
        zero = [oracle.Prediction(0)]
        one = [oracle.Prediction(1)]
        excess = [oracle.Prediction(1), oracle.Prediction(2)]
        huge = [oracle.Prediction(1e308)]
        inconsistent = [oracle.Prediction(1, oracle.DOMAIN_ERROR)]
        unknown = [oracle.Prediction(None, "invented")]
        for value in (True, float("nan"), float("inf"), 10 ** 1000):
            label = str(value)[:20]
            with self.subTest(value=label), self.assertRaises(ValueError):
                oracle.score([value], zero)
        for tolerance in (-1, float("inf"), float("nan"), True):
            with self.subTest(tolerance=tolerance), self.assertRaises(ValueError):
                oracle.score([1], one, atol=tolerance)
        with self.assertRaises(ValueError):
            oracle.score([1], excess)
        with self.assertRaises(ValueError):
            oracle.score([1e308], huge, rtol=1e308)
        with self.assertRaises(ValueError):
            oracle.score([1], inconsistent)
        with self.assertRaises(ValueError):
            oracle.score([1], unknown)

    def test_invalid_scoring_ids_cannot_hide_rows(self) -> None:
        predictions = [oracle.Prediction(1), oracle.Prediction(2)]
        for rows in ([0, 0], [True, 1], [-1, 1], [1]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                oracle.score([1, 2], predictions, row_ids=rows)

    def test_source_data_and_expectations_cannot_redefine_the_oracle(self) -> None:
        for index, field, value in ((0, "y", [0] * 10), (1, "x", [-2, 0, 1]),
                                    (2, "y", [0] * 5), (3, "y", [0] * 10)):
            with self.subTest(index=index, field=field):
                document = deepcopy(self.document)
                document["cases"][index][field] = value
                cases = oracle.load_cases(document)
                with self.assertRaises(ValueError):
                    oracle.HANDLERS[cases[index].identifier](cases[index])
        for index in range(4):
            with self.subTest(index=index):
                document = deepcopy(self.document)
                document["cases"][index]["expected"]["extra"] = 0
                case = oracle.load_cases(document)[index]
                with self.assertRaises(ValueError):
                    oracle.HANDLERS[case.identifier](case)

    def test_numeric_masks_cannot_impersonate_boolean_validity(self) -> None:
        self.document["cases"][1]["expected"]["valid_mask"] = [1, 0, 1]
        case = oracle.load_cases(self.document)[1]
        with self.assertRaises(ValueError):
            oracle.domain_case(case)

    def test_unknown_candidate_or_secret_fields_are_rejected(self) -> None:
        for field, value in (("candidate", "__import__('os')"), ("secret", "canary")):
            with self.subTest(field=field):
                document = deepcopy(self.document)
                document["cases"][0][field] = value
                with self.assertRaises(ValueError):
                    oracle.load_cases(document)

    def test_split_overlap_duplicates_reordering_bool_or_out_of_range_are_rejected(self) -> None:
        for rows in ([6, 6], [5, 7], [7, 6], [True, 7], [6, 100], []):
            with self.subTest(rows=rows):
                document = deepcopy(self.document)
                document["cases"][0]["development"] = rows
                with self.assertRaises(ValueError):
                    oracle.load_cases(document)

    def test_private_visibility_duplicates_and_unknown_cases_are_rejected(self) -> None:
        private = deepcopy(self.document)
        private["visibility"] = "SEALED_TEST"
        with self.assertRaises(ValueError):
            oracle.load_cases(private)
        self.document["cases"][1] = deepcopy(self.document["cases"][0])
        with self.assertRaises(ValueError):
            oracle.load_cases(self.document)

    def test_boolean_nonfinite_observations_and_relaxed_policy_are_rejected(self) -> None:
        for field, value in (("atol", 1), ("rtol", True), ("version", "2.0")):
            with self.subTest(field=field):
                document = deepcopy(self.document)
                document[field] = value
                with self.assertRaises(ValueError):
                    oracle.load_cases(document)
        for value in (True, float("inf")):
            document = deepcopy(self.document)
            document["cases"][0]["x"][0] = value
            with self.assertRaises(ValueError):
                oracle.load_cases(document)

    def test_json_duplicates_constants_and_non_objects_are_rejected(self) -> None:
        for content in (b'{"x":1,"x":2}', b'{"x":NaN}', b'[]', b'{'):
            with self.subTest(content=content), self.assertRaises(ValueError):
                oracle.decode_document(content)
        with self.assertRaises(ValueError):
            oracle.decode_document(b' ' * (2 * 1024 * 1024 + 1))

    def test_sine_reference_is_independent_and_bounded(self) -> None:
        for point in (Fraction(-1), Fraction(1, 10), Fraction(1)):
            self.assertAlmostEqual(float(oracle.sine_reference(point)), math.sin(float(point)), places=15)
        outside = Fraction(2)
        with self.assertRaises(ValueError):
            oracle.sine_reference(outside)

    def test_solver_projection_is_a_whitelist_and_does_not_modify_input(self) -> None:
        original = deepcopy(self.document)
        cases = oracle.load_cases(self.document)
        projection = oracle.solver_projection(cases)
        self.assertEqual(self.document, original)
        self.assertEqual(len(projection["cases"]), 2)
        for case in projection["cases"]:
            self.assertEqual(set(case), {"case_id", "observations"})
            self.assertEqual(set(case["observations"]), {"fit", "development"})
            for rows in case["observations"].values():
                self.assertTrue(all(set(row) == {"row_id", "x", "y"} for row in rows))
                self.assertTrue(all(row["row_id"] < 8 for row in rows))
        serialized = json.dumps(projection)
        for forbidden in ("expected", "candidate", "baseline", "final_test"):
            self.assertNotIn(forbidden, serialized)
        projection["cases"][0]["observations"]["fit"][0]["y"] = 999
        self.assertEqual(cases[0].y[0], 1)

    def test_projection_revalidates_mutated_split_mappings(self) -> None:
        case = oracle.load_cases(self.document)[0]
        case.splits["fit"] = tuple(range(10))
        with self.assertRaises(ValueError):
            oracle.solver_projection([case])

    def test_cli_report_failure_does_not_remain_pass_or_corrupt_source(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "suite.json"
            source.write_text(json.dumps(self.document), encoding="utf-8")
            original = source.read_bytes()
            cases = ((["--output", str(source)], "Output paths"),
                     (["--projection-output", str(root / "absent/projection.json")], "No such file"),
                     (["--output", str(root / "absent/report.json")], "unable to write"))
            for arguments, error in cases:
                stdout = io.StringIO()
                with self.subTest(arguments=arguments), patch("sys.argv", ["oracle", "--suite", str(source), *arguments]), redirect_stdout(stdout):
                    self.assertEqual(oracle.main(), 1)
                report = json.loads(stdout.getvalue())
                self.assertEqual(report["status"], "FAIL")
                self.assertIn(error, str(report["errors"]))
                self.assertEqual(source.read_bytes(), original)

    def test_cli_rejects_hardlinked_output_without_overwriting_source(self) -> None:
        with TemporaryDirectory() as temporary:
            source = Path(temporary) / "suite.json"
            source.write_text(json.dumps(self.document), encoding="utf-8")
            alias = Path(temporary) / "alias.json"
            alias.hardlink_to(source)
            original = source.read_bytes()
            stdout = io.StringIO()
            with patch("sys.argv", ["oracle", "--suite", str(source), "--output", str(alias)]), redirect_stdout(stdout):
                self.assertEqual(oracle.main(), 1)
            self.assertEqual(source.read_bytes(), original)
            self.assertEqual(json.loads(stdout.getvalue())["status"], "FAIL")

    def test_cli_rejects_incorrect_metric_implementation(self) -> None:
        original_score = oracle.score

        def incorrect_score(*_args: object, **_kwargs: object) -> oracle.Score:
            return replace(original_score([1], [oracle.Prediction(1)]), mae=99)

        stdout = io.StringIO()
        with patch.object(oracle, "score", side_effect=incorrect_score), patch("sys.argv", ["oracle"]), redirect_stdout(stdout):
            self.assertEqual(oracle.main(), 1)
        self.assertEqual(json.loads(stdout.getvalue())["status"], "FAIL")

    def test_cli_reproduces_from_another_working_directory(self) -> None:
        with TemporaryDirectory() as temporary:
            result = subprocess.run([sys.executable, str(Path(oracle.__file__).resolve())], cwd=temporary,
                                    text=True, capture_output=True, timeout=15, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["scope"], "PUBLIC_REFERENCE_ONLY")
            self.assertEqual(report["product_status"], "NOT_RUN")


if __name__ == "__main__":
    unittest.main()
