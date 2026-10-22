# T07｜SEARCH 執行器驗證紀錄

日期：2026-10-22；owner／SELF_REVIEW：project-owner；承接 90c1430。切片設計見[技術設計](<T07-SEARCH執行器設計.md>)。本批交付三策略離線擬合與 EquationVersion 不可變落庫；T07 仍 IN_PROGRESS。

## 交付範圍

依 AX-11 交付線性最小平方、多項式 degree 2／3 與固定頻率諧波字典三策略，共用 AX-38 的插件 manifest 介面；manifest 只接受已列舉的 14 個欄位，未知欄位與越界值一律拒絕，插件因此無法以宣告取得寫 DB、產生 EvidenceBundle 或對外送出的權限。擬合只使用 fit 列，development 列只用於評分與排序；輸入介面沒有 `final_test` 欄位，頻率不能由最終測試選擇。

求解以列主元 Householder QR 進行，不反解 normal-equation matrix；rank 判定為相對最大奇異值的列主元估計（1e-12），rank 不足時保留退化診斷而不強行給唯一參數。fit 先以均值／尺度正規化再求解並保存逆變換，使結果 AST 對回原始變數；正規化只作用線性／多項式的 x 與三族共用的 y，諧波字典定義在原始 x 軸故不正規化 x。諧波 `omega` 以 12 位有效數字（`ROUND_HALF_EVEN`）寫入 `param` 的 `lower=upper`，評估與排序一律使用同一取整值，未取整浮點值與精度另記診斷。

候選身分沿用 T06 的 canonical DSL，`identity_hash` 為 canonical bytes 的 SHA-256；等價 AST 依 AX-10 去重並保留全部生成來源。EquationVersion 契約不含 run 引用，因此可在本批落庫；同租戶 `(identity_hash, dsl_version)` 唯一，重複登記讀回同一列，不重建身分。量測沿用非權威標記（`usage_scope=LOCAL_SEARCH_EXECUTION_ONLY`、`product_status=NOT_RUN`、`precision_bits=53`）。

本批同時把研究檢視的評分函式抽為共用模組 `mathematics/metrics.py`（研究檢視與 SEARCH 共用同一份 `score`／`quantile`），`ingestion/research.py` 改為引用共用模組，未改變既有研究檢視行為。

## 檢查與實測

| 檢查 | 結果 |
|---|---|
| 完整後端 | PostgreSQL／Linux arm64 容器 304／304（新增 20 項：`test_linalg` 7、`test_search` 7、`test_equations` 6），無 skip |
| 前端 | strict typecheck 0 error；vitest 9 檔 77／77；build 63 modules（js 144.31 kB／css 9.87 kB） |
| 工程工具 | `typing_policy` PASS（新增 `metrics.py`／`search.py`／`test_search.py`／`test_equations.py` 四筆額度，並收斂 `models.py` 與 `equations.py`）；`development_baseline` PASS；`check_docs.py` exit 0 |
| 嚴格型別 | 根與 backend Pyright 1.1.414：0 errors／0 warnings |
| 公開 oracle | `python -m mathematics.smoke` PASS（公開 oracle 與十進位參考） |
| 離線真實執行 | `search()` 於容器實跑：`proposed_count=8`、`duplicate_count=0`，三策略皆 `EXECUTED`（3／2／3）；線性最小平方 `c0=3`、`c1=-2`，development MAE `0`；多項式 degree 2／3 MAE `8.88e-16`；諧波 k=1／2／3 MAE `10.118`／`7.882`／`7.882`，診斷含 3 條 `FIXED_PRECISION_FREQUENCY` 與 1 條 `ALIASING_RISK` |
| 資料庫守門 | 真 PostgreSQL 上驗證 EquationVersion 兩唯一鍵、`dsl_version` 值域、`identity_hash` 格式、UPDATE／DELETE 一律拒絕、同身分重複登記讀回同一列、跨租戶不可見 |
| 遷移與文件 | 0017／0018 已套用、`makemigrations --check` 無變更；產品 Gate 仍 NOT_RUN |

證據：[後端原始結果](<t07-search-backend-tests.txt>)、[前端原始結果](<t07-search-frontend-tests.txt>)、[離線真實執行](<t07-search-fixture.json>)、[來源與檢查摘要](<t07-search-validation.json>)。遠端 amd64 以本提交 Actions 為準；不推論 Windows／WSL2 已通過。

## SELF_REVIEW

- 候選順序固定為 development MAE、AST 複雜度、成本形狀、`identity_hash` 的決定性 tie-break，不以牆鐘時間參與排序，重跑同輸入得到同一順序。
- 諧波相位在 AST 與評估皆為 `sin(omega*x)`／`cos(omega*x)`（x 不中心化），與頻率字典定義在同一軸上，避免字典與公式不一致。
- 實測發現並修正真實缺陷：含截距最小平方原先只把常數項做 y 逆變換，未把中心化 t 的截距逆變換回原始 x 軸，`x` 均值非零時 DSL 的 `c0` 會偏掉；今以完整二項式逆展開（`_expand`）修正，並補回歸測試 `test_least_squares_intercept_is_back_transformed_from_a_nonzero_centre` 鎖定 `c0=3`／`c1=-2` 與 MAE `0`。
- 三策略都必須留下執行或不適用紀錄：資料不足（少於 degree+1 或 4 個不同 x、`T<=0`）以 `NOT_APPLICABLE` 保存診斷，不靜默回一個看似成功的候選。
- 本批只輸出離線候選身分，未建立 SEARCH run、Candidate／FitRun／FrozenCandidate，未做候選凍結、未評估 `final_test`，也未開放對外端點；`usage_scope`／`product_status` 標記使報告不得被當成產品成果。
- 非權威量測不被冒充為帳本：成本形狀只是確定性計數，不是 BudgetUsage，本批不建立任何帳本列。

## 遷移及後續

0017 建 EquationVersion 兩唯一鍵與 `dsl_version` 值域；0018 加原生 guard，寫入時 `document` 的 `kind`、`schema_version`、`id`、`tenant_id`、`created_at`、`identity_hash`、`dsl.dsl_version` 必須與資料列同步，`identity_hash` 必須為 64 位小寫十六進位，UPDATE 與 DELETE 一律拒絕。本批沒有任何資料表引用 EquationVersion，故不新增複合 FK；待候選凍結切片建立 Candidate 時再一併加上 `(equation_version_id, tenant_id)`。

下一步為候選凍結與比較（#4）、最終盲測評估（#5，D-03 未關使 G2 保持 BLOCKED）與工作台整合（#6）。validation 引用仍受阻於 FitRun／FrozenCandidate 尚未存在。M0／M1 與企劃驗收維持 NOT_RUN。

## 提交後 CI 補批

日期：2026-10-22；承接 03de531。三個工作流於本提交全部成功：`docs-check` 48s、`compatibility-check` 48s、`product-check` 4m35s。因此 Linux amd64 上的完整後端測試（含 `mathematics.test_linalg`／`mathematics.test_search` 與 EquationVersion 測試）與 `python -m mathematics.smoke` 皆為實際往返，不是由本機推論。產品 Gate 仍 NOT_RUN。

