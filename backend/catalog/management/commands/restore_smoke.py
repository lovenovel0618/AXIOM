"""M3 備份與還原演練：以受控維護窗建立一致 `BackupSet`，驗引用物件、重播刪除帳本並量測 RPO／RTO。

依 AX-27 的 MVP 一致集與恢復 Runbook，本命令在真實迴環 HTTP 產生的權威資源上：於單一
REPEATABLE READ 唯讀交易內收斂物件清單、帳本高水位與 DB 還原點並落盤為不可變備份集；
由凍結備份集重跑引用物件驗證；注入單一缺件以證明缺件會被偵測且不得宣告可還原；宣告
刪除後重播刪除帳本，確認已刪／隔離資料仍不可查；並以 DB 重建派送狀態與冪等重放稽核。
本命令只蒐集證據：`g7_status` 固定 `BLOCKED`、`nfr_002_status` 固定 `NOT_RUN`，
未執行完整 DB 還原與獨立曝光帳本對帳者一律標 `NOT_RUN`。
"""
import json
import secrets
import time
from argparse import ArgumentParser
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, NoReturn, cast
from uuid import uuid4
from django.conf import settings
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from catalog import backup
from catalog.management.commands.catalog_smoke import BASE, Browser, FRONTEND_BASE
from catalog.management.commands.m3_e2e_smoke import prepare_chain, read_json
from catalog.management.commands.research_draft_smoke import check
from catalog.models import Account, Tenant
from catalog.storage import LocalVersionStore
from runtime.contracts import JsonObject

VERDICTS = {
    "AC-27-01": ("PARTIAL", "DB 引用物件缺失已實測可偵測且不宣告可還原；線上停寫閘門尚未實作，故「保持寫入關閉」只有離線證據"),
    "AC-27-02": ("PASS", "較早快照加上重播刪除帳本後，已宣告的來源與衍生產物仍不可查"),
    "AC-27-03": ("PARTIAL", "派送狀態可只由 DB 重建、刪除宣告冪等重放不產生第二次副作用；未實際毀損 Redis"),
    "AC-27-04": ("PARTIAL", "凍結 BackupSet 重跑的來源 hash 不變；正式 RPO／RTO 未取得（D-06 未凍結）"),
    "AC-27-05": ("NOT_RUN", "需獨立曝光帳本對帳與最終標籤消耗；本切片不觸及"),
    "AC-27-06": ("NOT_RUN", "需 journal 缺段／水位未知／金鑰缺失的隔離判定；本切片不觸及"),
    "AC-27-07": ("NOT_RUN", "需曝光已記但 DB 提交失敗的保守 tombstone；本切片不觸及"),
}


def acceptance_cases() -> list[JsonObject]:
    """逐案例回報本切片實際觀察到的狀態；未涵蓋者明列原因，不宣告 Gate 通過。"""
    return [{"id": identity, "status": status, "scope": scope} for identity, (status, scope) in VERDICTS.items()]


@dataclass(frozen=True)
class ReplayResult:
    """刪除帳本重播結果：宣告內容、帳本高水位變化與重播後仍不可查的狀態碼。"""
    declared: JsonObject
    tombstones_before: int
    tombstones_after: int
    target_count: int
    artifact_after: int
    bundle_after: int
    idempotent: bool


def declared_deletion(browser: Browser, version_id: str) -> ReplayResult:
    """宣告刪除並重播刪除帳本；同一冪等鍵重送必須回相同文件且不產生第二次副作用。"""
    ledger_before = backup.deletion_ledger()
    path = f"/api/v2/dataset-versions/{version_id}/deletion-requests"
    headers = {"Content-Type": "application/json", "Idempotency-Key": "m3-restore-declaration"}
    status, raw = browser.request(path, "POST", b"", headers)
    check(status == 201, f"刪除宣告失敗：{status} {raw.decode('utf-8', 'replace')[:300]}")
    declared: JsonObject = json.loads(raw)
    status, replay = browser.request(path, "POST", b"", headers)
    check(status == 201 and json.loads(replay) == declared, "刪除宣告的冪等重播結果不同")
    status, readback = browser.request(path)
    check(status == 200 and json.loads(readback) == declared, "刪除工作讀回與宣告內容不同")
    ledger_after = backup.deletion_ledger()
    targets = _list_field(declared["targets"], "刪除宣告未列出衍生受影響物件")
    check(len(targets) > 1, "刪除宣告未列出衍生受影響物件")
    added = ledger_after["tombstones"] - ledger_before["tombstones"]
    if added != len(targets):
        _mismatch(added, len(targets))
    return ReplayResult(declared=declared, tombstones_before=ledger_before["tombstones"],
                        tombstones_after=ledger_after["tombstones"], target_count=len(targets),
                        artifact_after=0, bundle_after=0, idempotent=True)


