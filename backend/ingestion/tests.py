"""Format, shape, boundary and real Linux process enforcement tests."""
from collections.abc import Sequence
from dataclasses import replace
import hashlib
import json
import os
import stat
from pathlib import Path
import signal
import subprocess
import sys
from tempfile import TemporaryDirectory
from typing import Any
from unittest import TestCase, skipUnless
from unittest.mock import patch
import polars as pl
from ingestion.limits import ImportLimits, ImportRejected, LIMIT_CODE
from ingestion.parser import parse
from ingestion.tabular import Table
from ingestion.supervisor import MAX_OUTPUT, collect_output, decode_result, terminate_group, inspect_bytes

LIMITS = ImportLimits(100, 8, 4096, 65536, 10)


def inspect_local(content: bytes, format_name: str = "CSV", limits: ImportLimits = LIMITS) -> dict[str, Any]:
    with TemporaryDirectory() as temporary:
        path = Path(temporary) / "data"
        path.write_bytes(content)
        return parse(path, format_name, limits)


def parquet_bytes(frame: pl.DataFrame) -> bytes:
    with TemporaryDirectory() as temporary:
        path = Path(temporary) / "data"
        frame.write_parquet(path, compression="zstd")
        return path.read_bytes()


class ParserTests(TestCase):
    def reject(self, content: bytes, code: str = "INVALID_SCHEMA", format_name: str = "CSV", limits: ImportLimits = LIMITS) -> None:
        with self.assertRaises(ImportRejected) as raised:
            inspect_local(content, format_name, limits)
        self.assertEqual(raised.exception.code, code)

    def test_csv_unicode_and_no_observations(self) -> None:
        result = inspect_local('時間（秒）,位移（公分）\n1,秘密標籤\n2,\n'.encode())
        self.assertEqual(result["row_count"], 2)
        self.assertEqual([c["name"] for c in result["columns"]], ["時間（秒）", "位移（公分）"])
        self.assertNotIn("秘密標籤", json.dumps(result, ensure_ascii=False))
        self.assertEqual(set(result), {"row_count", "columns"})

    def test_csv_quoting_multiline_and_formula_is_literal(self) -> None:
        result = inspect_local(b'x,y\r\n1,"two\nlines"\r\n2,"=HYPERLINK(""literal"")"\r\n')
        self.assertEqual(result["row_count"], 2)

    def test_csv_duplicate_empty_and_missing_header(self) -> None:
        for content in (b'x,x\n1,2\n', b'x,\n1,2\n', b'\n', b'', b'x,\x00y\n1,2\n'):
            self.reject(content)

    def test_csv_wrong_width_blank_rows_and_bad_quotes(self) -> None:
        for content in (b'x,y\n1\n', b'x,y\n1,2,3\n', b'x,y\n\n', b'x,y\n1,"unterminated\n', b'x,y\n1,"a"b\n'):
            self.reject(content)

    def test_text_invalid_utf8_and_surrogate(self) -> None:
        self.reject(b'x\n\xff')
        self.reject(b'[{"x":"\\ud800"}]', format_name="JSON")

    def test_csv_header_only(self) -> None:
        self.assertEqual(inspect_local(b'x,y\n')["row_count"], 0)

    def test_csv_row_and_column_boundaries(self) -> None:
        limits = replace(LIMITS, max_rows=2, max_columns=2)
        self.assertEqual(inspect_local(b'x,y\n1,2\n3,4\n', limits=limits)["row_count"], 2)
        self.reject(b'x,y\n1,2\n3,4\n5,6\n', LIMIT_CODE, limits=limits)
        self.reject(b'x,y,z\n1,2,3\n', LIMIT_CODE, limits=limits)

    def test_csv_cell_limits_count_utf8_bytes(self) -> None:
        limits = replace(LIMITS, max_cell_utf8_bytes=3)
        self.assertEqual(inspect_local('x\n中\n'.encode(), limits=limits)["row_count"], 1)
        self.reject('x\n中文\n'.encode(), LIMIT_CODE, limits=limits)
        self.reject(b'x\n1234\n', LIMIT_CODE, limits=limits)

    def test_decoded_bytes_exact_boundary(self) -> None:
        limits = replace(LIMITS, max_decoded_bytes=5)
        self.assertEqual(inspect_local(b'x,y\n1,22\n', limits=limits)["row_count"], 1)
        self.reject(b'x,y\n1,222\n', LIMIT_CODE, limits=limits)

    def test_json_scalars_and_reordered_columns(self) -> None:
        content = b'[{"x":null,"y":true},{"y":false,"x":"literal"},{"x":1.25,"y":2}]'
        result = inspect_local(content, "JSON")
        self.assertEqual(result["row_count"], 3)
        self.assertEqual(result["columns"], [{"name": "x", "physical_type": "JSON_SCALAR"}, {"name": "y", "physical_type": "JSON_SCALAR"}])

    def test_json_escapes_and_brackets_in_strings(self) -> None:
        content = json.dumps([{"x": 'text [ { } ] " \\ \n 中文'}]).encode()
        self.assertEqual(inspect_local(content, "JSON")["row_count"], 1)

    def test_json_duplicate_and_escaped_duplicate(self) -> None:
        for content in (b'[{"x":1,"x":2}]', b'[{"x":1,"\\u0078":2}]'):
            self.reject(content, format_name="JSON")

    def test_json_nested_objects_arrays_and_nonfinite(self) -> None:
        for content in (b'[{"x":{}}]', b'[{"x":[]}]', b'[{"x":NaN}]', b'[{"x":Infinity}]', b'[{"x":1e400}]'):
            self.reject(content, format_name="JSON")

    def test_json_grammar_and_flat_shapes(self) -> None:
        for content in (b'[]', b'{}', b'[{}]', b'[{"x":1},]', b'[{"x":1}] true', b'[{"x":1}', b'[{"x":1},{"y":2}]', b'[1]', b'[{"x":1} {"x":2}]', b'[{"x":1}, {"x":2,"y":3}]'):
            self.reject(content, format_name="JSON")

    def test_json_limits(self) -> None:
        self.reject(b'[{"x":"12345"}]', LIMIT_CODE, "JSON", replace(LIMITS, max_cell_utf8_bytes=4))
        self.reject(b'[{"x":1},{"x":2}]', LIMIT_CODE, "JSON", replace(LIMITS, max_rows=1))
        self.reject(b'[{"x":1,"y":2}]', LIMIT_CODE, "JSON", replace(LIMITS, max_columns=1))
        self.reject(b'[{"x":"1234567890"}]', LIMIT_CODE, "JSON", replace(LIMITS, max_decoded_bytes=8))

    def test_column_names_are_preserved_and_bounded(self) -> None:
        result = inspect_local(b' x ,Y\n1,2\n')
        self.assertEqual([c["name"] for c in result["columns"]], [" x ", "Y"])
        self.reject((('x' * 257) + '\n1\n').encode())

    def test_parquet_scalar_anddecode_result_only(self) -> None:
        frame = pl.DataFrame({"x": [1, 2, 3], "y": ["private", None, "NaN"]})
        result = inspect_local(parquet_bytes(frame), "PARQUET")
        self.assertEqual(result["row_count"], 3)
        self.assertNotIn("private", json.dumps(result))
        self.assertEqual([c["physical_type"] for c in result["columns"]], ["Int64", "String"])

    def test_parquet_nonfinite_not_dropped(self) -> None:
        frame = pl.DataFrame({"x": [float("nan"), float("inf"), None]})
        self.assertEqual(inspect_local(parquet_bytes(frame), "PARQUET")["row_count"], 3)

    def test_parquet_schema_only(self) -> None:
        content = parquet_bytes(pl.DataFrame(schema={"x": pl.Float64}))
        self.assertEqual(inspect_local(content, "PARQUET")["row_count"], 0)

    def test_parquet_nested_binary_and_fake_format(self) -> None:
        for frame in (pl.DataFrame({"x": [[1, 2]]}), pl.DataFrame({"x": [b"raw"]}), pl.DataFrame({"x": [{"a": 1}]})):
            self.reject(parquet_bytes(frame), format_name="PARQUET")
        for content in (b'x,y\n1,2\n', b'PAR1fakePAR1', b'PAR1'):
            self.reject(content, format_name="PARQUET")

    def test_compressed_parquet_limits(self) -> None:
        content = parquet_bytes(pl.DataFrame({"x": ["a" * 2048] * 1000}))
        self.assertLess(len(content), 10000)
        self.reject(content, LIMIT_CODE, "PARQUET", replace(LIMITS, max_rows=1000, max_cell_utf8_bytes=1024))
        self.reject(content, LIMIT_CODE, "PARQUET", replace(LIMITS, max_rows=1000, max_decoded_bytes=4096))
        self.reject(content, LIMIT_CODE, "PARQUET", replace(LIMITS, max_rows=2))

    def test_unknown_format(self) -> None:
        self.reject(b'x\n1\n', "UNSUPPORTED_MEDIA_TYPE", "PICKLE")

    def test_all_limits_required_positive_and_hard_bounded(self) -> None:
        for field in LIMITS.document():
            for value in (0, -1, True, 1000000000):
                with self.subTest(field=field, value=value), self.assertRaises(ImportRejected):
                    replace(LIMITS, **{field: value})

    def test_encoded_json_overhead_is_not_decoded_usage(self) -> None:
        limits = replace(LIMITS, max_decoded_bytes=2)
        self.assertEqual(inspect_local(b'[{"x":1}]', "JSON", limits)["row_count"], 1)
        self.assertEqual(inspect_local(b'x\n', limits=replace(LIMITS, max_decoded_bytes=1))["row_count"], 0)

    def test_parser_order_and_null_rows_are_retained(self) -> None:
        observed: list[list[object]] = []
        original = Table.append
        def record(table: Table, values: Sequence[object]) -> None:
            row: list[object] = list(values)
            observed.append(row)
            original(table, row)
        with patch("ingestion.tabular.Table.append", new=record):
            inspect_local(b'[{"x":3,"y":null},{"y":9,"x":1}]', "JSON")
        self.assertEqual(observed, [[3, None], [1, 9]])

    def test_worker_output_validation(self) -> None:
        for raw in (b'null', b'[]', b'{"status":"PASS","metadata":{"row_count":1,"columns":[]}}',
                    b'{"status":"REJECTED","code":"private text"}', b'{"status":"PASS","metadata":{"row_count":true,"columns":[1]}}',
                    b'{"status":"PASS","metadata":{"row_count":1,"columns":[{"name":"x","physical_type":"TEXT","sample":"private"}]}}'):
            with self.subTest(raw=raw), self.assertRaises(ImportRejected):
                decode_result(raw, LIMITS)

    def test_nonlinux_fails_closed(self) -> None:
        with patch("ingestion.supervisor.sys.platform", "darwin"):
            with self.assertRaises(ImportRejected) as raised:
                inspect_bytes(b'x\n1\n', "CSV", LIMITS)
        self.assertEqual(raised.exception.code, "DEPENDENCY_UNAVAILABLE")


