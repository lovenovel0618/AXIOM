"""Three-strategy search against independent references, dedup, diagnostics and manifest limits."""
from dataclasses import fields
from fractions import Fraction
import math
from unittest import TestCase
from mathematics.search import (HARMONIC, LINEAR, MANIFESTS, MAX_DEGREE, MAX_ROWS, MIN_DEGREE, NOT_APPLICABLE, POLYNOMIAL,
    STRATEGIES, Domain, Request, Variable, manifest, search)
from mathematics.syntax import DslError
from runtime.contracts import JsonObject

DIMENSIONLESS = (0,) * 7
COST_KEYS = ("fit_rows", "unknowns", "pivots", "nodes", "development_rows", "timeout_seconds", "memory_bytes",
    "resource_class")


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

    def test_registry_keeps_three_unique_valid_manifests_in_declared_order(self) -> None:
        self.assertEqual([registered.family for registered in STRATEGIES], [LINEAR, POLYNOMIAL, HARMONIC])
        self.assertEqual([registered.manifest for registered in STRATEGIES], list(MANIFESTS))
        self.assertEqual(len({registered.manifest.plugin_id for registered in STRATEGIES}), len(STRATEGIES))
        for registered in STRATEGIES:
            self.assertEqual(manifest(registered.manifest.document()), registered.manifest)

    def test_shared_interface_serves_every_family_and_linear_ignores_the_variant_index(self) -> None:
        fixture = request([(-1.0, 5.0), (0.0, 3.0), (1.0, 1.0)], [(2.0, -1.0)])
        report = search(fixture)
        for registered in STRATEGIES:
            produced = [proposal for index, _label in registered.variants
                for proposal in registered.propose(fixture, index)[0]]
            self.assertEqual(strategy(report, registered.family)["proposed_count"], len(produced))
        linear = STRATEGIES[0]
        proposals, diagnostics = linear.propose(fixture, 0)
        self.assertEqual(diagnostics, [])
        self.assertEqual([proposal.source for proposal in proposals],
            ["linear-fit:zero", "linear-fit:mean", "linear-fit:least-squares"])
        self.assertEqual(linear.propose(fixture, 7), (proposals, diagnostics))

    def test_cost_account_is_shared_and_the_minimum_origin_is_hand_checked(self) -> None:
        report = search(request([(-1.0, 4.0), (0.0, 4.0), (1.0, 4.0)], [(2.0, 4.0)]))
        for candidate in report["candidates"]:
            self.assertEqual(tuple(candidate["cost_shape"]), COST_KEYS)
            for origin in candidate["origins"]:
                self.assertEqual(tuple(origin["cost_shape"]), COST_KEYS)
            smallest = min((origin["cost_shape"] for origin in candidate["origins"]),
                key=lambda shape: tuple(shape[name] for name in COST_KEYS))
            self.assertEqual(candidate["cost_shape"], smallest)
        merged = [candidate for candidate in report["candidates"] if len(candidate["origins"]) > 1]
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["cost_shape"], {"fit_rows": 3, "unknowns": 1, "pivots": 0, "nodes": 1,
            "development_rows": 1, "timeout_seconds": 30, "memory_bytes": 268435456, "resource_class": "CPU_LOCAL"})

    def test_failure_classification_codes_are_unchanged_for_every_family(self) -> None:
        insufficient = search(request([(1.0, 1.0), (1.0, 2.0)]))
        self.assertEqual(codes(strategy(insufficient, LINEAR)), ["INSUFFICIENT_DISTINCT_X"])
        self.assertEqual(codes(strategy(insufficient, POLYNOMIAL)),
            ["INSUFFICIENT_DISTINCT_X", "INSUFFICIENT_DISTINCT_X"])
        self.assertEqual(codes(strategy(insufficient, HARMONIC)), ["INSUFFICIENT_DISTINCT_X"] * 3)
        degenerate = search(request([(float(x), 1.0) for x in range(4)]))
        self.assertEqual(codes(strategy(degenerate, HARMONIC)), ["FIXED_PRECISION_FREQUENCY",
            "FIXED_PRECISION_FREQUENCY", "ALIASING_RISK", "FIXED_PRECISION_FREQUENCY", "ALIASING_RISK", "RANK_DEFICIENT"])


