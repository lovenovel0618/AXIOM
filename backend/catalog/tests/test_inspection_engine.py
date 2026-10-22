"""Independent conversion/statistics vectors and final non-interference checks."""
from collections.abc import Sequence
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal
from fractions import Fraction
import json
import math
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from uuid import uuid4
import polars as pl
from catalog.tests.test_research import draft_data
from ingestion.limits import ImportLimits, ImportRejected
from ingestion.research import converted, inspect_file, scalar
from ingestion.research_protocol import decode_report, report_check, number
from ingestion.supervisor import inspect_research
from mathematics.evaluator import evaluate
from runtime.contracts import JsonObject, identity_hash

LIMITS = ImportLimits(100, 8, 4096, 65536, 10)


def linear_model(domain: list[JsonObject]) -> JsonObject:
    return {"dsl_version": "1.0", "variables": [{"name": "x", "unit": [0]*7}], "parameters": [], "domain": deepcopy(domain),
        "root": {"op": "add", "args": [{"op": "mul", "args": [{"op": "const", "value": {"numerator": "2", "denominator": "1"}}, {"op": "var", "name": "x"}]}, {"op": "const", "value": {"numerator": "1", "denominator": "1"}}]}}


def config_for(model: bool = True) -> JsonObject:
    research = draft_data(uuid4())
    split = research["observation_split"]
    split["row_ids_hash"] = identity_hash({key: split[key] for key in ("fit", "development", "final_test")})
    return {"research": research, "metadata": {"row_count": 10, "columns": [{"name": "x", "physical_type": "CSV_TEXT"}, {"name": "y", "physical_type": "CSV_TEXT"}]},
        "model": linear_model(research["domain"]) if model else None, "parameters": {}}