@skipUnless(sys.platform == "linux", "OS enforcement evidence requires Linux")
class ProcessTests(TestCase):
    def test_three_real_worker_formats(self) -> None:
        cases = [(b'x,y\n1,3\n2,5\n', "CSV"), (b'[{"x":1,"y":3},{"x":2,"y":5}]', "JSON"),
                 (parquet_bytes(pl.DataFrame({"x": [1, 2], "y": [3, 5]})), "PARQUET")]
        for content, format_name in cases:
            report = inspect_bytes(content, format_name, LIMITS)
            self.assertEqual(report["metadata"]["row_count"], 2)
            self.assertEqual(report["source_sha256"], hashlib.sha256(content).hexdigest())

    def test_real_worker_rejects_limits_and_bad_format(self) -> None:
        for content, format_name in ((b'x\n12345\n', "CSV"), (b'[{"x":"12345"}]', "JSON"),
                                     (parquet_bytes(pl.DataFrame({"x": ["12345"]})), "PARQUET")):
            limits = replace(LIMITS, max_cell_utf8_bytes=4)
            with self.assertRaises(ImportRejected) as raised:
                inspect_bytes(content, format_name, limits)
            self.assertEqual(raised.exception.code, LIMIT_CODE)

    def test_production_spawn_strips_secrets_and_uses_private_files(self) -> None:
        spawn = subprocess.Popen
        observed: list[dict[str, Any]] = []
        def record_spawn(*args: Any, **kwargs: Any) -> subprocess.Popen[Any]:
            directory = Path(kwargs["cwd"])
            observed.append({"environment": kwargs["env"], "directory_mode": stat.S_IMODE(directory.stat().st_mode),
                             "file_mode": stat.S_IMODE((directory / "input").stat().st_mode), "session": kwargs["start_new_session"]})
            return spawn(*args, **kwargs, text=False)
        with patch.dict(os.environ, {"AXIOM_SECRET_KEY": "synthetic-private-canary", "AXIOM_DB_PASSWORD": "synthetic-private-canary"}):
            with patch("ingestion.supervisor.subprocess.Popen", side_effect=record_spawn):
                inspect_bytes(b'x\n1\n', "CSV", LIMITS)
        self.assertEqual(set(observed[0]["environment"]), {"POLARS_MAX_THREADS", "LANG"})
        self.assertEqual(observed[0]["directory_mode"], 0o700)
        self.assertEqual(observed[0]["file_mode"], 0o400)
        self.assertTrue(observed[0]["session"])

    def test_temporary_copy_is_cleaned(self) -> None:
        with TemporaryDirectory() as directory:
            with patch("ingestion.supervisor.tempfile.tempdir", directory):
                inspect_bytes(b'x\n1\n', "CSV", LIMITS)
                with self.assertRaises(ImportRejected):
                    inspect_bytes(b'x,x\n1,2\n', "CSV", LIMITS)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_wall_deadline_and_process_reaping(self) -> None:
        with subprocess.Popen([sys.executable, "-I", "-c", "import time; time.sleep(10)"], stdout=subprocess.PIPE, start_new_session=True) as process:
            try:
                with self.assertRaises(ImportRejected) as raised:
                    collect_output(process, 1)
                self.assertEqual(raised.exception.code, LIMIT_CODE)
            finally:
                terminate_group(process)
            self.assertIsNotNone(process.returncode)

    def test_stdout_is_bounded(self) -> None:
        script = "import sys; sys.stdout.write('x' * " + str(MAX_OUTPUT + 1) + "); sys.stdout.flush()"
        with subprocess.Popen([sys.executable, "-I", "-c", script], stdout=subprocess.PIPE, start_new_session=True) as process:
            try:
                with self.assertRaises(ImportRejected) as raised:
                    collect_output(process, 3)
                self.assertEqual(raised.exception.code, LIMIT_CODE)
            finally:
                terminate_group(process)

    def enforcement_script(self, statement: str) -> str:
        directory = str(Path(__file__).resolve().parents[1])
        return "import sys; sys.path.insert(0," + repr(directory) + "); from ingestion.worker import configure; configure(1); " + statement

    def test_actual_address_space_limit(self) -> None:
        script = self.enforcement_script("x=bytearray(2*1024*1024*1024)")
        result = subprocess.run([sys.executable, "-I", "-B", "-c", script], capture_output=True, timeout=5, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"MemoryError", result.stderr)

    def test_actual_cpu_limit(self) -> None:
        script = self.enforcement_script("\nwhile True: pass")
        result = subprocess.run([sys.executable, "-I", "-B", "-c", script], capture_output=True, timeout=6, check=False)
        self.assertEqual(result.returncode, -signal.SIGKILL)

    def test_worker_environment_and_limits(self) -> None:
        script = self.enforcement_script("import os,resource,json; print(json.dumps({'env':dict(os.environ),'memory':resource.getrlimit(resource.RLIMIT_AS),'file':resource.getrlimit(resource.RLIMIT_FSIZE),'core':resource.getrlimit(resource.RLIMIT_CORE)}))")
        result = subprocess.run([sys.executable, "-I", "-B", "-c", script], capture_output=True, timeout=5, check=True, env={"LANG": "C.UTF-8"})
        report = json.loads(result.stdout)
        self.assertNotIn("AXIOM_SECRET_KEY", report["env"])
        self.assertEqual(report["memory"], [1073741824, 1073741824])
        self.assertEqual(report["file"], [0, 0])
        self.assertEqual(report["core"], [0, 0])
