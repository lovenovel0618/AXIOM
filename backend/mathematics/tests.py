"""Independent references and hostile inputs for the scalar interpreter."""
from copy import deepcopy
from decimal import Decimal, localcontext
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
from typing import Any
from mathematics.compiler import Plan, compile_dsl
from mathematics.evaluator import Numeric, evaluate
from mathematics.syntax import DslError

Document = dict[str, Any]
ZERO_UNIT = [0] * 7


def const(numerator: int, denominator: int = 1) -> Document:
    return {"op": "const", "value": {"numerator": str(numerator), "denominator": str(denominator)}}


def var(name: str = "x") -> Document:
    return {"op": "var", "name": name}


def op(name: str, *args: Document) -> Document:
    return {"op": name, "args": list(args)}


def envelope(root: Document) -> Document:
    return {"dsl_version": "1.0", "variables": [{"name": "x", "unit": ZERO_UNIT.copy()}], "parameters": [],
            "domain": [{"name": "x", "lower": {"numerator": "-1000", "denominator": "1"},
                        "upper": {"numerator": "1000", "denominator": "1"}, "lower_closed": True, "upper_closed": True}],
            "root": root}


def compile_document(document: Document) -> Plan:
    return compile_dsl(json.dumps(document).encode())


def expression(root: Document) -> Plan:
    return compile_document(envelope(root))


