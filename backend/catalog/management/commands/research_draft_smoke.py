"""Loopback HTTP upload-to-draft smoke on disposable synthetic observations."""
import json
import secrets
from typing import Any
from uuid import UUID, uuid4
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from catalog.management.commands.business_ingest_smoke import upload
from catalog.management.commands.catalog_smoke import Browser
from catalog.models import Account, Tenant
from catalog.services import set_grant
from catalog.validation import validate_api
from runtime.contracts import JsonObject, identity_hash


def configuration(version: str) -> JsonObject:
    return {
        "dataset_version_id": version,
        "semantic_profile": {"inputs": [{"name": "x", "source_column": "時間（秒）", "unit": [0,0,1,0,0,0,0], "conversion": {"source_unit": "s", "scale": "1", "offset": "0"}}],
            "target": {"name": "y", "source_column": "位移（公分）", "unit": [1,0,0,0,0,0,0], "conversion": {"source_unit": "cm", "scale": "0.01", "offset": "0"}},
            "units_confirmed": True, "time_ordered": False, "measurement_resolution": "0.001", "resolution_reason": "Synthetic independent positions; names alone do not establish time dependence", "group_column": None},
        "budget": {"cpu_seconds": 30, "gpu_seconds": 0, "wall_seconds": 60, "tokens": 0, "candidate_limit": 10, "memory_bytes": 1073741824}, "purpose": "DESCRIPTION",
        "observation_split": {"kind": "EXPLICIT", "dataset_version_id": version, "fit": list(range(6)), "development": [6,7], "final_test": [8,9], "gap_rows": 0, "lookback_rows": 0, "horizon_rows": 0, "seed": 7, "time_column": None, "group_column": None, "group_assignment_digest": None, "splitter_version": "synthetic-explicit-v1", "policy_version": "2.0", "sealed_final_test": True},
        "domain": [{"name": "x", "lower": {"numerator": "0", "denominator": "1"}, "upper": {"numerator": "10", "denominator": "1"}, "lower_closed": True, "upper_closed": True}],
        "evaluation_policy": {"policy_version": "1.0", "metric_version": "2.0", "error_model": "UNSPECIFIED", "absolute_error_bound": None, "comparison_method": "NONE", "bootstrap_replicates": 2000, "bootstrap_seed": 7, "block_method": None, "block_length": None, "practical_scale_override": None, "practical_margin_ratio": "0.01", "baseline": "FIT_MEAN", "practical_scale_reason": None},
    }


def check(condition: bool, message: str) -> None:
    if not condition:
        raise CommandError(message)


class Command(BaseCommand):
    help = "Exercise real INGEST, Unicode semantic confirmation, DRAFT persistence and ACL revocation"

    def handle(self, *args: Any, **options: Any) -> None:
        password = secrets.token_urlsafe(24)
        user = User.objects.create_user(username="draft-" + uuid4().hex, password=password)
        actor = Account.objects.create(user=user, tenant=Tenant.objects.create(name="draft-synthetic"), role="ADMIN")
        browser = Browser()
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
        status, _ = browser.request(detail + "/validate", "POST", b'{}', {"Content-Type": "application/json"})
        check(status == 503, "Unimplemented PROFILE accepted")
        set_grant(actor.id, actor.id, UUID(dataset["id"]), None)
        status, _ = browser.request(detail)
        check(status == 404, "Revoked version exposed")
        status, _ = browser.request(path, "POST", encoded, headers)
        check(status == 404, "Cached draft bypassed revocation")
        self.stdout.write(json.dumps({"scope": "T07_RESEARCH_DRAFT_HTTP", "status": "PASS", "ingest_status": run["status"], "research_version_status": draft["status"], "draft_id": draft["id"], "draft_hash": identity_hash(draft), "policy_hash": draft["evaluation_policy_hash"], "unicode_source_mapping": "PASS", "replay_and_restore": "PASS", "revoked_http_status": 404, "profile_http_status": 503, "sealed_test_registered": False, "product_gate_status": "NOT_RUN"}, indent=2))
