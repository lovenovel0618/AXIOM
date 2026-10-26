# T07｜刪除傳播與 tombstone 驗證紀錄

日期：2026-10-22；owner／SELF_REVIEW：project-owner；承接 83a5f94。切片設計見[技術設計](<T07-刪除傳播與tombstone設計.md>)。本批交付來源失效宣告與權威有效性回查；T07 仍 IN_PROGRESS。

## 交付範圍

新增 Tombstone／DeletionRequest／DeletionTarget 三張表（migration 0015）與原生防線（migration 0016），以及服務層 `catalog/deletion.py`；不新增對外端點，也不實作 outbox。AX-43 明訂 MVP 不提供資料硬刪除 API，且 D-05 未定保留與刪除政策前只允許受控的隔離／tombstone，因此失效宣告由服務層以研究來源（DatasetVersion）為根發起，不由客戶端指定刪除範圍。

`GET /api/v2/artifacts/{id}`、`GET /api/v2/artifacts/{id}/content` 與 `GET /api/v2/evidence-bundles/{id}` 沿用既有授權路徑，在授權時一併回查 tombstone；已失效的物件不再因 UUID、舊列表或快取而可讀。目前沒有推薦端點，故本批涵蓋範圍是讀取與下載，未宣稱推薦已實作。

宣告於單一交易內寫入 tombstone、刪除工作與逐項受影響物件，並依 lineage 列舉：DatasetVersion→其 raw／preview Artifact→引用該版本的 ResearchVersion→這些版本的 EvidenceBundle→掛在這些版本的其餘 Artifact。AX-26 所列記憶 embedding／快取、報告、訓練快照與模型版本目前不存在，不為它們偽造受影響物件列。tombstone 與政策是否放行無關，宣告即生效；刪除工作則在 `AXIOM_DELETION_PROPAGATION_ENABLED` 為 0 時只停在 BLOCKED 並帶 `FEATURE_DISABLED`。

## 檢查與實測

| 檢查 | 結果 |
|---|---|
| 完整後端 | PostgreSQL／Linux arm64 容器 284／284，含刪除傳播 10 項斷言，無 skip |
| 前端 | strict typecheck 0 error；vitest 9 檔 77／77；build 63 modules（js 144.31 kB／css 9.87 kB） |
| 工程工具 | `typing_policy` PASS（新增 test_deletion.py 額度，deletion.py 全具體型別）；`development_baseline` PASS；`check_docs.py` exit 0 |
| 嚴格型別 | 根與 backend Pyright 1.1.414：0 errors／0 warnings |
| 真 HTTP（直連） | 上傳→INGEST→草案→PROFILE 202→Run SUCCEEDED→READY→證據包 200→宣告：artifact 200→409、證據包 200→404 |
| 真 HTTP（前端同源） | 同上經 15173 同源代理，結果一致 |
| Fail-Closed 實測 | 宣告後 `deletion_status=BLOCKED`、`policy_status=BLOCKED`（`FEATURE_DISABLED`）、受影響物件 8 項；同一來源二次宣告回 409 `INVALID_TRANSITION` |
| 資料庫守門 | 跨租戶根目標 FK 拒絕、tombstone 不可改／不可刪、非法狀態轉移拒絕、policy 未放行不得進 PROPAGATING／COMPLETED、COMPLETED 需無未完成項 |
| 遷移與文件 | 0015／0016 已套用、`makemigrations --check` 無變更；產品 Gate 仍 NOT_RUN |

證據：[後端原始結果](<t07-deletion-backend-tests.txt>)、[前端原始結果](<t07-deletion-frontend-tests.txt>)、[真實 HTTP](<t07-deletion-smoke.json>)、[來源與檢查摘要](<t07-deletion-validation.json>)。遠端 amd64 以本提交 Actions 為準；不推論 Windows／WSL2 已通過。

## SELF_REVIEW

- 宣告只走服務層：沒有對外刪除或隔離端點，客戶端不能指定要刪什麼，也不能藉 API 觸發傳播。
- tombstone 於宣告時立即生效，且不因刪除工作停在 BLOCKED 而回退；「立即停止讀取」是最小安全性質。
- Fail-Closed 由資料庫強制而非只靠應用層：`policy_status` 非 ACTIVE 時，任何轉入 PROPAGATING／COMPLETED 的寫入被 0016 的 guard 拒絕；COMPLETED 另需該請求下無未完成受影響物件，部分清理失敗不得顯示完成。
- 失敗與重試不收敛成單一分數：受影響物件、動作與結果逐項保存，`outstanding()` 供查核未完成項。
- 讀取不是只在建立時檢查一次：artifact 與證據包每次授權都回查 tombstone，因此舊列表與快取不構成繞道。
- 未實作 outbox、未宣稱索引／快取／訓練快照已清除，也未把 tombstone 說成備份已重播；`QUARANTINED` 仍只是值域預留。
- `AXIOM_DELETION_PROPAGATION_ENABLED` 預設 0（Fail-Closed），啟用僅在測試以 `override_settings` 演練，未以任何預設值對外開放。