class CompilerTests(TestCase):
    def reject(self, document: Document, code: str) -> None:
        with self.assertRaises(DslError) as raised:
            compile_document(document)
        self.assertEqual(raised.exception.code, code)

    def test_commutative_hash_and_literal_vector(self) -> None:
        first = expression(op("add", var(), const(1)))
        second = expression(op("add", const(2, 2), var()))
        self.assertEqual(first, second)
        expected = (b'{"domain":[{"lower":{"denominator":"1","numerator":"-1000"},"lower_closed":true,"name":"x",'
                    b'"upper":{"denominator":"1","numerator":"1000"},"upper_closed":true}],"dsl_version":"1.0",'
                    b'"parameters":[],"root":{"args":[{"name":"x","op":"var"},{"op":"const","value":{"denominator":"1",'
                    b'"numerator":"1"}}],"op":"add"},"variables":[{"name":"x","unit":[0,0,0,0,0,0,0]}]}')
        self.assertEqual(first.canonical, expected)
        self.assertEqual(first.identity_hash, hashlib.sha256(expected).hexdigest())

    def test_flatten_and_exact_constant_folding(self) -> None:
        first = expression(op("add", var(), op("add", const(1, 3), const(1, 6))))
        second = expression(op("add", const(1, 2), var()))
        self.assertEqual(first, second)
        self.assertEqual(compile_dsl(first.canonical), first)

    def test_different_domain_and_hole_keep_identity(self) -> None:
        document = envelope(var())
        original = compile_document(document)
        document["domain"][0]["lower_closed"] = False
        self.assertNotEqual(original.identity_hash, compile_document(document).identity_hash)
        self.assertNotEqual(expression(op("div", var(), var())).identity_hash, expression(const(1)).identity_hash)

    def test_units_operations(self) -> None:
        for name, expected in (("mul", (0, 2, 0, 0, 0, 0, 0)), ("div", tuple(ZERO_UNIT)), ("sub", (0, 1, 0, 0, 0, 0, 0))):
            with self.subTest(name=name):
                document = envelope(op(name, var(), var()))
                document["variables"][0]["unit"][1] = 1
                self.assertEqual(compile_document(document).output_unit, expected)
        document = envelope(op("pow", var(), const(-2)))
        document["variables"][0]["unit"][2] = 1
        self.assertEqual(compile_document(document).output_unit, (0, 0, -2, 0, 0, 0, 0))

    def test_unit_mismatch_and_transcendental(self) -> None:
        for root in (op("add", var(), const(1)), op("sin", var()), op("cos", var()), op("exp", var()), op("log", var())):
            document = envelope(root)
            document["variables"][0]["unit"][1] = 1
            self.reject(document, "UNIT_MISMATCH")

    def test_unknown_operator_and_symbol(self) -> None:
        self.reject(envelope(op("exec", const(1))), "UNSUPPORTED_OPERATOR")
        self.reject(envelope(var("__import__")), "UNKNOWN_SYMBOL")
        self.reject(envelope({"op": "param", "name": "missing"}), "UNKNOWN_SYMBOL")

    def test_pow_integer_limits(self) -> None:
        for power in (const(9), const(-9), const(1, 2), var()):
            self.reject(envelope(op("pow", var(), power)), "AST_LIMIT_EXCEEDED")

    def test_depth_and_node_limits(self) -> None:
        root = var()
        for _index in range(10):
            root = op("abs", root)
        self.reject(envelope(root), "AST_LIMIT_EXCEEDED")
        self.reject(envelope(op("add", *[var() for _index in range(1024)])), "AST_LIMIT_EXCEEDED")
        self.assertEqual(expression(op("add", *[var() for _index in range(1023)])).node_count, 1024)

    def test_rational_growth_limit(self) -> None:
        self.reject(envelope(op("pow", const(10**127), const(8))), "AST_LIMIT_EXCEEDED")
        self.reject(envelope(const(10**128)), "INVALID_SCHEMA")

    def test_duplicate_and_overlapping_names(self) -> None:
        document = envelope(var())
        document["variables"].append(deepcopy(document["variables"][0]))
        self.reject(document, "INVALID_SCHEMA")
        document = envelope(var())
        document["parameters"] = [{"name": "x", "unit": ZERO_UNIT, "lower": "0", "upper": "1"}]
        self.reject(document, "INVALID_SCHEMA")

    def test_domain_coverage_duplicates_and_order(self) -> None:
        document = envelope(var())
        document["domain"] = []
        self.reject(document, "INVALID_SCHEMA")
        document = envelope(var())
        document["domain"].append(deepcopy(document["domain"][0]))
        self.reject(document, "INVALID_SCHEMA")
        document = envelope(var())
        document["domain"][0]["lower"]["numerator"] = "1001"
        self.reject(document, "INVALID_SCHEMA")

    def test_singleton_domain(self) -> None:
        document = envelope(var())
        document["domain"][0]["upper"] = deepcopy(document["domain"][0]["lower"])
        self.assertIsInstance(compile_document(document), Plan)
        document["domain"][0]["lower_closed"] = False
        self.reject(document, "INVALID_SCHEMA")

    def test_parameter_normalization_and_bounds(self) -> None:
        document = envelope({"op": "param", "name": "a"})
        document["parameters"] = [{"name": "a", "unit": ZERO_UNIT, "lower": "-0.000", "upper": "2.1000"}]
        canonical = json.loads(compile_document(document).canonical)
        self.assertEqual((canonical["parameters"][0]["lower"], canonical["parameters"][0]["upper"]), ("0", "2.1"))
        document["parameters"][0]["lower"] = "3"
        self.reject(document, "INVALID_SCHEMA")

    def test_json_attacks(self) -> None:
        document = json.dumps(envelope(var())).encode()
        payloads = [b'{"root":{},"root":{}}', b'{"root":{},"r\\u006fot":{}}', b'[]', b'null', b'"text"',
                    b'{"x":NaN}', b'{"x":1e400}', b'{"x":1.0}', b'\xff', b'{"x":"\\ud800"}',
                    document.replace(b'"op": "var"', b'"op": []'), document.replace(b'"op": "var"', b'"op": "__import__(os)"')]
        for payload in payloads:
            with self.subTest(payload=payload[:80]), self.assertRaises(DslError):
                compile_dsl(payload)

    def test_size_and_json_depth(self) -> None:
        for payload in (b' ' * (256 * 1024 + 1), b'[' * 33 + b']' * 33):
            with self.assertRaises(DslError) as raised:
                compile_dsl(payload)
            self.assertEqual(raised.exception.code, "AST_LIMIT_EXCEEDED")

    def test_schema_extra_fields_and_arity(self) -> None:
        document = envelope(op("sin", var(), const(1)))
        self.reject(document, "INVALID_SCHEMA")
        document = envelope(var())
        document["root"]["host"] = "os.system"
        self.reject(document, "INVALID_SCHEMA")

    def test_declared_order_does_not_change_hash(self) -> None:
        document = envelope(op("add", var(), var("y")))
        document["variables"].append({"name": "y", "unit": ZERO_UNIT})
        domain = deepcopy(document["domain"][0])
        domain["name"] = "y"
        document["domain"].append(domain)
        first = compile_document(document)
        document["variables"].reverse()
        document["domain"].reverse()
        self.assertEqual(first, compile_document(document))

    def test_piecewise_unit_and_predicate_checked(self) -> None:
        root: Document = {"op": "piecewise", "branches": [{"when": {"var": "x", "comparator": "lt", "value": const(0)["value"]}, "then": const(1)}], "otherwise": var()}
        document = envelope(root)
        document["variables"][0]["unit"][1] = 1
        self.reject(document, "UNIT_MISMATCH")
        root["branches"][0]["when"]["var"] = "missing"
        self.reject(envelope(root), "UNKNOWN_SYMBOL")

    def test_max_depth_and_declarations(self) -> None:
        root = var()
        for _index in range(9):
            root = op("abs", root)
        self.assertEqual(expression(root).node_count, 10)
        document = envelope(var())
        document["parameters"] = [{"name": "p" + str(index), "unit": ZERO_UNIT, "lower": "0", "upper": "1"} for index in range(129)]
        self.reject(document, "AST_LIMIT_EXCEEDED")

    def test_exact_fraction_folds(self) -> None:
        for root, expected in ((op("sub", const(2, 3), const(1, 6)), const(1, 2)),
                               (op("div", const(2, 3), const(4, 3)), const(1, 2)),
                               (op("pow", const(2), const(-3)), const(1, 8)),
                               (op("mul", const(2, 3), const(3, 4)), const(1, 2)),
                               (op("abs", const(-1, 2)), const(1, 2))):
            self.assertEqual(expression(root), expression(expected))

    def test_repository_examples(self) -> None:
        root = Path(__file__).resolve().parents[2]
        path = root / "docs/企劃案/contracts/dsl-v1.examples.json"
        if not path.exists():
            path = Path(__file__).resolve().parents[1] / "contracts/dsl-v1.examples.json"
        examples: Document = json.loads(path.read_text())
        for document in examples["valid"]:
            compile_document(document)
        for row in examples["invalid"]:
            with self.assertRaises(DslError):
                compile_document(row["document"])
        for row in examples["semantic_invalid"]:
            self.reject(row["document"], row["reason"])


