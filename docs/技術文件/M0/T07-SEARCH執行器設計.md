# T07 SEARCH 執行器設計

狀態：已實作、已驗收（限本批離線策略核心與 EquationVersion 落庫）；T07 仍為 IN_PROGRESS。本批只把 fit／development 資料擬合成公式候選並保存不可變候選身分，不建立 SEARCH run、不建立 Candidate／FitRun，也不開放對外端點。實測見[驗證紀錄](<T07-SEARCH執行器驗證紀錄.md>)。

## 交付邊界

三策略依 AX-11 的 M2 基線固定設定：線性最小平方（先產常數零、fit 均值、含截距最小平方）、多項式 degree 2 與 3、固定頻率諧波字典 `omega=2*pi*k/T`（k=1,2,3，`T=max(x_fit)-min(x_fit)`）。三策略共用 AX-38 的插件 manifest 介面；manifest 只接受已列舉欄位，未知欄位一律拒絕，因此插件無法以宣告取得寫 DB、產生 EvidenceBundle 或對外送出的權限。

擬合只使用 fit 列，development 列只用於評分與排序，`final_test` 完全不在本批輸入介面內（AX-11：頻率不能由 final_test 選擇）。擬合係數帶單位，因此在 AST 以 `param`（`lower=upper` 十進位字串）表徵，`const` 只用於無量綱值；`omega` 使用 x 的逆單位，不能以無量綱常數冒充帶單位係數。

候選身分沿用 T06 的 canonical DSL：root 經既有正規化後編譯，`identity_hash` 為 canonical bytes 的 SHA-256；等價 AST 依 AX-10 去重並保留全部生成來源。EquationVersion 契約（`research-v2` 的 `EquationVersion`）不含 run 引用，因此可在本批落庫；同租戶 `(identity_hash, dsl_version)` 唯一，重複擬合讀回同一列，不重建身分。

本批量測沿用非權威標記：報告附 `usage_scope=LOCAL_SEARCH_EXECUTION_ONLY`、`product_status=NOT_RUN`、`precision_bits=53`，不宣稱 SEARCH run 已執行或產品 Gate 已通過。

## 數值與去重

最小平方以列主元 Householder QR 求解，禁止反解 normal-equation matrix；rank 判定為 `|R_kk| <= 1e-12 * |R_00|`，即相對最大奇異值的列主元估計，rank 不足時保留退化診斷而不強行給唯一參數。fit 輸入先以 fit 均值／尺度正規化再求解，並保存逆變換，使結果 AST 對回原始變數；常數項與係數都回寫成原始尺度的 `param`。正規化只作用在線性／多項式族的 x（轉為 `t=(x-mean)/scale` 求解後以二項式展開回原始 x 的冪次）與三族共用的 y；諧波族的頻率字典定義在原始 x 軸（`T=max(x_fit)-min(x_fit)`），因此 x 不正規化，僅做 y 的逆變換。

諧波頻率採固定精度近似：`omega` 以 12 位有效數字（`Decimal`，`ROUND_HALF_EVEN`）寫入 `param` 的 `lower=upper`，評估與排序一律使用同一個取整值，診斷另記未取整浮點值、k、T 與精度，不混用近似值與精確值。資料不足（少於 degree+1 或 4 個不同 x、`T<=0`）或疑似混疊（`omega` 乘平均間距達 π 以上）都保存診斷，不靜默回一個看似成功的候選。

每個候選記錄確定性的成本形狀：fit 列數、未知數個數、pivot 次數、AST 節點數、development 列數，以及 manifest 宣告的 `timeout_seconds`、`memory_bytes`、`resource_class`。這不是 BudgetUsage；權威預留與用量仍是 M2 的 BudgetReservation／BudgetUsage，本批不建立任何帳本列，也不以牆鐘時間參與排序。

候選順序固定為 development MAE、AST 複雜度、成本形狀、`identity_hash` 的決定性 tie-break；本批只輸出這個離線順序，持久化的 `development_rank` 與同 rank 去重屬候選凍結切片。

## 儲存不變條件與驗證

0017 建 EquationVersion：同租戶 `(id, tenant)` 與 `(tenant, identity_hash, dsl_version)` 兩個唯一鍵，`dsl_version` 只接受 `1.0`。0018 補原生 guard：寫入時 `document` 的 `kind`、`schema_version`、`id`、`tenant_id`、`created_at`、`identity_hash`、`dsl.dsl_version` 必須與資料列同步，`identity_hash` 必須是 64 位小寫十六進位；UPDATE 與 DELETE 一律拒絕，公式版本因此不可改寫也不可刪除，同一身分不能出現兩份真相。本批沒有任何資料表引用 EquationVersion，因此不新增複合 FK；待候選凍結切片建立 Candidate 時才一併加上 `(equation_version_id, tenant_id)`。

測試涵蓋：三策略數值結果與獨立參考對照（精確有理數閉式解、另一套求解路徑）、等價 AST 去重且保留來源、rank 不足與混疊診斷、manifest 未知欄位與越界值拒絕、`final_test` 不出現在輸入介面、真 PostgreSQL 上的唯一鍵與 guard、重複登記讀回同一列、跨租戶不可見。

明確不在本批：SEARCH run 與派送／租約／checkpoint、Candidate／FitRun／FrozenCandidate 資料列、validation 引用、`final_test` 評估、候選凍結與對外 API、outbox 與異步清除。
