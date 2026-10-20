"""Public synthetic DSL vectors, separate from evaluator implementation."""
from decimal import Decimal, localcontext
from fractions import Fraction
import json
import math
from pathlib import Path
from runtime.contracts import JsonObject
from mathematics.compiler import compile_dsl
from mathematics.evaluator import evaluate


def main() -> None:
    directory = Path(__file__).resolve().parents[1] / "contracts"
    if not directory.is_dir():
        directory = directory.parent.parent / "docs/企劃案/contracts"
    fixtures: JsonObject = json.loads((directory / "dsl-v1.examples.json").read_text())
    document: JsonObject = fixtures["valid"][0]
    plan = compile_dsl(json.dumps(document).encode())
    xs = [Fraction(n, 8) for n in range(-8, 9)]
    results = evaluate(plan, [{"x": float(x)} for x in xs])
    errors = [abs((point.value if point.value is not None else math.inf) - float(x + 1))
              for point, x in zip(results.points, xs, strict=True)]
    if not all(p.valid_mask for p in results.points) or max(errors) > 1e-14:
        raise AssertionError("Independent linear oracle failed")
    document["root"] = {"op": "div", "args": [{"op": "var", "name": "x"}, {"op": "var", "name": "x"}]}
    quotient = compile_dsl(json.dumps(document).encode())
    hole = evaluate(quotient, [{"x": -1}, {"x": 0}, {"x": 1}])
    if [p.valid_mask for p in hole.points] != [True, False, True]:
        raise AssertionError("Domain hole disappeared")
    document["root"] = {"op": "exp", "args": [{"op": "var", "name": "x"}]}
    exponential = compile_dsl(json.dumps(document).encode())
    exp_result = evaluate(exponential, [{"x": 0.5}]).points[0]
    with localcontext() as context:
        context.prec = 70
        reference = float(Decimal("0.5").exp())
    if exp_result.value is None or not math.isclose(exp_result.value, reference, rel_tol=1e-14):
        raise AssertionError("Independent Decimal exp oracle failed")
    print(json.dumps({"scope": "T06_PUBLIC_SYNTHETIC_LOCAL_EVALUATOR", "status": "PASS", "precision_bits": 53,
                      "product_gate_status": "NOT_RUN", "linear_identity_hash": plan.identity_hash,
                      "linear_rows": len(xs), "max_absolute_error": max(errors),
                      "domain_identity_hash": quotient.identity_hash,
                      "domain_values": [p.value for p in hole.points], "valid_mask": [p.valid_mask for p in hole.points],
                      "domain_reasons": [p.reason for p in hole.points], "decimal_reference_digits": 70,
                      "exp_absolute_error": abs(exp_result.value - reference)}, indent=2))


if __name__ == "__main__":
    main()