class PolynomialStrategyTests(TestCase):
    """M2-T2 專屬：度數上限、擬合與排名、退化輸入、等價結構去重。"""

    def test_degree_bound_rejects_every_degree_outside_the_registered_variants(self) -> None:
        polynomial = STRATEGIES[1]
        self.assertEqual([index for index, _label in polynomial.variants], [MIN_DEGREE, MAX_DEGREE])
        fixture = request([(float(x), float(x * x)) for x in range(6)])
        for degree in (0, 1, MAX_DEGREE + 1, 7):
            with self.subTest(degree=degree):
                produced, notes = polynomial.propose(fixture, degree)
                self.assertEqual(produced, [])
                self.assertEqual([note.code for note in notes], ["UNSUPPORTED_DEGREE"])
        for degree in (MIN_DEGREE, MAX_DEGREE):
            with self.subTest(degree=degree):
                self.assertEqual(len(polynomial.propose(fixture, degree)[0]), 1)

    def test_quadratic_is_recovered_and_outranks_the_line_at_the_same_budget(self) -> None:
        fit = [(float(x), float(x * x - 2 * x + 3)) for x in range(6)]
        development = [(6.0, 27.0), (7.0, 38.0)]
        report = search(request(fit, development))
        polynomial = {sources(candidate)[0]: float(candidate["development"]["mae"])
            for candidate in report["candidates"] if sources(candidate)[0].startswith("polynomial-fit")}
        self.assertEqual(sorted(polynomial, key=polynomial.__getitem__),
            ["polynomial-fit:degree-3", "polynomial-fit:degree-2"])
        self.assertLess(polynomial["polynomial-fit:degree-3"], 1e-12)
        self.assertLess(polynomial["polynomial-fit:degree-2"], 1e-12)
        line = next(candidate for candidate in report["candidates"] if "linear-fit:least-squares" in sources(candidate))
        self.assertGreater(float(line["development"]["mae"]), 1.0)
        self.assertLess(polynomial["polynomial-fit:degree-2"], float(line["development"]["mae"]))

    def test_degree_three_needs_four_distinct_x_while_degree_two_still_fits(self) -> None:
        polynomial = STRATEGIES[1]
        fixture = request([(0.0, 3.0), (1.0, 2.0), (2.0, 3.0)])
        self.assertEqual(len(polynomial.propose(fixture, MIN_DEGREE)[0]), 1)
        produced, notes = polynomial.propose(fixture, MAX_DEGREE)
        self.assertEqual(produced, [])
        self.assertEqual([note.code for note in notes], ["INSUFFICIENT_DISTINCT_X"])

    def test_equivalent_constant_ast_merges_the_line_and_both_polynomial_degrees(self) -> None:
        report = search(request([(float(x), 4.0) for x in range(4)], [(4.0, 4.0)]))
        merged = [candidate for candidate in report["candidates"] if len(candidate["origins"]) > 1]
        self.assertEqual(len(merged), 1)
        self.assertEqual(sorted(sources(merged[0])), ["linear-fit:least-squares", "linear-fit:mean",
            "polynomial-fit:degree-2", "polynomial-fit:degree-3"])
        self.assertEqual(merged[0]["development"], {"selected_count": 1, "valid_count": 1, "failed_count": 0,
            "coverage": "1", "mae": "0", "rmse": "0"})


class HarmonicStrategyTests(TestCase):
    """M2-T3 專屬：字典外頻率不誤判為識別、混疊歧義保留候選與拒答。"""

    def test_off_grid_frequency_keeps_candidates_but_none_ranks_first(self) -> None:
        # 真實頻率取字典格的一半位置（k=1.5），三格字典都解釋不了，排名必須讓不涉及頻率的基線勝出。
        span = 5.0
        omega = 2 * math.pi * 1.5 / span
        fit = [(float(x), math.sin(omega * x)) for x in range(6)]
        development = [(float(x), math.sin(omega * x)) for x in (6, 7)]
        report = search(request(fit, development))
        harmonic = [candidate for candidate in report["candidates"] if sources(candidate)[0].startswith("harmonic-fit")]
        self.assertEqual(sorted(sources(candidate)[0] for candidate in harmonic),
            ["harmonic-fit:k=1", "harmonic-fit:k=2", "harmonic-fit:k=3"])
        best = report["candidates"][0]
        self.assertFalse(sources(best)[0].startswith("harmonic-fit"))
        for candidate in harmonic:
            self.assertGreater(float(candidate["development"]["mae"]), float(best["development"]["mae"]))
        self.assertIn("FIXED_PRECISION_FREQUENCY", codes(strategy(report, HARMONIC)))

    def test_alias_equivalent_entries_stay_separate_candidates_without_identification(self) -> None:
        # 整數格且 T=3 時 k=2 的基底與 k=1 只差一個負號，兩者對 fit 的解釋在浮點噪音內相同；
        # k=3 在這格上退化，策略保留 RANK_DEFICIENT 而不給候選，歧義因此不被合併成單一答案。
        fit = [(float(x), math.sin(2 * math.pi * x / 3)) for x in range(4)]
        development = [(float(x), math.sin(2 * math.pi * x / 3)) for x in (4, 5)]
        report = search(request(fit, development))
        self.assertEqual(codes(strategy(report, HARMONIC)), ["FIXED_PRECISION_FREQUENCY", "FIXED_PRECISION_FREQUENCY",
            "ALIASING_RISK", "FIXED_PRECISION_FREQUENCY", "ALIASING_RISK", "RANK_DEFICIENT"])
        ambiguous = [candidate for candidate in report["candidates"]
            if sources(candidate)[0] in ("harmonic-fit:k=1", "harmonic-fit:k=2")]
        self.assertEqual(len(ambiguous), 2)
        for candidate in ambiguous:
            self.assertLess(float(candidate["development"]["mae"]), 1e-11)
        self.assertEqual((report["product_status"], report["usage_scope"]), ("NOT_RUN", "LOCAL_SEARCH_EXECUTION_ONLY"))

    def test_row_budget_is_shared_and_over_budget_requests_stop_generation(self) -> None:
        report = search(request([(float(x), float(x)) for x in range(MAX_ROWS - 1)], [(500.0, 500.0)]))
        shapes = [origin["cost_shape"] for candidate in report["candidates"] for origin in candidate["origins"]]
        for name, expected in (("fit_rows", MAX_ROWS - 1), ("development_rows", 1), ("timeout_seconds", 30),
                ("memory_bytes", 268435456), ("resource_class", "CPU_LOCAL")):
            with self.subTest(field=name):
                self.assertEqual({shape[name] for shape in shapes}, {expected})
        with self.assertRaises(DslError) as error:
            search(request([(float(index), float(index)) for index in range(MAX_ROWS + 1)]))
        self.assertEqual(error.exception.code, "AST_LIMIT_EXCEEDED")
        # 預算內的候選一律不帶已驗證標記，只有報告層級的 NOT_RUN 與離線使用範圍宣告。
        self.assertEqual(report["product_status"], "NOT_RUN")
        for candidate in report["candidates"]:
            with self.subTest(candidate=candidate["identity_hash"]):
                self.assertNotIn("verified", candidate)
                self.assertNotIn("product_status", candidate)
