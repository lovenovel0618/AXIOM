"""Loopback HTTP upload-to-draft smoke on disposable synthetic observations."""
import json
import secrets
from argparse import ArgumentParser
from typing import Any
from uuid import uuid4
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from catalog.management.commands.business_ingest_smoke import upload, wait_run
from catalog.management.commands.catalog_smoke import BASE, Browser, FRONTEND_BASE
from catalog.models import Account, DeletionRequest, DeletionTarget, Tenant
from catalog.validation import validate_api
from runtime.contracts import JsonObject, identity_hash


def split(rows: int) -> tuple[list[int], list[int], list[int]]:
    """列序 60／20／20 的 EXPLICIT 切分；10 列時與既有冒煙資料逐列相同。"""
    fit = rows * 6 // 10
    development = rows * 2 // 10
    return list(range(fit)), list(range(fit, fit + development)), list(range(fit + development, rows))


def configuration(version: str, rows: int = 10) -> JsonObject:
    fit, development, final_test = split(rows)
    return {
        "dataset_version_id": version,
        "semantic_profile": {"inputs": [{"name": "x", "source_column": "時間（秒）", "unit": [0,0,1,0,0,0,0], "conversion": {"source_unit": "s", "scale": "1", "offset": "0"}}],
            "target": {"name": "y", "source_column": "位移（公分）", "unit": [1,0,0,0,0,0,0], "conversion": {"source_unit": "cm", "scale": "0.01", "offset": "0"}},
            "units_confirmed": True, "time_ordered": False, "measurement_resolution": "0.001", "resolution_reason": "Synthetic independent positions; names alone do not establish time dependence", "group_column": None},
        "budget": {"cpu_seconds": 30, "gpu_seconds": 0, "wall_seconds": 60, "tokens": 0, "candidate_limit": 10, "memory_bytes": 4294967296}, "purpose": "DESCRIPTION",
        "observation_split": {"kind": "EXPLICIT", "dataset_version_id": version, "fit": fit, "development": development, "final_test": final_test, "gap_rows": 0, "lookback_rows": 0, "horizon_rows": 0, "seed": 7, "time_column": None, "group_column": None, "group_assignment_digest": None, "splitter_version": "synthetic-explicit-v1", "policy_version": "2.0", "sealed_final_test": True},
        "domain": [{"name": "x", "lower": {"numerator": "0", "denominator": "1"}, "upper": {"numerator": "10", "denominator": "1"}, "lower_closed": True, "upper_closed": True}],
        "evaluation_policy": {"policy_version": "1.0", "metric_version": "2.0", "error_model": "UNSPECIFIED", "absolute_error_bound": None, "comparison_method": "NONE", "bootstrap_replicates": 2000, "bootstrap_seed": 7, "block_method": None, "block_length": None, "practical_scale_override": None, "practical_margin_ratio": "0.01", "baseline": "FIT_MEAN", "practical_scale_reason": None},
    }


def check(condition: bool, message: str) -> None:
    if not condition:
        raise CommandError(message)