class InspectionEngineTests(TestCase):
    def inspect(self, rows: Sequence[tuple[object, object]] | None = None, config: JsonObject | None = None, format_name: str = "CSV") -> JsonObject:
        request: JsonObject = deepcopy(config or config_for())
        data = rows if rows is not None else [(i, 2*i+1) for i in range(10)]
        with TemporaryDirectory() as directory:
            path = Path(directory) / "input"
            if format_name == "PARQUET":
                pl.DataFrame({"x": [row[0] for row in data], "y": [row[1] for row in data]}).write_parquet(path)
                physical = [str(dtype) for dtype in pl.read_parquet_schema(path).values()]
            elif format_name == "JSON":
                path.write_text(json.dumps([{"x": x,"y": y} for x,y in data]))
                physical = ["JSON_SCALAR"]*2
            else:
                path.write_text('x,y\n' + ''.join(f'{x},{y}\n' for x,y in data))
                physical = ["CSV_TEXT"]*2
            request["metadata"]["columns"] = [{"name": name, "physical_type": dtype} for name,dtype in zip(("x","y"),physical,strict=True)]
            result = inspect_file(path, format_name, LIMITS, request)
            report_check(result, request)
            return result

    def test_three_formats_against_exact_linear_and_type7_oracle(self) -> None:
        for format_name in ("CSV", "JSON", "PARQUET"):
            with self.subTest(format_name=format_name):
                result = self.inspect(format_name=format_name)
                self.assertEqual(result["quality"], "PASS")
                self.assertEqual(result["fit_summary"], {"selected_count":6,"unique_x":6,"target_min":"1","target_max":"11","target_mean":"6","target_iqr":"5"})
                self.assertEqual(result["model_evaluation"], {"fit": {"selected_count":6,"valid_count":6,"failed_count":0,"coverage":"1","mae":"0","rmse":"0"}, "development": {"selected_count":2,"valid_count":2,"failed_count":0,"coverage":"1","mae":"0","rmse":"0"}})

    def test_final_labels_do_not_change_any_statistics_or_scores(self) -> None:
        baseline = self.inspect()
        rows: list[tuple[object, object]] = [(i, 2*i+1 if i < 8 else 987654321123) for i in range(10)]
        self.assertEqual(self.inspect(rows), baseline)
        with patch("mathematics.metrics.evaluate", wraps=evaluate) as evaluator:
            self.inspect(rows)
            evaluated = [point["x"] for call in evaluator.call_args_list for point in call.args[1]]
            self.assertEqual(evaluated, list(range(8)))
            self.assertNotIn(8, evaluated)
            self.assertNotIn(9, evaluated)

    def test_any_bad_selected_cell_has_identical_masked_output(self) -> None:
        outputs: list[JsonObject] = []
        for row in (0,6,8):
            for value in ("secret-marker", "NaN", "1e-400", "1e400", " 2 "):
                rows: list[tuple[object, object]] = [(i,2*i+1) for i in range(10)]
                rows[row] = (row, value)
                with self.subTest(row=row, value=value):
                    outputs.append(self.inspect(rows))
        self.assertTrue(all(output == outputs[0] for output in outputs))
        self.assertEqual(outputs[0]["quality"], "BLOCKED")
        self.assertIsNone(outputs[0]["fit_summary"])
        self.assertIsNone(outputs[0]["model_evaluation"])
        self.assertNotIn("secret-marker", json.dumps(outputs))

    def test_json_null_boolean_and_parquet_nonfinite_block_quality(self) -> None:
        for value in (None, True):
            rows: list[tuple[object, object]] = [(i,2*i+1) for i in range(10)]
            rows[9] = (9,value)
            self.assertEqual(self.inspect(rows, format_name="JSON")["quality"], "BLOCKED")
        for value in (float("nan"),float("inf")):
            rows = [(float(i),float(2*i+1)) for i in range(10)]
            rows[9] = (9.0,value)
            self.assertEqual(self.inspect(rows, format_name="PARQUET")["quality"], "BLOCKED")

    def test_exact_affine_units_and_parquet_decimal(self) -> None:
        mapping = {"conversion": {"scale":"0.01","offset":"0"}}
        self.assertEqual(converted("123.45",mapping)[0], Fraction(2469,2000))
        self.assertEqual(converted(Decimal("123.45"),mapping)[0], Fraction(2469,2000))
        self.assertEqual(converted("0",{"conversion":{"scale":"1","offset":"273.15"}})[0], Fraction(5463,20))
        self.assertEqual(scalar("1.25e-2"),Fraction(1,80))
        for value in ("1e1000000000", "1"*257, False, None):
            with self.subTest(value=value), self.assertRaises(ImportRejected):
                scalar(value)

    def test_text_decimal_tokens_remain_exact_and_unused_column_is_allowed(self) -> None:
        rows: list[tuple[object,object]] = [(i,"0.1") for i in range(10)]
        for format_name in ("CSV","JSON"):
            values = rows if format_name=="CSV" else [(i,0.1) for i in range(10)]
            result = self.inspect(values,config_for(False),format_name)
            self.assertEqual(result["fit_summary"]["target_mean"],"1/10")
        config: JsonObject = config_for(False)
        config["metadata"]["columns"].append({"name":"unused","physical_type":"CSV_TEXT"})
        with TemporaryDirectory() as directory:
            path = Path(directory)/"input"
            path.write_text('x,y,unused\n'+''.join(f'{i},{2*i+1},non-numeric\n' for i in range(10)))
            result = inspect_file(path,"CSV",LIMITS,config)
        self.assertEqual(result["quality"],"PASS")

    def test_open_boundary_and_float_rounding_are_not_relaxed(self) -> None:
        config: JsonObject = config_for(False)
        config["research"]["domain"][0]["lower_closed"] = False
        self.assertEqual(self.inspect(config=config)["quality"],"BLOCKED")
        config["research"]["domain"][0]["lower_closed"] = True
        config["research"]["domain"][0]["upper"] = {"numerator":"1","denominator":"10"}
        rows: list[tuple[object,object]] = [("0.1", i) for i in range(10)]
        self.assertEqual(self.inspect(rows,config)["quality"],"BLOCKED")

    def test_nonzero_metrics_and_parameter_binding_use_independent_oracle(self) -> None:
        config: JsonObject = config_for()
        config["model"]["parameters"] = [{"name":"a","unit":[0]*7,"lower":"0","upper":"2"}]
        config["model"]["root"] = {"op":"param","name":"a"}
        config["parameters"] = {"a":"1"}
        result = self.inspect(config=config)
        fit,development = result["model_evaluation"]["fit"],result["model_evaluation"]["development"]
        self.assertEqual(fit["mae"],"5")
        self.assertEqual(development["mae"],"13")
        self.assertTrue(math.isclose(float(fit["rmse"]),math.sqrt(110/3),rel_tol=1e-14))
        self.assertTrue(math.isclose(float(development["rmse"]),math.sqrt(170),rel_tol=1e-14))

    def test_evaluator_failure_preserves_denominator(self) -> None:
        config: JsonObject = config_for()
        config["model"]["root"] = {"op":"div","args":[{"op":"var","name":"x"},{"op":"var","name":"x"}]}
        result = self.inspect(config=config)
        self.assertEqual(result["quality"],"PASS")
        metrics = result["model_evaluation"]["fit"]
        self.assertEqual((metrics["selected_count"],metrics["valid_count"],metrics["failed_count"],metrics["coverage"]),(6,5,1,"5/6"))
        self.assertIsNone(metrics["mae"])
        self.assertIsNone(metrics["rmse"])

    def test_wrong_dsl_domain_unit_or_parameters_rejected_before_rows(self) -> None:
        for change in ("domain","unit","parameters"):
            config: JsonObject = config_for()
            if change == "domain": config["model"]["domain"][0]["lower_closed"] = False
            elif change == "unit": config["model"]["variables"][0]["unit"][0] = 1
            else: config["parameters"] = {"unknown":"1"}
            with self.subTest(change=change), patch("ingestion.research.parse") as parser:
                with self.assertRaises(ValueError):
                    self.inspect(config=config)
                parser.assert_not_called()

    def test_source_shape_split_hash_and_size_are_verified(self) -> None:
        for change in ("metadata","hash","overlap","missing"):
            config: JsonObject = config_for()
            if change == "metadata": config["metadata"]["row_count"] = 11
            elif change == "hash": config["research"]["observation_split"]["row_ids_hash"] = "0"*64
            elif change == "overlap": config["research"]["observation_split"]["final_test"] = [0,9]
            else: config["research"]["observation_split"]["final_test"] = [9]
            with self.subTest(change=change), self.assertRaises(ImportRejected):
                self.inspect(config=config)

    def test_child_protocol_rejects_extra_final_samples_and_fake_counts(self) -> None:
        config = config_for()
        valid: JsonObject = self.inspect()
        for change in ("final","sample","count","type","extra"):
            value = deepcopy(valid)
            if change == "final": value["model_evaluation"]["final_test"] = {}
            elif change == "sample": value["fit_summary"]["samples"] = [999]
            elif change == "count": value["model_evaluation"]["fit"]["failed_count"] = 1
            elif change == "type": value["precision_bits"] = True
            else: value["secret"] = 999
            raw = json.dumps({"status":"PASS","report":value}).encode()
            with self.subTest(change=change), self.assertRaises(ImportRejected):
                decode_report(raw,config)
        for raw in (b'null',b'[]',b'{"status":"REJECTED","code":"secret"}'):
            with self.assertRaises(ImportRejected):
                decode_report(raw,config)

    def test_child_numeric_strings_cannot_trigger_unbounded_exponents(self) -> None:
        for text in ("1e1000000000","1e-1000000000","NaN","Infinity","1/0"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                number(text)

    def test_real_research_child_and_private_request_cleanup(self) -> None:
        config = config_for()
        content = b'x,y\n' + b''.join(f'{i},{2*i+1}\n'.encode() for i in range(10))
        with TemporaryDirectory() as directory:
            with patch("ingestion.supervisor.tempfile.tempdir",directory):
                result = inspect_research(content,"CSV",LIMITS,config)
            self.assertEqual(list(Path(directory).iterdir()),[])
        self.assertEqual(result["quality"],"PASS")
        limits = replace(LIMITS,max_rows=9)
        with self.assertRaises(ImportRejected):
            inspect_research(content,"CSV",limits,config)
