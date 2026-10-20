"""T02 probe reporting, disposable-service guards and worker cleanup regressions."""
from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from tools.compatibility import python_probe as probe


class CompatibilityProbeTests(unittest.TestCase):
    def test_probe_pass_and_skip_are_distinct(self) -> None:
        passed = probe.run_probe("sample", lambda: "checked")
        self.assertEqual((passed.status, passed.detail), ("PASS", "checked"))
        skipped = Mock(side_effect=probe.NotRunError("not configured"))
        result = probe.run_probe("service", skipped)
        self.assertEqual((result.status, result.detail), ("NOT_RUN", "not configured"))

    def test_failure_redacts_driver_credentials(self) -> None:
        failed = Mock(side_effect=RuntimeError("postgresql://user:secret@host/database"))
        result = probe.run_probe("database", failed)
        self.assertEqual(result.status, "FAIL")
        self.assertEqual(result.detail, "RuntimeError")
        self.assertNotIn("secret", result.detail)

    def test_empty_or_failed_probe_set_cannot_pass(self) -> None:
        self.assertFalse(probe.successful([], False))
        results = [probe.ProbeResult("failure", "FAIL", "error")]
        self.assertFalse(probe.successful(results, False))
        self.assertFalse(probe.successful(results, True))

    def test_strict_mode_rejects_not_run_services(self) -> None:
        results = [probe.ProbeResult("local", "PASS", "ok"), probe.ProbeResult("postgresql", "NOT_RUN", "absent")]
        self.assertTrue(probe.successful(results, False))
        self.assertFalse(probe.successful(results, True))
        self.assertTrue(probe.successful([results[0]], True))

    def test_critical_skips_and_all_skipped_services_cannot_pass(self) -> None:
        critical = [probe.ProbeResult("django_drf", "NOT_RUN", "absent")]
        services = [probe.ProbeResult("postgresql", "NOT_RUN", "absent")]
        self.assertFalse(probe.successful(critical, False))
        self.assertFalse(probe.successful(services, False))

    def test_postgres_guard_rejects_other_databases_and_incomplete_urls(self) -> None:
        urls = ["sqlite:///axiom_compat", "postgresql://user:password@host/production",
                "postgresql://user@host/axiom_compat", "postgresql:///axiom_compat",
                "postgresql://user:password@host:invalid/axiom_compat"]
        for url in urls:
            with self.subTest(url=url), self.assertRaises(ValueError):
                probe.database_settings(url)

    def test_postgres_configuration_decodes_credentials_and_sets_timeout(self) -> None:
        settings = probe.database_settings("postgresql://user:p%40ss@postgres:5433/axiom_compat")
        self.assertEqual(settings["PASSWORD"], "p@ss")
        self.assertEqual(settings["PORT"], "5433")
        self.assertEqual(settings["OPTIONS"], {"connect_timeout": 5})

    def test_services_require_explicit_disposable_opt_in(self) -> None:
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(probe.NotRunError):
            probe.require_disposable()
        with patch.dict(os.environ, {probe.DISPOSABLE_ENV: "1"}, clear=True):
            probe.require_disposable()
            with self.assertRaises(probe.NotRunError):
                probe.redis_configuration()
            with self.assertRaises(probe.NotRunError):
                probe.postgres_probe()

    def test_redis_guard_rejects_non_disposable_databases(self) -> None:
        for url in ("redis://redis/0", "https://redis/13", "redis:///13"):
            with self.subTest(url=url), patch.dict(os.environ, {
                probe.DISPOSABLE_ENV: "1", probe.REDIS_ENV: url,
            }, clear=True), self.assertRaises(ValueError):
                probe.redis_configuration()

    def test_worker_is_stopped_and_result_forgotten_after_task_timeout(self) -> None:
        client = Mock()
        app = Mock()
        app.send_task.return_value.get.side_effect = TimeoutError("private broker connection")
        worker = Mock()
        worker.wait.side_effect = [subprocess.TimeoutExpired("celery", 10), 0]
        redis_module = Mock()
        redis_module.Redis.from_url.return_value = client
        celery_module = Mock(app=app)
        with patch.object(probe, "redis_configuration", return_value="redis://redis/13"), \
             patch.object(probe, "import_module", side_effect=[redis_module, celery_module]), \
             patch.object(probe.subprocess, "Popen", return_value=worker):
            result = probe.run_probe("worker", probe.celery_probe)
        self.assertEqual((result.status, result.detail), ("FAIL", "TimeoutError"))
        worker.terminate.assert_called_once()
        worker.kill.assert_called_once()
        app.send_task.return_value.forget.assert_called_once()
        client.close.assert_called_once()
        app.close.assert_called_once()

    def test_worker_is_stopped_if_dispatch_fails(self) -> None:
        app = Mock()
        app.send_task.side_effect = RuntimeError("dispatch failed")
        redis_module = Mock()
        worker = Mock()
        with patch.object(probe, "redis_configuration", return_value="redis://redis/13"), \
             patch.object(probe, "import_module", side_effect=[redis_module, Mock(app=app)]), \
             patch.object(probe.subprocess, "Popen", return_value=worker):
            result = probe.run_probe("worker", probe.celery_probe)
        self.assertEqual(result.status, "FAIL")
        worker.terminate.assert_called_once()
        app.close.assert_called_once()

    def test_cli_strict_mode_records_missing_services_and_writes_json(self) -> None:
        with TemporaryDirectory() as temporary:
            output = Path(temporary) / "report.json"
            for strict, expected in ((False, 0), (True, 1)):
                arguments = ["python_probe", "--output", str(output)]
                if strict:
                    arguments.append("--require-services")
                stdout = io.StringIO()
                with self.subTest(strict=strict), \
                     patch.object(probe, "django_probe", return_value="local checked"), \
                     patch.object(probe, "postgres_probe", side_effect=probe.NotRunError("absent")), \
                     patch.object(probe, "celery_probe", side_effect=probe.NotRunError("absent")), \
                     patch.object(probe, "numerical_probe", return_value="checked"), \
                     patch.object(probe, "precision_table_probe", return_value="checked"), \
                     patch.object(probe, "inventory", return_value=[]), \
                     patch("sys.argv", arguments), redirect_stdout(stdout):
                    self.assertEqual(probe.main(), expected)
                report = json.loads(output.read_text(encoding="utf-8"))
                self.assertEqual(report, json.loads(stdout.getvalue()))
                self.assertEqual(report["product_status"], "NOT_RUN")
                self.assertEqual(report["checks"][1]["status"], "NOT_RUN")
                self.assertEqual(report["status"], "FAIL" if strict else "PASS")


if __name__ == "__main__":
    unittest.main()
