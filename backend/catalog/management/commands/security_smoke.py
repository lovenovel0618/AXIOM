"""M3 資安驗收：真實 HTTP 的跨租戶越權、SEALED_DETAIL 與 cursor／SSE 隔離矩陣。

以同一租戶的三個獨立身分（自有 owner、同租戶非 owner、外租戶）對 `run_chain` 產生的 M3 權威
資源逐項重驗租戶分區與 access_class：任何一項洩漏即中止並回報。外送政策（Gateway）、向量／
模型 lineage 隔離與服務身分憑證不屬本切片，一律標 NOT_RUN。此命令只蒐集證據，不宣告 Gate 通過。
"""
import json
import secrets
from argparse import ArgumentParser
from typing import Any
from uuid import uuid4
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db import transaction
from catalog.management.commands.catalog_smoke import BASE, Browser, FRONTEND_BASE
from catalog.management.commands.m3_e2e_smoke import read_json, run_chain
from catalog.management.commands.research_draft_smoke import check
from catalog.models import Account, Artifact, Tenant
from catalog.validation import validate_api

VERDICTS = {
    "AC-26-01": ("PASS", "跨租戶 API／SSE／下載／cursor 一律 404 或拒絕，且不洩漏存在性"),
    "AC-26-02": ("NOT_RUN", "外送政策在 Gateway 實際發送前執行，屬 M4；本切片不觸及"),
    "AC-26-03": ("PASS", "同租戶一般身分與作者自身讀 SEALED_DETAIL 產物一律 404"),
    "AC-26-04": ("NOT_RUN", "向量／模型 lineage 隔離與 QUARANTINED 屬 M4；本切片只涵蓋 tombstone 讀取"),
    "AC-26-05": ("NOT_RUN", "需 Solver 服務身分與任務 scope；本切片無 app 層服務憑證"),
    "AC-26-06": ("NOT_RUN", "需 Evaluator 服務身分與 submission 綁定；本切片無 app 層服務憑證"),
    "AC-26-07": ("PARTIAL", "開發投影可讀且 Run 投影不含受限引用；null 遮罩判讀屬前端"),
}


def acceptance_cases() -> list[dict[str, str]]:
    """逐案例回報本切片實際觀察到的狀態，未涵蓋者明列原因，不宣告 Gate 通過。"""
    return [{"id": identity, "status": status, "scope": scope} for identity, (status, scope) in VERDICTS.items()]


