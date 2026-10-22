"""Real HTTP, relay and dedicated worker probe; disposable synthetic data only."""
from io import BytesIO
import hashlib
import json
import secrets
import time
from typing import Any
from uuid import uuid4
import polars as pl
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from catalog.management.commands.catalog_smoke import Browser
from catalog.models import Account, Tenant
from catalog.validation import validate_api


def wait_run(browser: Browser, identity: str) -> dict[str, Any]:
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        status, raw = browser.request("/api/v2/runs/" + identity)
        record: dict[str, Any] = json.loads(raw)
        if status != 200:
            raise CommandError("Run read unavailable")
        validate_api(record, "Run")
        if record["status"] in {"SUCCEEDED", "FAILED", "CANCELLED"}:
            return record
        time.sleep(0.2)
    raise CommandError("Actual INGEST worker did not finish")


def upload(browser: Browser, dataset: str, content: bytes, format_name: str) -> tuple[str, dict[str, Any]]:
    checksum = hashlib.sha256(content).hexdigest()
    status, session = browser.post(f"/api/v2/datasets/{dataset}/uploads", {"filename": "synthetic", "format": format_name, "size_bytes": len(content), "sha256": checksum})
    if status != 201:
        raise CommandError("Upload unavailable")
    status, _ = browser.request("/storage/uploads/" + session["id"], "PUT", content, session["required_headers"])
    if status != 204:
        raise CommandError("Bytes rejected")
    path = "/api/v2/uploads/" + session["id"] + "/complete"
    status, record = browser.post(path, {"checksum": checksum})
    if status != 202:
        raise CommandError("Business INGEST not enabled or not queued")
    status, replay = browser.post(path, {"checksum": checksum})
    if status != 202 or replay["id"] != record["id"]:
        raise CommandError("Complete domain idempotency failed")
    return checksum, wait_run(browser, record["id"])


def verified_version(browser: Browser, dataset: dict[str, Any], checksum: str, run: dict[str, Any], format_name: str) -> dict[str, Any]:
    status, raw = browser.request(f"/api/v2/datasets/{dataset['id']}/versions")
    page = json.loads(raw)
    validate_api(page, "VersionPage")
    version = next(row for row in page["items"] if row["sha256"] == checksum)
    if status != 200 or version["row_count"] != 2:
        raise CommandError("Version not committed")
    status, raw = browser.request(f"/api/v2/artifacts/{version['structure_preview_artifact_id']}/content")
    report = json.loads(raw)
    if status != 200 or report["analysis_scope"] != "METADATA_ONLY" or report["source_metadata"]["row_count"] != 2:
        raise CommandError("Safe artifact unavailable")
    status, _ = browser.request(f"/api/v2/artifacts/{version['artifact_id']}/content")
    if status != 404:
        raise CommandError("Raw bytes unexpectedly exposed")
    return {"format": format_name, "run_id": run["id"], "status": run["status"], "version_id": version["id"], "preview_id": version["structure_preview_artifact_id"], "sha256": checksum, "budget_usage": run["budget_usage"]}


class Command(BaseCommand):
    help = "Verify opted-in business INGEST with real relay, queue, worker and artifact reads"

    def handle(self, *args: Any, **options: Any) -> None:
        password = secrets.token_urlsafe(24)
        user = User.objects.create_user(username="ingest-" + uuid4().hex, password=password)
        Account.objects.create(user=user, tenant=Tenant.objects.create(name="ingest-" + uuid4().hex))
        browser = Browser()
        browser.login(user.get_username(), password)
        status, dataset = browser.post("/api/v2/datasets", {"name": "synthetic-business-ingest"})
        if status != 201:
            raise CommandError("Dataset unavailable")
        buffer = BytesIO()
        pl.DataFrame({"x": [1, 2], "y": [3, 5]}).write_parquet(buffer, compression="zstd")
        fixtures = [("CSV", b'x,y\n1,3\n2,5\n'), ("JSON", b'[{"x":1,"y":3},{"x":2,"y":5}]'), ("PARQUET", buffer.getvalue())]
        results: list[dict[str, Any]] = []
        for format_name, content in fixtures:
            checksum, run = upload(browser, dataset["id"], content, format_name)
            if run["status"] != "SUCCEEDED":
                raise CommandError("Real INGEST failed")
            results.append(verified_version(browser, dataset, checksum, run, format_name))
        _checksum, duplicate = upload(browser, dataset["id"], fixtures[0][1], "CSV")
        if duplicate["status"] != "SUCCEEDED":
            raise CommandError("Dedup run failed")
        _checksum, invalid = upload(browser, dataset["id"], b'x,x\nprivate-marker,2\n', "CSV")
        if invalid["status"] != "FAILED" or not invalid["diagnostic_artifact_ids"]:
            raise CommandError("Invalid file was accepted")
        status, raw = browser.request("/api/v2/artifacts/" + invalid["diagnostic_artifact_ids"][0] + "/content")
        if status != 200 or json.loads(raw)["code"] != "INVALID_SCHEMA" or b"private-marker" in raw:
            raise CommandError("Unsafe diagnostic")
        status, raw = browser.request(f"/api/v2/datasets/{dataset['id']}/versions")
        if status != 200 or len(json.loads(raw)["items"]) != 3:
            raise CommandError("Duplicate or failed version committed")
        self.stdout.write(json.dumps({"scope": "T07_ACTUAL_LOCAL_INGEST", "status": "PASS", "results": results,
            "dedup_versions": 3, "invalid_status": invalid["status"], "raw_http_status": 404,
            "research_version_status": "NOT_EXERCISED_BY_THIS_SMOKE", "product_gate_status": "NOT_RUN"}, indent=2))
