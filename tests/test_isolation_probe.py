"""Canary fail-closed reporting and identity checks; actual UID tests run in Docker."""
from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from tools.benchmark import access_child, isolation_probe as isolation


def solver_result() -> isolation.JsonObject:
    return {"uid": isolation.SOLVER_UID, "gid": isolation.SOLVER_UID, "effective_capabilities": 0,
            "exit_code": 0, "identity_verified": True, "public_access": "ALLOWED",
            "sealed_access": "DENIED", "directory_access": "DENIED", "sealed_digest": None}


def evaluator_result() -> isolation.JsonObject:
    return {"uid": isolation.EVALUATOR_UID, "gid": isolation.EVALUATOR_UID, "effective_capabilities": 0,
            "exit_code": 0, "identity_verified": True, "public_access": "ALLOWED",
            "sealed_access": "ALLOWED", "directory_access": "ALLOWED", "sealed_digest": "synthetic-digest"}


class IsolationProbeTests(unittest.TestCase):
    def test_solver_requires_real_identity_no_capabilities_and_actual_denial(self) -> None:
        result = solver_result()
        self.assertTrue(isolation.solver_isolated(result))
        mutations = {"uid": 0, "gid": 0, "exit_code": 1, "identity_verified": False,
                     "effective_capabilities": 1, "public_access": "ERROR", "sealed_access": "ALLOWED",
                     "directory_access": "ALLOWED", "sealed_digest": "leaked"}
        for field, value in mutations.items():
            with self.subTest(field=field):
                changed = dict(result)
                changed[field] = value
                self.assertFalse(isolation.solver_isolated(changed))
        result["sealed_access"] = "ERROR"
        self.assertFalse(isolation.solver_isolated(result))

    def test_bool_cannot_impersonate_zero_capabilities_or_exit_code(self) -> None:
        for field in ("effective_capabilities", "exit_code"):
            with self.subTest(field=field):
                result = solver_result()
                result[field] = False
                self.assertFalse(isolation.solver_isolated(result))

    def test_evaluator_must_read_the_correct_canary_and_have_no_capabilities(self) -> None:
        result = evaluator_result()
        self.assertTrue(isolation.evaluator_authorized(result, "synthetic-digest"))
        self.assertFalse(isolation.evaluator_authorized(result, "different"))
        result["effective_capabilities"] = 1
        self.assertFalse(isolation.evaluator_authorized(result, "synthetic-digest"))

    def test_public_report_uses_a_whitelist_without_nonce_or_digest(self) -> None:
        source = evaluator_result()
        source.update(nonce="do-not-export", private_label="do-not-export")
        report = isolation.sanitized_result(source)
        self.assertNotIn("sealed_digest", report)
        self.assertNotIn("nonce", report)
        self.assertNotIn("private_label", report)
        self.assertNotIn("synthetic-digest", json.dumps(report))

    def test_missing_file_is_error_not_permission_denial(self) -> None:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "missing"
            self.assertEqual(access_child.file_access(path), ("ERROR", None))
            self.assertEqual(access_child.directory_access(path), "ERROR")
        with patch.object(Path, "read_bytes", side_effect=PermissionError):
            self.assertEqual(access_child.file_access(Path("sealed")), ("DENIED", None))

    def test_actual_worker_launch_parameters_clear_groups_and_environment(self) -> None:
        completed = subprocess.CompletedProcess(["child"], 0, stdout=json.dumps(solver_result()), stderr="")
        with patch.object(isolation.subprocess, "run", return_value=completed) as run:
            result = isolation.run_child(Path("/public/solver.json"), Path("/sealed/canary"), isolation.SOLVER_UID, "solver")
        self.assertTrue(isolation.solver_isolated(result))
        self.assertEqual(run.call_args.kwargs["user"], isolation.SOLVER_UID)
        self.assertEqual(run.call_args.kwargs["group"], isolation.SOLVER_UID)
        self.assertEqual(run.call_args.kwargs["extra_groups"], [])
        self.assertEqual(run.call_args.kwargs["env"], {"LANG": "C.UTF-8"})
        self.assertEqual(run.call_args.kwargs["timeout"], 10)

    def test_child_non_object_output_is_rejected(self) -> None:
        completed = subprocess.CompletedProcess(["child"], 0, stdout="[]", stderr="")
        with patch.object(isolation.subprocess, "run", return_value=completed), self.assertRaises(ValueError):
            isolation.run_child(Path("/public/file"), Path("/sealed/canary"), isolation.SOLVER_UID, "solver")

    def test_negative_controls_must_actually_detect_a_readable_canary(self) -> None:
        for leaked, expected in ((True, "PASS"), (False, "FAIL")):
            with self.subTest(leaked=leaked), TemporaryDirectory() as temporary:
                root = Path(temporary)
                sealed = root / "sealed/canary"
                sealed.parent.mkdir()
                sealed.write_bytes(b"synthetic")
                wrong = {**solver_result(), "identity_verified": False, "exit_code": 1}
                leaky = {**solver_result(), "sealed_access": "ALLOWED" if leaked else "DENIED", "exit_code": 1}
                missing = {**solver_result(), "sealed_access": "ERROR", "exit_code": 1}
                with patch.object(isolation, "prepare_workspace", return_value=(root / "public", sealed, "synthetic-digest")), \
                     patch.object(isolation, "run_child", side_effect=[solver_result(), evaluator_result(), wrong, leaky, missing]):
                    report = isolation.exercise_isolation(root)
                self.assertEqual(report["status"], expected)
                self.assertNotIn("synthetic-digest", json.dumps(report))

    def test_non_linux_host_is_not_reported_as_an_isolation_pass(self) -> None:
        stdout = io.StringIO()
        with patch.object(isolation.platform, "system", return_value="Darwin"), \
             patch("sys.argv", ["isolation"]), redirect_stdout(stdout):
            self.assertEqual(isolation.main(), 2)
        report = json.loads(stdout.getvalue())
        self.assertEqual(report["status"], "NOT_RUN")
        self.assertEqual(report["product_status"], "NOT_RUN")

    def test_runtime_errors_are_failures_without_private_exception_text(self) -> None:
        stdout = io.StringIO()
        with patch.object(isolation.platform, "system", return_value="Linux"), \
             patch.object(isolation.os, "geteuid", return_value=0), \
             patch.object(isolation, "exercise_isolation", side_effect=ValueError("private-canary-value")), \
             patch("sys.argv", ["isolation"]), redirect_stdout(stdout):
            self.assertEqual(isolation.main(), 1)
        report = json.loads(stdout.getvalue())
        self.assertEqual(report["status"], "FAIL")
        self.assertNotIn("private-canary-value", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
