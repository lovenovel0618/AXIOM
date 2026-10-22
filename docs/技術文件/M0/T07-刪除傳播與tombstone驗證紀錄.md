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
