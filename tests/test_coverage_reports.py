"""Coverage 匯入前的路徑與完整性檢查反例。"""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from tools import check_coverage_reports as reports


class CoverageReportTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        self.enterContext(patch.object(reports, "ROOT", self.root))
        for folder in ("backend/catalog", "reports", "frontend/src", "frontend/coverage"):
            (self.root / folder).mkdir(parents=True)
        (self.root / "backend/catalog/service.py").write_text("pass\n")
        (self.root / "frontend/src/App.vue").write_text("<template>Hello</template>\n")
        (self.root / "frontend/src/main.ts").write_text("export {}\n")
        (self.root / "reports/backend-coverage.xml").write_text(
            '<coverage lines-valid="1" branches-valid="1"><sources><source>backend</source></sources>'
            '<packages><package><classes><class filename="catalog/service.py"/>'
            '</classes></package></packages></coverage>')
        (self.root / "frontend/coverage/lcov.info").write_text(
            "SF:frontend/src/App.vue\nDA:1,0\nend_of_record\n"
            "SF:frontend/src/main.ts\nDA:1,1\nend_of_record\n")

    def test_portable_reports_include_uncovered_vue(self) -> None:
        self.assertEqual(reports.check_backend(), 1)
        self.assertEqual(reports.check_frontend(), 2)

    def test_frontend_cannot_hide_unimported_sources(self) -> None:
        (self.root / "frontend/src/Ungraded.vue").write_text("<template>Uncovered</template>\n")
        with self.assertRaisesRegex(ValueError, "every src"):
            reports.check_frontend()

    def test_container_absolute_path_and_traversal_are_rejected(self) -> None:
        for name in ("/app/catalog/service.py", "../backend/catalog/service.py"):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "repository-relative"):
                reports.source_path(name, "backend")

    def test_missing_report_source_is_rejected(self) -> None:
        (self.root / "backend/catalog/service.py").unlink()
        with self.assertRaisesRegex(ValueError, "does not exist"):
            reports.check_backend()

    def test_empty_backend_measurement_is_rejected(self) -> None:
        (self.root / "reports/backend-coverage.xml").write_text('<coverage lines-valid="0" branches-valid="0"/>')
        with self.assertRaisesRegex(ValueError, "no lines or branches"):
            reports.check_backend()


if __name__ == "__main__":
    unittest.main()