class Command(BaseCommand):
    help = "Exercise real INGEST, Unicode semantic confirmation, DRAFT persistence, sealed PROFILE READY, evidence bundle reads and Fail-Closed source declaration over loopback HTTP"

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--frontend", action="store_true")

    def handle(self, *args: Any, **options: Any) -> None:
        password = secrets.token_urlsafe(24)
        user = User.objects.create_user(username="draft-" + uuid4().hex, password=password)
        account = Account.objects.create(user=user, tenant=Tenant.objects.create(name="draft-synthetic"))
        browser = Browser(FRONTEND_BASE if options["frontend"] else BASE)
        browser.login(user.get_username(), password)
        status, dataset = browser.post("/api/v2/datasets", {"name": "synthetic-draft"})
        check(status == 201, "Dataset rejected")
        content = ('時間（秒）,位移（公分）\n' + ''.join(f'{i},{2*i+1}\n' for i in range(10))).encode()
        _checksum, run = upload(browser, dataset["id"], content, "CSV")
        check(run["status"] == "SUCCEEDED", "Actual INGEST failed")
        status, raw = browser.request(f'/api/v2/datasets/{dataset["id"]}/versions')
        check(status == 200, "Versions unavailable")
        version = json.loads(raw)["items"][0]
        status, research = browser.post("/api/v2/researches", {"name": "manual-confirmation"})
        check(status == 201, "Research rejected")
        path = f'/api/v2/researches/{research["id"]}/versions'
        data = configuration(version["id"])
        encoded = json.dumps(data).encode()
        headers = {"Content-Type": "application/json", "Idempotency-Key": "fixed-draft"}
        status, raw = browser.request(path, "POST", encoded, headers)
        check(status == 201, "Draft rejected")
        draft: JsonObject = json.loads(raw)
        validate_api(draft, "ResearchVersion")
        check(draft["status"] == "DRAFT" and draft["quality_report_id"] is None and draft["observation_split"]["sealed_test_id"] is None, "Unverified result exposed")
        status, replay = browser.request(path, "POST", encoded, headers)
        check(status == 201 and json.loads(replay) == draft, "Draft idempotency failed")
        detail = f'/api/v2/research-versions/{draft["id"]}'
        status, restored = browser.request(detail)
        check(status == 200 and json.loads(restored) == draft, "Draft restore failed")
        profile_headers = {"Content-Type": "application/json", "Idempotency-Key": "fixed-profile", "If-Control-Revision": str(draft["revision"])}
        status, raw = browser.request(detail + "/validate", "POST", b'{}', profile_headers)
        check(status == 202, f"Enabled PROFILE was not queued: {status} {raw.decode('utf-8', 'replace')[:400]}")
        queue_status = status
        validate_api(json.loads(raw), "Run")
        run = wait_run(browser, json.loads(raw)["id"])
        check(run["status"] == "SUCCEEDED", "Sealed PROFILE run did not succeed")
        status, raw = browser.request(detail)
        ready = json.loads(raw)
        check(status == 200 and ready["status"] == "READY", "Sealed version was not projected READY")
        check(ready["quality_report_id"] is not None and ready["structure_assessment_artifact_id"] is not None, "READY without sealed quality evidence")
        check(ready["observation_split"]["sealed_test_id"] is not None, "READY without sealed test registration")
        check(len(ready["evidence_bundle_ids"]) == 1, "Evidence bundle was not registered exactly once")
        bundle_id = ready["evidence_bundle_ids"][0]
        status, raw = browser.request(f"/api/v2/evidence-bundles/{bundle_id}")
        bundle: JsonObject = json.loads(raw)
        check(status == 200, "Evidence bundle read failed")
        validate_api(bundle, "EvidenceBundle")
        check(bundle["status"] == "ACTIVE" and bundle["revision"] == 0, "Unexpected evidence bundle state")
        check(bundle["validation_ids"] == [], "Evidence bundle referenced validations that do not exist yet")
        check(sorted(bundle["proof_artifact_ids"]) == sorted([ready["quality_report_id"], ready["structure_assessment_artifact_id"]]), "Evidence bundle references differ from sealed artifacts")
        status, _ = browser.request(f"/api/v2/evidence-bundles/{uuid4()}")
        check(status == 404, "Unknown evidence bundle was exposed")
        status, _ = browser.request(f'/api/v2/artifacts/{ready["quality_report_id"]}')
        check(status == 200, f"Sealed quality artifact was not readable before declaration: {status}")
        impact_path = f'/api/v2/dataset-versions/{version["id"]}/deletion-requests/dry-run'
        status, raw = browser.request(impact_path, "POST")
        check(status == 200, f"Deletion dry-run failed: {status}")
        impact = json.loads(raw)
        validate_api(impact, "DeletionImpact")
        check(impact["propagation_enabled"] is False and len(impact["affected"]) > 1, "Dry-run did not enumerate the lineage while the policy is closed")
        check(DeletionRequest.objects.filter(tenant_id=account.tenant_id).count() == 0 and DeletionTarget.objects.filter(tenant_id=account.tenant_id).count() == 0, "Dry-run wrote deletion state")
        request_path = f'/api/v2/dataset-versions/{version["id"]}/deletion-requests'
        status, raw = browser.request(request_path, "POST", b"", {"Idempotency-Key": "fixed-declaration"})
        check(status == 201, f"Deletion declaration failed: {status} {raw.decode('utf-8', 'replace')[:300]}")
        declared = json.loads(raw)
        validate_api(declared, "DeletionRequestView")
        check(declared["status"] == "BLOCKED" and declared["policy_status"] == "BLOCKED" and declared["blocked_code"] == "FEATURE_DISABLED", "Deletion work did not stay Fail-Closed while the policy is closed")
        check(declared["outstanding"] == len(declared["targets"]) > 1, "Declaration recorded no derived objects to purge")
        status, replay = browser.request(request_path, "POST", b"", {"Idempotency-Key": "fixed-declaration"})
        check(status == 201 and json.loads(replay) == declared, "Declaration idempotency failed")
        status, raw = browser.request(request_path)
        check(status == 200 and json.loads(raw) == declared, "Deletion read-back differs from the declared work")
        check(DeletionRequest.objects.filter(tenant_id=account.tenant_id).count() == 1, "One declaration wrote more than one deletion request")
        request_id, request_status = declared["deletion_request_id"], declared["status"]
        policy_status, target_count = declared["policy_status"], len(declared["targets"])
        status, _ = browser.request(f'/api/v2/artifacts/{ready["quality_report_id"]}')
        check(status == 409, f"Artifact stayed readable after declaration: {status}")
        status, _ = browser.request(f'/api/v2/artifacts/{ready["quality_report_id"]}/content')
        check(status == 409, f"Artifact stayed downloadable after declaration: {status}")
        status, _ = browser.request(f"/api/v2/evidence-bundles/{bundle_id}")
        check(status == 404, f"Evidence bundle stayed readable after declaration: {status}")
        status, raw = browser.request(request_path, "POST", b"", {"Idempotency-Key": "another-declaration"})
        check(status == 409 and json.loads(raw)["code"] == "INVALID_TRANSITION", f"Second declaration of the same source returned {status}")
        self.stdout.write(json.dumps({"scope": "T07_RESEARCH_DRAFT_HTTP", "status": "PASS", "via_frontend": bool(options["frontend"]), "ingest_status": run["status"], "research_version_status": ready["status"], "draft_id": draft["id"], "draft_hash": identity_hash(draft), "policy_hash": draft["evaluation_policy_hash"], "unicode_source_mapping": "PASS", "replay_and_restore": "PASS", "profile_http_status": queue_status, "profile_run_status": run["status"], "sealed_test_registered": ready["observation_split"]["sealed_test_id"] is not None, "evidence_bundle_id": bundle_id, "evidence_bundle_status": bundle["status"], "evidence_bundle_revision": bundle["revision"], "evidence_bundle_proof_count": len(bundle["proof_artifact_ids"]), "unknown_bundle_http_status": 404, "deletion_dry_run_http_status": 200, "deletion_dry_run_target_count": len(impact["affected"]), "deletion_declaration_http_status": 201, "deletion_readback_http_status": 200, "deletion_declaration_idempotent": True, "deletion_request_id": request_id, "deletion_status": request_status, "deletion_policy_status": policy_status, "deletion_target_count": target_count, "deletion_outstanding": declared["outstanding"], "artifact_http_status_after_declaration": 409, "evidence_bundle_http_status_after_declaration": 404, "repeat_declaration": "REJECTED_409", "product_gate_status": "NOT_RUN"}, indent=2))