def _list_field(value: object, message: str) -> list[object]:
    """把宣告文件中的清單欄位收斂成具體型別；非清單即中止，不讓未知型別流進後續判斷。"""
    check(isinstance(value, list), message)
    return cast("list[object]", value)


def _mismatch(added: int, targets: int) -> NoReturn:
    """tombstone 增量與受影響物件數不符即中止，避免以部分重播掩蓋帳本落差。"""
    raise CommandError(f"刪除帳本重播增量不符：新增 {added} 筆、受影響物件 {targets} 項")


class Command(BaseCommand):
    help = "Drill AX-27 backup and restore over real resources: consistent BackupSet, object verification, fault injection, deletion ledger replay and DB-only dispatch reconstruction"

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--frontend", action="store_true")
        parser.add_argument("--rows", type=int, default=100)

    def handle(self, *args: Any, **options: Any) -> None:
        rows = int(options["rows"])
        if rows < 10:
            raise CommandError("rows 至少 10 列以容納 60／20／20 切分")
        password = secrets.token_urlsafe(24)
        user = User.objects.create_user(username="restore-" + uuid4().hex, password=password)
        account = Account.objects.create(user=user, tenant=Tenant.objects.create(name="restore-synthetic"))
        browser = Browser(FRONTEND_BASE if options["frontend"] else BASE)
        browser.login(user.get_username(), password)
        prepared = prepare_chain(browser, rows)
        store = LocalVersionStore(settings.OBJECT_ROOT)
        # 1. 受控維護窗：單一一致性快照收斂物件清單、帳本高水位與還原點，再落盤為不可變備份集。
        window_started = time.monotonic()
        identity = str(uuid4())
        document, entries = backup.capture(datetime.now(timezone.utc), identity)
        capture_seconds = round(time.monotonic() - window_started, 3)
        directory = backup.write(document, entries)
        build_seconds = round(time.monotonic() - window_started, 3)
        check(backup.root() == settings.BACKUP_ROOT, "備份保管位置與設定不符")
        # 2. 還原驗證：由凍結備份集重讀並先驗檔案 checksum，再逐一核對引用物件大小與 SHA-256。
        restored_document, restored_entries = backup.read(directory)
        check(restored_document == document and restored_entries == entries, "讀回的備份集與落盤內容不同")
        verify_started = time.monotonic()
        verification = backup.verify(restored_entries, store)
        verify_seconds = round(time.monotonic() - verify_started, 3)
        check(verification.ok(), f"備份集內的引用物件不可用：{verification.document()}")
        # 3. AC-27-01：注入單一缺件，缺件必須被偵測且不得宣告可還原；驗畢立即放回原位。
        drill_entries = tuple(entry for entry in entries if entry.tenant == account.tenant_id.hex)
        check(len(drill_entries) >= 1, "本輪租戶沒有可注入缺件的物件")
        victim = drill_entries[0]
        hidden = backup.detach(victim, store)
        try:
            degraded = backup.verify(entries, store)
        finally:
            backup.reattach(hidden, victim, store)
        check(not degraded.ok() and victim.version in degraded.unreadable, "缺件未被偵測")
        check(backup.verify(entries, store).ok(), "缺件放回後引用物件仍不可用")
        # 4. AC-27-02：備份集早於刪除宣告；重播刪除帳本後來源與衍生產物必須仍不可查。
        versions = read_json(browser, f'/api/v2/datasets/{prepared.dataset_id}/versions')
        version = next(row for row in versions["items"] if row["id"] == prepared.dataset_version_id)
        project_artifact = str(version["structure_preview_artifact_id"])
        status, _ = browser.request(f"/api/v2/artifacts/{project_artifact}")
        check(status == 200, f"宣告前的 PROJECT 產物不可讀：{status}")
        check(document["deletion_ledger_high_water"]["digest"] == backup.deletion_ledger()["digest"],
              "備份集並非早於本次刪除宣告")
        replay = declared_deletion(browser, prepared.dataset_version_id)
        status, _ = browser.request(f"/api/v2/artifacts/{project_artifact}")
        check(status == 409, f"重播刪除帳本後 PROJECT 產物仍可讀：{status}")
        status, _ = browser.request(f"/api/v2/evidence-bundles/{prepared.evidence_bundle_id}")
        check(status == 404, f"重播刪除帳本後證據包仍可讀：{status}")
        # 5. AC-27-03：Redis 非權威，派送狀態必須能只由 DB 重建；且重播不得產生第二次副作用。
        reconstruction = backup.dispatch_reconstruction()
        check(not reconstruction.inconsistent, f"事件鏈與 Run 游標不一致：{reconstruction.document()}")
        check(replay.tombstones_after - replay.tombstones_before == replay.target_count, "刪除帳本重播增量不符")
        # 6. AC-27-04：凍結備份集重跑後來源 hash 不變；RPO／RTO 未取得則據實標示。
        frozen, frozen_entries = backup.read(directory)
        check(frozen_entries == restored_entries and backup.verify(frozen_entries, store).ok(), "凍結備份集重跑後來源變形")
        counts = cast("dict[str, Any]", frozen["authoritative_counts"])
        self.stdout.write(json.dumps({
            "scope": "M3_RESTORE_DRILL", "status": "PASS", "via_frontend": bool(options["frontend"]),
            "spec": "docs/企劃案/09-非功能/27-可觀測性備份與故障復原.md (AX-27, AC-27-01..07)",
            "backup_set": {
                "backup_set_id": str(frozen["backup_set_id"]), "backup_set_version": str(frozen["backup_set_version"]),
                "directory": str(directory), "storage_location": str(frozen["storage_location"]),
                "dsl_version": str(frozen["dsl_version"]), "app_version": str(frozen["app_version"]),
                "migration_count": int(cast("dict[str, Any]", frozen["schema_versions"])["migration_count"]),
                "wal_lsn": str(cast("dict[str, Any]", frozen["db_restore_point"])["wal_lsn"]),
                "secret_key_version": str(frozen["secret_key_version"]),
                "object_count": int(cast("dict[str, Any]", frozen["object_manifest"])["count"]),
                "object_digest": str(cast("dict[str, Any]", frozen["object_manifest"])["digest"]),
                "outbox_high_water": frozen["outbox_high_water"],
                "deletion_ledger_high_water": frozen["deletion_ledger_high_water"],
                "exposure_ledger_high_water": frozen["exposure_ledger_high_water"],
                "authoritative_counts": counts,
            },
            "object_verification": verification.document(),
            "fault_injection": {"detached_version": victim.version, "detected": not degraded.ok(),
                                "degraded": degraded.document(), "recovered_ok": backup.verify(entries, store).ok(),
                                "writes_reopened": False,
                                "writes_reopened_reason": "線上停寫閘門未實作，演練只證明缺件被偵測且未宣告可還原"},
            "deletion_ledger_replay": {
                "deletion_request_id": str(replay.declared["deletion_request_id"]),
                "status": str(replay.declared["status"]), "policy_status": str(replay.declared["policy_status"]),
                "blocked_code": replay.declared["blocked_code"], "target_count": replay.target_count,
                "tombstones_before": replay.tombstones_before, "tombstones_after": replay.tombstones_after,
                "idempotent_replay": replay.idempotent, "artifact_http_after_replay": 409,
                "evidence_bundle_http_after_replay": 404,
            },
            "dispatch_reconstruction": reconstruction.document(),
            "measurements": {
                "maintenance_capture_seconds": capture_seconds, "consistent_set_build_seconds": build_seconds,
                "restore_verification_seconds": verify_seconds,
                "objects_verified": verification.checked,
                "measured_rpo_seconds": None,
                "measured_rpo_reason": "本機演練未啟用線上停寫閘門，維護窗未實際禁止寫入，依 Fail-Closed 不宣稱 RPO",
                "measured_rto_seconds": None,
                "measured_rto_reason": "環境沒有 pg_dump／pg_restore 且不得對執行中環境直接還原，未執行完整 DB 還原",
            },
            "retention": {"completed_sets_kept": None, "reason": "保留與敏感資料期限屬 D-06，未凍結前不設定承諾值"},
            "identity_model": {"drill_tenant": str(account.tenant_id), "source_research_version_id": prepared.research_version_id},
            "acceptance_cases": acceptance_cases(),
            "g7_status": "BLOCKED", "nfr_002_status": "NOT_RUN",
            "g7_reason": "D-05／D-06 未關閉保留政策與 RPO／RTO，G7 維持 BLOCKED，本命令只出量測與演練證據",
            "account_tenant": str(account.tenant_id), "product_gate_status": "NOT_RUN",
        }, indent=2, ensure_ascii=False))
