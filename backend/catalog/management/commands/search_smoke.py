"""真 HTTP／CSRF、broker 與獨立 SEARCH worker 的三格式合成資料驗證。"""
import json
import secrets
from uuid import UUID, uuid4
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from catalog.management.commands.catalog_smoke import Browser, FRONTEND_BASE
from catalog.management.commands.profile_smoke import draft, payload, verified_profile
from catalog.management.commands.business_ingest_smoke import wait_run
from catalog.management.commands.research_draft_smoke import check
from catalog.models import Account, Candidate, ResearchBudget, Reservation, RootBudget, Tenant
from runtime.models import RuntimeRun, RuntimeCheckpoint


class Command(BaseCommand):
    help = "Verify SEARCH over HTTP, dedicated queue, checkpoints and paired ledgers"

    def handle(self, *args: object, **options: object) -> None:
        password = secrets.token_urlsafe(24)
        user = User.objects.create_user(username="search-" + uuid4().hex, password=password)
        Account.objects.create(user=user, tenant=Tenant.objects.create(name="search-synthetic"))
        results: list[dict[str, object]] = []
        for base in (None, FRONTEND_BASE):
            browser = Browser() if base is None else Browser(base)
            browser.login(user.get_username(), password)
            status, dataset = browser.post('/api/v2/datasets', {"name": "search-three-formats"})
            check(status == 201, "Dataset rejected")
            for index, format_name in enumerate(("CSV", "JSON", "PARQUET")):
                version = draft(browser, dataset["id"], payload(index, format_name), format_name)
                verified_profile(browser, version, 0, "profile-before-search-" + format_name, "PASS")
                before = ResearchBudget.objects.get(research_version_id=UUID(version["id"])).document["usage"].copy()
                path = f'/api/v2/research-versions/{version["id"]}/runs'
                body = json.dumps({"type": "SEARCH", "seed": 42}).encode()
                headers = {"Content-Type": "application/json", "Idempotency-Key": "search-" + format_name, "If-Control-Revision": "2"}
                status, raw = browser.request(path, "POST", body, headers)
                queued = json.loads(raw)
                check(status == 202, "SEARCH enqueue rejected")
                run = wait_run(browser, queued["id"])
                check(run["status"] == "SUCCEEDED" and run["phase"] == "SEARCHING", "SEARCH worker failed")
                identity = UUID(run["id"])
                account = ResearchBudget.objects.get(research_version_id=UUID(version["id"]))
                root = RootBudget.objects.get(run_id=identity)
                check(root.document["usage"] == run["budget_usage"] and account.document["usage"]["cpu_seconds"] == before["cpu_seconds"] + run["budget_usage"]["cpu_seconds"], "Ledger usage differs")
                check(root.document["status"] == "CLOSED" and account.document["status"] == "CLOSING", "Search/final settlement boundary differs")
                check(Reservation.objects.get(root=root).state == "RELEASED", "Reservation retained")
                check(RuntimeCheckpoint.objects.filter(run_id=identity).count() == 3, "Strategy checkpoints missing")
                check(RuntimeRun.objects.filter(document__type="SEARCH", document__research_version_id=version["id"]).count() == 1, "Duplicate SEARCH root")
                count = Candidate.objects.filter(search_run_id=identity).count()
                check(count == run["budget_usage"]["candidates_accepted"] and count > 0, "Candidate count differs")
                status, repeated = browser.request(path, "POST", body, headers)
                check(status == 202 and json.loads(repeated) == queued, "Idempotency replay differs")
                results.append({"format": format_name, "via_frontend": base is not None, "run_id": run["id"],
                    "research_version_id": version["id"], "candidate_count": count, "research_budget_status": account.document["status"], "root_budget_status": root.document["status"], "usage": run["budget_usage"]})
        self.stdout.write(json.dumps({"scope": "T07_ACTUAL_SEARCH", "status": "PASS", "results": results, "product_gate_status": "NOT_RUN"}, indent=2))