## 遷移及後續

0015 建三表與唯一鍵、狀態值域；0016 加 native 複合 FK、BEFORE INSERT／UPDATE guard 與 tombstone 不可變觸發器，readiness 必須見到 0016。未修改既有 INGEST、研究、封存或證據包資料；回退須先停寫與備份，reverse 會移除 guard 與三張表，並非無損回退。

本批同時在開發堆疊觀察到資料庫漂移：規格級反轉重寫 `0001_initial` 後，既有開發資料庫仍保有已移除的 `catalog_account.role` 與 `catalog_grant`，導致帳號寫入違反 not-null。已重建本機開發資料庫（`axiom-dev` 的 `axiom` 資料庫）並重跑遷移後取證；此為本機可丟棄開發堆疊的處置，未觸及其他專案或部署環境。

下一步為對外刪除政策的決策（D-05）、outbox 與異步清除索引／快取、validation 引用、SEARCH 與候選比較、對外交付。工作台與盲測最終評估仍待後續；M0／M1 與企劃驗收維持 NOT_RUN。

## 提交後 CI 補批

日期：2026-10-22；承接 3eb3363。三個工作流於本提交全部成功：`docs-check` 36s、`compatibility-check` 48s、`product-check` 5m56s。因此 Linux amd64 上的完整後端測試與 `research_draft_smoke`（含本批新增的失效宣告段：宣告後 artifact 轉 409、證據包轉 404、二次宣告 409）皆為實際往返，不是由本機推論。產品 Gate 仍 NOT_RUN。

## 對外入口與非同步收斂補批

日期：2026-10-27。本批把失效宣告從服務層推向對外邊界，並在政策放行後接上異步逐項收斂；不動 tombstone 的「宣告即生效」語意，也不開放硬刪除。

交付：

- `POST /api/v2/dataset-versions/{id}/deletion-requests/dry-run`：只列 lineage 影響（`DeletionImpact`），不寫任何列；政策未放行時 `propagation_enabled=false`。
- `POST /api/v2/dataset-versions/{id}/deletion-requests`：以 `Idempotency-Key` 冪等宣告，回 `DeletionRequestView`；`GET` 讀回同一份工作，重送同鍵回同一結果。
- 來源授權 `source_for()`：租戶分區與資料集 owner 皆須相符，否則一律 404（不因知道 UUID 而可讀）。
- `catalog/deletion.py::due()`／`propagate()` 與 `relay_deletion()`／`catalog.deletion_tick`：政策放行後逐項核對 tombstone 存在再把 `DeletionTarget` 轉 `DONE`，全部完成才把請求轉 `COMPLETED` 並遞增 revision；缺 tombstone 者記 `BLOCKED`／`INVALID_TRANSITION` 不冒充完成。政策未放行時 `due()` 名單為空、`propagate()` 直接回 503 `FEATURE_DISABLED`。
- 契約三方同步：`openapi-v2.json` 新增 2 path／3 operation＋`DeletionImpact`／`DeletionRequestView` schema，AX-21 端點表同步，`api_operations` 30→33。

| 檢查 | 結果 |
|---|---|
| 完整後端 | PostgreSQL／Linux 容器全量通過，含刪除傳播 16 項斷言（10→16），無 skip |
| 服務層聚焦 | `catalog.tests.test_deletion` 16／16 OK |
| 工程工具 | `typing_policy` PASS（為 deletion／deletion_http／test_deletion 明列額度）；`development_baseline` PASS；`check_docs.py` exit 0（`api_operations` 33） |
| 真 HTTP（直連） | dry-run 200（受影響 8 項、未寫任何列）→ 宣告 201 → 同鍵重送回同一結果 → GET 讀回一致 → 二次宣告 409 `INVALID_TRANSITION`；宣告後 artifact 409、證據包 404 |
| 真 HTTP（前端同源） | 同上經 15173 同源代理，結果一致 |
| Fail-Closed 實測 | `AXIOM_DELETION_PROPAGATION_ENABLED=0` 時 `deletion_status=BLOCKED`、`policy_status=BLOCKED`、`blocked_code=FEATURE_DISABLED`、`outstanding=8`；`due()` 名單為空、`propagate()` 回 503 |
| 收斂實測 | 測試以 `override_settings` 放行後 `due()` 取得該請求、`relay_deletion()` 派送 1 次、`propagate()` 將 8 項收斂至 `DONE` 並轉 `COMPLETED`（revision +1） |

證據：[真實 HTTP](<t07-deletion-smoke.json>)、[來源與檢查摘要](<t07-deletion-validation.json>)。

本批仍不宣稱：outbox 事件、索引／快取／訓練快照的實際清除、備份還原重播；`QUARANTINED` 仍只是值域預留。D-05 未決前政策維持預設關閉，G2 仍 BLOCKED，產品 Gate 仍 NOT_RUN。
