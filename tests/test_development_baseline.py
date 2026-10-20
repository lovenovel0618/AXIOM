"""Regression tests for T01 traceability and fail-closed development readiness."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from tools.development_baseline import (
    BASELINE_PATH, DEPENDENCIES, REPOSITORY, SCHEMA_PATH, SOURCE_PATHS,
    JsonObject, Report, check_graph, read_object, validate_baseline,
)


class BaselineTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for relative in SOURCE_PATHS | {SCHEMA_PATH, BASELINE_PATH}:
            destination = self.root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(REPOSITORY / relative, destination)
        self.document = read_object(self.root / BASELINE_PATH)

    def validate(self, document: JsonObject) -> Report:
        path = self.root / BASELINE_PATH
        path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
        return validate_baseline(self.root, path)

    def assert_invalid(self, document: JsonObject, error_fragment: str) -> None:
        report = self.validate(document)
        self.assertEqual(report.validation_status, "FAIL")
        self.assertFalse(report.m0_ready)
        self.assertIn(error_fragment, "\n".join(report.errors))

    def test_actual_baseline_reports_pending_work(self) -> None:
        report = self.validate(self.document)
        self.assertEqual(report.validation_status, "PASS", report.errors)
        self.assertEqual((report.requirements, report.decisions, report.tickets), (21, 9, 8))
        self.assertFalse(report.m0_ready)
        self.assertEqual(report.product_status, "NOT_RUN")
        self.assertTrue(any("D-03" in blocker for blocker in report.blockers))
        self.assertEqual(report.development_mode, "SOLO")
        self.assertEqual(report.review_method, "SELF_REVIEW")
        self.assertFalse(any("unassigned" in blocker for blocker in report.blockers))

    def test_missing_requirement(self) -> None:
        self.document["requirements"].pop()
        self.assert_invalid(self.document, "requirements")

    def test_duplicate_requirement(self) -> None:
        self.document["requirements"][1] = deepcopy(self.document["requirements"][0])
        self.assert_invalid(self.document, "Duplicate or incomplete requirements")

    def test_requirement_trace_fields_cannot_drift(self) -> None:
        for field in ("delivery", "documents", "acceptance", "gates"):
            with self.subTest(field=field):
                document = deepcopy(self.document)
                document["requirements"][0][field] = "altered"
                self.assert_invalid(document, "REQ-001")

    def test_mvp_cannot_expand_or_drop_baseline_requirements(self) -> None:
        for identifier in ("REQ-004", "REQ-011", "NFR-004"):
            with self.subTest(identifier=identifier):
                document = deepcopy(self.document)
                row = next(row for row in document["requirements"] if row["id"] == identifier)
                row["scope"] = "MVP_BASELINE" if row["scope"] == "FUTURE" else "FUTURE"
                self.assert_invalid(document, "MVP scope drift: " + identifier)

    def test_authority_changes_require_review(self) -> None:
        source = self.root / self.document["sources"][0]["path"]
        source.write_text(source.read_text(encoding="utf-8") + "\nchanged\n", encoding="utf-8")
        self.assert_invalid(self.document, "Authority hash changed")

    def test_sources_cannot_duplicate_or_escape(self) -> None:
        duplicate = deepcopy(self.document)
        duplicate["sources"][1] = deepcopy(duplicate["sources"][0])
        self.assert_invalid(duplicate, "Duplicate or incomplete authority sources")
        self.document["sources"][0]["path"] = "../outside.txt"
        self.assert_invalid(self.document, "sources")

    def test_symlink_cannot_escape_repository(self) -> None:
        with TemporaryDirectory() as external:
            target = Path(external) / "source.md"
            target.write_text("outside repository", encoding="utf-8")
            source = self.root / self.document["sources"][0]["path"]
            source.unlink()
            source.symlink_to(target)
            self.assert_invalid(self.document, "escapes repository")

    def test_decision_trace_and_approval_cannot_be_fabricated(self) -> None:
        for field, value in (("owner_role", "someone"), ("status", "APPROVED"),
                             ("approved_by", "Backend/QA"), ("evidence_uri", "invented")):
            with self.subTest(field=field):
                document = deepcopy(self.document)
                document["decisions"][0][field] = value
                self.assert_invalid(document, "D-01" if field == "owner_role" else "decisions")

    def test_missing_and_duplicate_decisions_and_tickets(self) -> None:
        for collection in ("decisions", "tickets"):
            with self.subTest(collection=collection):
                document = deepcopy(self.document)
                document[collection][1] = deepcopy(document[collection][0])
                self.assert_invalid(document, "Duplicate or incomplete " + collection)
                document[collection].pop()
                self.assert_invalid(document, collection)

    def test_ticket_dependencies_cannot_skip_or_duplicate_preconditions(self) -> None:
        for dependencies in ([], ["T01", "T01"], ["T02"], ["T08"], ["T99"]):
            with self.subTest(dependencies=dependencies):
                document = deepcopy(self.document)
                document["tickets"][1]["depends_on"] = dependencies
                self.assert_invalid(document, "ticket" if dependencies == [] else "depend")

    def test_dependency_graph_detects_cycles_and_unknown_tickets(self) -> None:
        check_graph(DEPENDENCIES)
        for graph, error in (({"T01": {"T01"}}, "Cyclic"),
                             ({"T01": {"T02"}, "T02": {"T01"}}, "Cyclic"),
                             ({"T01": {"T99"}}, "Unknown"),
                             ({"T01": {"T02", "T99"}, "T02": set[str]()}, "Unknown")):
            with self.subTest(graph=graph), self.assertRaisesRegex(ValueError, error):
                check_graph(graph)

    def test_ticket_summary_and_deliverable_are_traced(self) -> None:
        for field in ("summary", "deliverable"):
            with self.subTest(field=field):
                document = deepcopy(self.document)
                document["tickets"][0][field] = "altered"
                self.assert_invalid(document, "Ticket authority drift: T01")

    def test_solo_owner_can_review_their_own_code(self) -> None:
        report = self.validate(self.document)
        self.assertEqual(report.validation_status, "PASS", report.errors)
        ticket = self.document["tickets"][0]
        self.assertEqual(ticket["owner"], ticket["reviewer"])
        self.assertEqual(report.review_method, "SELF_REVIEW")

    def test_solo_assignments_cannot_invent_another_developer(self) -> None:
        for role in ("owner", "reviewer"):
            with self.subTest(role=role):
                document = deepcopy(self.document)
                document["tickets"][0][role] = "another-person"
                self.assert_invalid(document, "SOLO ticket must use the project developer")

    def test_solo_assignment_is_required_and_not_blank(self) -> None:
        for value in (None, "", "  "):
            with self.subTest(value=value):
                document = deepcopy(self.document)
                document["tickets"][0]["owner"] = value
                self.assert_invalid(document, "owner")

    def test_solo_mode_and_self_review_cannot_claim_independence(self) -> None:
        for field, value in (("mode", "TEAM"), ("review_method", "INDEPENDENT_REVIEW")):
            with self.subTest(field=field):
                document = deepcopy(self.document)
                document["development"][field] = value
                self.assert_invalid(document, "development")
        del self.document["development"]
        self.assert_invalid(self.document, "development")

    def test_trailing_newline_cannot_bypass_name_validation(self) -> None:
        self.document["tickets"][0].update(owner="Developer\n", reviewer="Reviewer")
        self.assert_invalid(self.document, "surrounding whitespace")

    def test_invalid_schema_returns_failure_report(self) -> None:
        (self.root / SCHEMA_PATH).write_text(
            '{"type":"invalid-type"}', encoding="utf-8",
        )
        report = self.validate(self.document)
        self.assertEqual(report.validation_status, "FAIL")
        self.assertEqual(report.errors, ["SchemaError: Invalid baseline schema"])

    def test_named_assignments_do_not_close_m0(self) -> None:
        self.document["development"]["developer_id"] = "solo-developer"
        for ticket in self.document["tickets"]:
            ticket.update(owner="solo-developer", reviewer="solo-developer")
        report = self.validate(self.document)
        self.assertEqual(report.validation_status, "PASS", report.errors)
        self.assertFalse(report.m0_ready)
        self.assertFalse(any("unassigned" in blocker for blocker in report.blockers))

    def test_ticket_progress_cannot_be_advanced_without_review(self) -> None:
        self.document["tickets"][1]["status"] = "IN_PROGRESS"
        self.assert_invalid(self.document, "Ticket progress requires")

    def test_unknown_fields_and_fake_product_success_are_rejected(self) -> None:
        unknown = deepcopy(self.document)
        unknown["extra"] = True
        self.assert_invalid(unknown, "Additional properties")
        self.document["product_status"] = "PASS"
        self.assert_invalid(self.document, "NOT_RUN")

    def test_invalid_json_is_rejected(self) -> None:
        for content in ('{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}',
                        '{"x":1e400}', '[]', '{', '\ufeff{}'):
            with self.subTest(content=content):
                path = self.root / BASELINE_PATH
                path.write_text(content, encoding="utf-8")
                report = validate_baseline(self.root, path)
                self.assertEqual(report.validation_status, "FAIL")
                self.assertTrue(report.errors)

    def test_missing_file_returns_failure_report(self) -> None:
        report = validate_baseline(self.root, self.root / "absent.json")
        self.assertEqual(report.validation_status, "FAIL")
        self.assertIn("FileNotFoundError", report.errors[0])

    def test_cli_exit_codes_and_external_working_directory(self) -> None:
        script = REPOSITORY / "tools/development_baseline.py"
        path = self.root / "invalid.json"
        path.write_text("{", encoding="utf-8")
        scenarios: tuple[tuple[list[str], int], ...] = (([], 0), (["--require-m0-ready"], 2), (["--baseline", str(path)], 1))
        for arguments, expected in scenarios:
            with self.subTest(arguments=arguments):
                result = subprocess.run(
                    [sys.executable, str(script), *arguments], cwd=self.root,
                    capture_output=True, text=True, check=False, timeout=30,
                )
                self.assertEqual(result.returncode, expected, result.stderr)
                self.assertEqual(result.stderr, "")
                output = json.loads(result.stdout)
                self.assertFalse(output["m0_ready"])
                self.assertEqual(output["product_status"], "NOT_RUN")


if __name__ == "__main__":
    unittest.main()
