"""Three-strategy search against independent references, dedup, diagnostics and manifest limits."""
from dataclasses import fields
from fractions import Fraction
import math
from unittest import TestCase
from mathematics.search import (HARMONIC, LINEAR, MANIFESTS, NOT_APPLICABLE, POLYNOMIAL, Domain, Request, Variable,
    manifest, search)
from mathematics.syntax import DslError
from runtime.contracts import JsonObject

DIMENSIONLESS = (0,) * 7


def request(fit: list[tuple[float, float]], development: list[tuple[float, float]] | None = None) -> Request:
    """固定域與無量綱單位的離線請求；介面沒有 final_test 欄位。"""
    return Request(Variable("x", DIMENSIONLESS), DIMENSIONLESS, Domain(Fraction(-1000), Fraction(1000), True, True),
        tuple(fit), tuple(development or []))


def strategy(report: JsonObject, family: str) -> JsonObject:
    found = [entry for entry in report["strategies"] if entry["family"] == family]
    assert len(found) == 1
    return found[0]


def codes(entry: JsonObject) -> list[str]:
    return [note["code"] for note in entry["diagnostics"]]


def sources(candidate: JsonObject) -> list[str]:
    return [origin["source"] for origin in candidate["origins"]]


class SearchTests(TestCase):
    def test_exact_line_is_recovered_by_the_least_squares_variant(self) -> None:
        report = search(request([(-1.0, 5.0), (0.0, 3.0), (1.0, 1.0)], [(2.0, -1.0), (3.0, -3.0)]))
        best = report["candidates"][0]
        self.assertIn("linear-fit:least-squares", sources(best))
        self.assertEqual(best["development"], {"selected_count": 2, "valid_count": 2, "failed_count": 0,
            "coverage": "1", "mae": "0", "rmse": "0"})
        self.assertEqual(best["dsl"]["parameters"], [
            {"name": "c0", "unit": [0]*7, "lower": "3", "upper": "3"},
            {"name": "c1", "unit": [0]*7, "lower": "-2", "upper": "-2"}])
        self.assertEqual([entry["plugin_id"] for entry in report["strategies"]], ["linear-fit", "polynomial-fit", "harmonic-fit"])

    def test_least_squares_intercept_is_back_transformed_from_a_nonzero_centre(self) -> None:
        report = search(request([(-2.0, 7.0), (-1.0, 5.0), (0.0, 3.0), (1.0, 1.0), (2.0, -1.0), (3.0, -3.0)],
            [(4.0, -5.0), (5.0, -7.0)]))
        produced = [entry for entry in report["candidates"] if "linear-fit:least-squares" in sources(entry)]
        self.assertEqual(len(produced), 1)
        self.assertEqual(produced[0]["dsl"]["parameters"], [
            {"name": "c0", "unit": [0]*7, "lower": "3", "upper": "3"},
            {"name": "c1", "unit": [0]*7, "lower": "-2", "upper": "-2"}])
        self.assertEqual(produced[0]["development"], {"selected_count": 2, "valid_count": 2, "failed_count": 0,
            "coverage": "1", "mae": "0", "rmse": "0"})

    def test_equivalent_ast_from_three_variants_is_deduplicated_and_keeps_every_origin(self) -> None:
        report = search(request([(-1.0, 4.0), (0.0, 4.0), (1.0, 4.0)], [(2.0, 4.0)]))
        self.assertEqual((report["proposed_count"], report["duplicate_count"]), (4, 2))
        self.assertEqual(len(report["candidates"]), 2)
        best = report["candidates"][0]
        self.assertEqual(sorted(sources(best)), ["linear-fit:least-squares", "linear-fit:mean", "polynomial-fit:degree-2"])
        self.assertEqual(best["dsl"]["parameters"], [{"name": "c0", "unit": [0]*7, "lower": "4", "upper": "4"}])
        self.assertEqual(best["development"], {"selected_count": 1, "valid_count": 1, "failed_count": 0,
            "coverage": "1", "mae": "0", "rmse": "0"})
        self.assertEqual(sources(report["candidates"][1]), ["linear-fit:zero"])
        self.assertEqual(report["candidates"][1]["development"]["mae"], "4")

    def test_insufficient_distinct_x_keeps_a_verifiable_not_applicable_record(self) -> None:
        report = search(request([(1.0, 1.0), (1.0, 2.0)]))
        linear = strategy(report, LINEAR)
        self.assertEqual(linear["status"], "EXECUTED")
        self.assertEqual(linear["proposed_count"], 2)
        self.assertEqual(codes(linear), ["INSUFFICIENT_DISTINCT_X"])
        for family in (POLYNOMIAL, HARMONIC):
            entry = strategy(report, family)
            self.assertEqual(entry["status"], NOT_APPLICABLE)
            self.assertEqual(entry["proposed_count"], 0)
            self.assertTrue(entry["diagnostics"])
        self.assertEqual([entry["code"] for entry in report["diagnostics"]], ["EMPTY_DEVELOPMENT"])
        self.assertEqual([candidate["development"] for candidate in report["candidates"]], [None, None])
        self.assertEqual(sorted(origin["source"] for candidate in report["candidates"] for origin in candidate["origins"]),
            ["linear-fit:mean", "linear-fit:zero"])

    def test_harmonic_dictionary_uses_one_rounded_frequency_everywhere(self) -> None:
        spacing, index = 3.0, 1
        omega = float(f"{2 * math.pi * index / spacing:.11e}")
        fit = [(float(x), 1.0 + 2.0 * math.sin(omega * x) + 3.0 * math.cos(omega * x)) for x in range(4)]
        development = [(float(x), 1.0 + 2.0 * math.sin(omega * x) + 3.0 * math.cos(omega * x)) for x in (4, 5)]
        report = search(request(fit, development))
        harmonic = strategy(report, HARMONIC)
        self.assertEqual(harmonic["status"], "EXECUTED")
        self.assertIn("FIXED_PRECISION_FREQUENCY", codes(harmonic))
        self.assertIn("ALIASING_RISK", codes(harmonic))
        produced = [candidate for candidate in report["candidates"] if "harmonic-fit:k=1" in sources(candidate)]
        self.assertEqual(len(produced), 1)
        best = produced[0]
        self.assertLess(float(best["development"]["mae"]), 1e-12)
        self.assertEqual(report["candidates"][0]["identity_hash"], best["identity_hash"])
        frequency = [parameter for parameter in best["dsl"]["parameters"] if parameter["name"] == "omega"]
        self.assertEqual(frequency[0]["lower"], frequency[0]["upper"])
        self.assertEqual(float(frequency[0]["lower"]), omega)
        self.assertEqual(frequency[0]["unit"], [0]*7)

    def test_request_surface_has_no_final_test_and_report_is_not_authoritative(self) -> None:
        self.assertEqual([field.name for field in fields(Request)], ["variable", "target_unit", "domain", "fit", "development"])
        report = search(request([(0.0, 1.0), (1.0, 2.0)]))
        self.assertEqual((report["policy_version"], report["usage_scope"]), ("local-search-execution-v1", "LOCAL_SEARCH_EXECUTION_ONLY"))
        self.assertEqual((report["product_status"], report["precision_bits"]), ("NOT_RUN", 53))

    def test_manifest_declares_its_limits_and_rejects_any_widening(self) -> None:
        declared = MANIFESTS[0].document()
        self.assertEqual(manifest(declared), MANIFESTS[0])
        self.assertEqual((declared["timeout_seconds"], declared["memory_bytes"], declared["seed_support"]), (30, 268435456, False))
        widening: tuple[JsonObject, ...] = ({"extra": 1}, {"resource_class": "GPU_LOCAL"}, {"determinism": "NONDETERMINISTIC"},
            {"seed_support": True}, {"precision_support": [32]}, {"precision_support": []}, {"timeout_seconds": 0},
            {"timeout_seconds": 3601}, {"memory_bytes": 1023}, {"input_types": []})
        for patch in widening:
            with self.subTest(patch=patch):
                with self.assertRaises(DslError) as error:
                    manifest(declared | patch)
                self.assertEqual(error.exception.code, "INVALID_SCHEMA")
        with self.assertRaises(DslError) as unsupported:
            manifest(declared | {"operators": ["add", "integrate"]})
        self.assertEqual(unsupported.exception.code, "UNSUPPORTED_OPERATOR")