class Command(BaseCommand):
    help = "Exercise M3 cross-tenant, SEALED_DETAIL and cursor/SSE isolation over real HTTP using disposable synthetic identities"

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--frontend", action="store_true")

    def handle(self, *args: Any, **options: Any) -> None:
        base = FRONTEND_BASE if options["frontend"] else BASE
        password = secrets.token_urlsafe(24)
        with transaction.atomic():
            shared = Tenant.objects.create(name="security-shared-" + uuid4().hex)
            owner_account = Account.objects.create(user=User.objects.create_user(username="sec-owner-" + uuid4().hex, password=password), tenant=shared)
            peer_account = Account.objects.create(user=User.objects.create_user(username="sec-peer-" + uuid4().hex, password=password), tenant=shared)
            foreign_account = Account.objects.create(user=User.objects.create_user(username="sec-foreign-" + uuid4().hex, password=password), tenant=Tenant.objects.create(name="security-foreign-" + uuid4().hex))
        owner, peer, foreign = Browser(base), Browser(base), Browser(base)
        owner.login(owner_account.user.get_username(), password)
        peer.login(peer_account.user.get_username(), password)
        foreign.login(foreign_account.user.get_username(), password)
        # 1. 以 owner 身分跑完整 M3 鏈路，取得每一類受保護資源的真實識別碼。
        result = run_chain(owner)
        versions = read_json(owner, f"/api/v2/datasets/{result.dataset_id}/versions")
        version = next(row for row in versions["items"] if row["id"] == result.dataset_version_id)
        sealed_artifact, project_artifact = str(version["artifact_id"]), str(version["structure_preview_artifact_id"])
        sealed_ids = {str(value) for value in Artifact.objects.filter(tenant_id=owner_account.tenant_id, document__access_class="SEALED_DETAIL").values_list("id", flat=True)}
        check(sealed_artifact in sealed_ids, "原始資料產物未被標為 SEALED_DETAIL")
        probes: list[dict[str, Any]] = []

        def probe(browser: Browser, label: str, path: str, expected: int, method: str = "GET", data: bytes | None = None) -> bytes:
            """送出請求並記錄狀態；不符預期即中止，避免以部分通過掩蓋洩漏。"""
            headers = {"Content-Type": "application/json", "Idempotency-Key": uuid4().hex} if data is not None else None
            status, raw = browser.request(path, method, data, headers)
            probes.append({"label": label, "method": method, "path": path, "expected": expected, "status": status})
            check(status == expected, f"{label}: {method} {path} -> {status}, expected {expected}")
            return raw

        # 2. AC-26-01：外租戶對 owner 的每一類資源讀取與下載都必須 404。
        cross_tenant = [
            ("dataset_versions", f"/api/v2/datasets/{result.dataset_id}/versions"),
            ("dataset_runs", f"/api/v2/datasets/{result.dataset_id}/runs"),
            ("run_detail", f"/api/v2/runs/{result.search_run_id}"),
            ("run_candidates", f"/api/v2/runs/{result.search_run_id}/candidates"),
            ("run_events", f"/api/v2/runs/{result.search_run_id}/events"),
            ("research_detail", f"/api/v2/researches/{result.research_id}"),
            ("research_version", f"/api/v2/research-versions/{result.research_version_id}"),
            ("research_events", f"/api/v2/research-versions/{result.research_version_id}/events"),
            ("evidence_bundle", f"/api/v2/evidence-bundles/{result.evidence_bundle_id}"),
            ("artifact_metadata", f"/api/v2/artifacts/{project_artifact}"),
            ("artifact_content", f"/api/v2/artifacts/{project_artifact}/content"),
            ("fit_run", f"/api/v2/fit-runs/{result.fit_run_id}"),
            ("equation_version", f"/api/v2/equation-versions/{result.equation_version_id}"),
            ("validation_run", f"/api/v2/validation-runs/{result.validation_run_ids[0]}"),
        ]
        for label, path in cross_tenant:
            probe(foreign, "cross_tenant_" + label, path, 404)
        probe(foreign, "cross_tenant_upload_write", f"/api/v2/datasets/{result.dataset_id}/uploads", 404, "POST", json.dumps({"filename": "x.csv", "format": "CSV", "size_bytes": 1, "sha256": "0" * 64}).encode())
        # 3. AC-26-01：簽章 cursor 綁 actor，跨身分重播一律 INVALID_CURSOR，不因曾簽發而永久可讀。
        owner.post("/api/v2/datasets", {"name": "security-cursor"})
        issued = read_json(owner, "/api/v2/datasets?limit=1")["next_cursor"]
        check(issued is not None, "多筆頁面未簽發 cursor，無法驗證範圍綁定")
        for label, browser in (("peer", peer), ("foreign", foreign)):
            raw = probe(browser, f"cursor_replay_{label}", f"/api/v2/datasets?limit=1&cursor={issued}", 400)
            check(json.loads(raw)["code"] == "INVALID_CURSOR", f"{label} 重播 cursor 未以 INVALID_CURSOR 拒絕")
        # 4. AC-26-03：SEALED_DETAIL 對作者自身、同租戶非 owner 與外租戶一律 404；PROJECT 對照仍可讀。
        probe(owner, "sealed_metadata_owner", f"/api/v2/artifacts/{sealed_artifact}", 404)
        probe(owner, "sealed_content_owner", f"/api/v2/artifacts/{sealed_artifact}/content", 404)
        probe(peer, "sealed_metadata_peer", f"/api/v2/artifacts/{sealed_artifact}", 404)
        probe(peer, "sealed_content_peer", f"/api/v2/artifacts/{sealed_artifact}/content", 404)
        probe(foreign, "sealed_metadata_foreign", f"/api/v2/artifacts/{sealed_artifact}", 404)
        probe(owner, "project_metadata_owner", f"/api/v2/artifacts/{project_artifact}", 200)
        # 5. AC-26-01/03：SSE 每次請求重驗 owner 與租戶分區；owner 自身可讀，其餘 404。
        probe(owner, "run_events_owner", f"/api/v2/runs/{result.search_run_id}/events", 200)
        probe(peer, "run_events_peer", f"/api/v2/runs/{result.search_run_id}/events", 404)
        probe(owner, "research_events_owner", f"/api/v2/research-versions/{result.research_version_id}/events", 200)
        probe(peer, "research_events_peer", f"/api/v2/research-versions/{result.research_version_id}/events", 404)
        # 6. AC-26-07：owner 可讀自身開發投影，且 Run 投影不得出現任何受限引用。
        for validation_id in result.validation_run_ids:
            probe(owner, "development_projection", f"/api/v2/validation-runs/{validation_id}", 200)
        search_detail = read_json(owner, f"/api/v2/runs/{result.search_run_id}")
        validate_api(search_detail, "Run")
        serialized = json.dumps(search_detail, sort_keys=True)
        leaked = sorted(value for value in sealed_ids if value in serialized)
        check("input_artifact_id" not in search_detail and not leaked, f"Run 投影洩漏受限引用：{leaked}")
        self.stdout.write(json.dumps({"scope": "M3_SECURITY", "status": "PASS", "via_frontend": bool(options["frontend"]),
            "identity_model": {"shared_tenant": str(owner_account.tenant_id), "foreign_tenant": str(foreign_account.tenant_id)},
            "cross_tenant_denials": len([row for row in probes if str(row["label"]).startswith("cross_tenant_")]),
            "request_probes": probes,
            "sealed_detail_artifact_id": sealed_artifact, "sealed_detail_tenant_classified": sealed_artifact in sealed_ids,
            "sealed_detail_count": len(sealed_ids), "project_artifact_id": project_artifact,
            "cursor_replay_rejected": True, "run_projection_excludes_sealed_artifacts": True,
            "development_projection_readable": True,
            "dataset_id": result.dataset_id, "research_version_id": result.research_version_id,
            "search_run_id": result.search_run_id, "fit_run_id": result.fit_run_id,
            "evidence_bundle_id": result.evidence_bundle_id,
            "acceptance_cases": acceptance_cases(), "product_gate_status": "NOT_RUN"}, indent=2))