class EvaluatorTests(TestCase):
    def value(self, root: Document, x: Numeric = 2) -> float:
        result = evaluate(expression(root), [{"x": x}])
        self.assertTrue(result.points[0].valid_mask)
        value = result.points[0].value
        self.assertIsNotNone(value)
        assert value is not None
        return value

    def test_linear_independent_fraction_reference(self) -> None:
        plan = expression(op("add", op("mul", const(2), var()), const(1)))
        xs = [Fraction(n, 8) for n in range(-80, 81)]
        result = evaluate(plan, [{"x": float(x)} for x in xs])
        for x, point in zip(xs, result.points, strict=True):
            self.assertEqual(point.value, float(2 * x + 1))
        self.assertEqual(result.precision_bits, 53)

    def test_sine_independent_taylor_reference(self) -> None:
        xs = [Fraction(n, 20) for n in range(-20, 21)]
        for x in xs:
            expected = sum(((-1)**n * x**(2*n+1) / math.factorial(2*n+1) for n in range(12)), Fraction())
            self.assertAlmostEqual(self.value(op("sin", var()), float(x)), float(expected), places=14)

    def test_exp_log_independent_decimal_reference(self) -> None:
        with localcontext() as context:
            context.prec = 70
            for text in ("0.125", "0.5", "1", "2", "8"):
                x = Decimal(text)
                self.assertAlmostEqual(self.value(op("exp", var()), float(x)), float(x.exp()), places=12)
                self.assertAlmostEqual(self.value(op("log", var()), float(x)), float(x.ln()), places=14)

    def test_other_operators(self) -> None:
        for root, expected in ((op("sub", var(), const(3)), -1), (op("div", var(), const(4)), 0.5),
                               (op("pow", var(), const(-2)), 0.25), (op("abs", var()), 2), (op("cos", const(0)), 1)):
            self.assertAlmostEqual(self.value(root), expected)

    def test_domain_hole_retains_all_points(self) -> None:
        result = evaluate(expression(op("div", var(), var())), [{"x": -1}, {"x": 0}, {"x": 1}])
        self.assertEqual([p.valid_mask for p in result.points], [True, False, True])
        self.assertEqual(result.points[1].reason, "DOMAIN_VIOLATION")
        self.assertIsNone(result.points[1].value)

    def test_invalid_constants_retained_until_evaluation(self) -> None:
        for root in (op("div", const(1), const(0)), op("log", const(-1)), op("pow", const(0), const(0)), op("pow", const(0), const(-1))):
            result = evaluate(expression(root), [{"x": 0}])
            self.assertFalse(result.points[0].valid_mask)

    def test_no_zero_times_hole_elimination(self) -> None:
        root = op("mul", const(0), op("div", var(), var()))
        result = evaluate(expression(root), [{"x": 0}])
        self.assertFalse(result.points[0].valid_mask)

    def test_piecewise_lazy_first_match_and_otherwise(self) -> None:
        root: Document = {"op": "piecewise", "branches": [
            {"when": {"var": "x", "comparator": "lte", "value": const(0)["value"]}, "then": const(7)},
            {"when": {"var": "x", "comparator": "lt", "value": const(1)["value"]}, "then": const(8)}],
            "otherwise": op("log", var())}
        result = evaluate(expression(root), [{"x": -1}, {"x": 0}, {"x": 0.5}, {"x": 1}])
        self.assertEqual([p.value for p in result.points], [7, 7, 8, 0])

    def test_piecewise_gt_gte(self) -> None:
        for comparator, expected in (("gt", 2), ("gte", 1)):
            root: Document = {"op": "piecewise", "branches": [{"when": {"var": "x", "comparator": comparator, "value": const(0)["value"]}, "then": const(1)}], "otherwise": const(2)}
            self.assertAlmostEqual(self.value(root, 0), expected)

    def test_invalid_unselected_branch_still_checked(self) -> None:
        root: Document = {"op": "piecewise", "branches": [{"when": {"var": "x", "comparator": "lt", "value": const(0)["value"]}, "then": var("missing")}], "otherwise": var()}
        with self.assertRaises(DslError):
            expression(root)

    def test_open_domain_and_outside(self) -> None:
        document = envelope(var())
        document["domain"][0]["lower_closed"] = False
        result = evaluate(compile_document(document), [{"x": -1000}, {"x": 1001}, {"x": 1000}])
        self.assertEqual([p.valid_mask for p in result.points], [False, False, True])

    def test_exact_rational_boundary(self) -> None:
        document = envelope(var())
        document["domain"][0]["lower"] = const(1, 10)["value"]
        result = evaluate(compile_document(document), [{"x": 0.1}, {"x": math.nextafter(0.1, 0)}])
        self.assertEqual([p.valid_mask for p in result.points], [True, False])

    def test_nonfinite_bool_and_unsafe_integer(self) -> None:
        rows = [{"x": x} for x in (math.inf, math.nan, True, 2**54)]
        result = evaluate(expression(var()), rows)
        self.assertTrue(all(not p.valid_mask for p in result.points))

    def test_overflow_underflow(self) -> None:
        for root, x in ((op("exp", var()), 1000), (op("exp", var()), -1000),
                        (op("pow", op("exp", var()), const(8)), 100),
                        (op("div", op("exp", var()), op("exp", op("abs", var()))), -500)):
            result = evaluate(expression(root), [{"x": x}])
            self.assertFalse(result.points[0].valid_mask)

    def test_missing_and_extra_row_names(self) -> None:
        result = evaluate(expression(var()), [{}, {"x": 0, "y": 1}])
        self.assertTrue(all(p.reason == "UNKNOWN_SYMBOL" for p in result.points))

    def test_parameter_binding(self) -> None:
        document = envelope(op("mul", {"op": "param", "name": "a"}, var()))
        document["parameters"] = [{"name": "a", "unit": ZERO_UNIT, "lower": "0", "upper": "2"}]
        plan = compile_document(document)
        result = evaluate(plan, [{"x": 2}], {"a": "1.50"})
        self.assertAlmostEqual(result.points[0].value or 0, 3)
        for binding in ({}, {"a": "3"}, {"a": "NaN"}, {"a": "1e0"}):
            with self.assertRaises(DslError):
                evaluate(plan, [{"x": 2}], binding)
        self.assertEqual(compile_document(document).identity_hash, plan.identity_hash)

    def test_batch_limits(self) -> None:
        plan = expression(var())
        rows = [{"x": 0}] * 4097
        with self.assertRaises(DslError):
            evaluate(plan, rows)
        plan = expression(op("add", *[var() for _index in range(128)]))
        rows = [{"x": 0}] * 4096
        with self.assertRaises(DslError):
            evaluate(plan, rows)

    def test_deadline(self) -> None:
        plan = expression(var())
        with patch("mathematics.evaluator.time.monotonic", side_effect=[10.0, 12.0]):
            with self.assertRaises(DslError) as raised:
                evaluate(plan, [{"x": 1}])
        self.assertEqual(raised.exception.code, "AST_LIMIT_EXCEEDED")

    def test_forged_plan_rejected(self) -> None:
        plan = expression(var())
        forged = Plan(plan.canonical, "0" * 64, plan.output_unit, plan.node_count)
        with self.assertRaises(DslError):
            evaluate(forged, [{"x": 1}])
