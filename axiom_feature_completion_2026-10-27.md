# AXIOM Feature Completion Audit

更新日期：2026-10-28

2026-10-28 接續實作（皆以 `docs/` 為權威，程式與文件同步修正）：

- **FIT 執行鏈**：對既有最小 FIT root 補上真實 `InputSnapshot`、`RootBudget`／`Reservation`、隔離重算與兩筆 `ValidationRun`（`split_role` 分別為 `FIT`／`DEVELOPMENT`，`metric_version="2.0"`，鍵齊但 `submission_id`／`frozen_candidate_id` 為 null），並接上 `relay_fit`／`catalog.fit_tick` 專用 `fit` queue（見 [T07-FIT執行鏈設計](docs/技術文件/M0/T07-FIT執行鏈設計.md)）。
- **時間與群組切分防線**：`TIME_ORDERED`（嚴格遞增時間與邊界 gap 覆蓋 lookback+horizon）與 `GROUPED_ROWS`（整組分派與 `group_assignment_digest`）已開放；版本建立只驗 metadata，真實值於隔離程序驗證後才 READY（見 [T07-時間與群組切分設計](docs/技術文件/M0/T07-時間與群組切分設計.md)）。
- **驗證結果數值語意硬化**：`catalog/result_semantics.py::verify` 固定分母、覆蓋率與可比較性，非 `INSUFFICIENT_EVIDENCE` 時不得缺 `mae`／`rmse`。
- **coverage 接線**：前後端 coverage 報告、CI artifact／路徑完整性檢查與可選的 Sonar 匯入（見 [執行與限制](tools/coverage/README.md)）。

實測佐證（dev 映像重建後於真實 PostgreSQL 執行）：`catalog.tests.test_fit`／`test_dependencies`／`test_final_evaluation` 44 項、`catalog.tests.test_search`／`test_inspection`／`test_research` 48 項、`tests.test_coverage_reports` 5 項全數通過。正式產品 Gate 與 `AX-46` 的 `NOT_RUN` 產品案例仍未跑。

這份盤點把「規格已定義」與「實作完成度」分開看，避免把 `NOT_RUN`、`BLOCKED`、`PARTIAL`、`未開工` 混成同一種狀態。

## 判定口徑

- `實作完成度`
  - `100%`：功能主體已交付，文件未再列出功能缺口
  - `75%`：主體已完成，但仍缺收尾模組、驗收接線或外部阻擋
  - `50%`：已有可用骨架或局部可用流程，但距離完整功能仍有明顯缺口
  - `25%`：只有前置資料層、基線能力或局部支撐，主功能尚未成立
  - `0%`：文件明示未開工，或只存在規格沒有實作跡象
- `驗收狀態`
  - `未跑`：文件明示 `NOT_RUN`
  - `阻擋`：文件明示 `BLOCKED`
  - `部分`：功能已交但該切口仍 `PARTIAL`
- 本表以 `docs/` 為權威來源；若文件與程式現況不同，以文件描述為準。

## 權威來源

- `docs/技術文件/缺口清單.md`
- `docs/技術文件/M0/T08-缺口審查與下一輪工作票.md`
- `docs/企劃案/11-交付/30-里程碑與分階段開發計畫.md`
- `docs/企劃案/11-交付/31-工作拆解WBS與依賴.md`
- `docs/企劃案/13-專題深化/46-驗收矩陣與交付證據.md`
- `docs/企劃案/14-自主研究/49-數據結構與自主表徵探索.md`
- `docs/企劃案/14-自主研究/50-研究決策軌跡與錯誤恢復.md`
- `docs/企劃案/14-自主研究/51-正確性證據與正逆向驗證.md`
- `docs/企劃案/14-自主研究/52-AI紀錄封存與經驗演化.md`

## 一頁總覽

| 階段 | 階段完成度 | 驗收狀態 | 摘要 |
|---|---:|---|---|
| M0 | 100% | 未跑 | 規格、契約、基線與審查票都已具備 |
| M1 | 75% | 未跑 | 可信核心與多數 T07 前置已落地，但 M1 仍未關閉 |
| M2 | 85% | 部分 / 阻擋 | 三策略、checkpoint、凍結 API、FIT 執行鏈與隔離驗證已交；正式產品 Gate 仍受阻 |
| M3 | 65% | 未跑 | 工作台已大量落地，40 頁 SSOT 已逐頁驗收；E2E、資安、壓測、備份還原仍未完成 |
| M4 | 10% | 未跑 | 規格完整，只有少數前置基線，主體未開工 |
| M5 | 5% | 未跑 | 只有 M1~M3 的最小證據基線，M5 主功能未開工 |
| M6 | 0% | 未跑 | 尚未開工 |
| M7 | 0% | 未跑 | 尚未開工 |

## M0：規格與基線

| 功能 | 實作完成度 | 驗收狀態 | 目前狀態 | 仍缺 |
|---|---:|---|---|---|
| 需求、契約、錯誤碼、API 權威文件 | 100% | 未跑 | 文件與 machine-readable 契約已建立 | 正式產品驗收證據 |
| M0/T01~T08 工作票與審查票 | 100% | 未跑 | T08 已交付，缺口盤點完整 | 不缺實作，缺後續產品驗收 |
| 里程碑、WBS、驗收矩陣 | 100% | 未跑 | AX-30 / AX-31 / AX-46 完整存在 | 依矩陣逐項補產品證據 |

## M1：可信數學核心與 T07 前置

| 功能 | 實作完成度 | 驗收狀態 | 目前狀態 | 仍缺 |
|---|---:|---|---|---|
| 本機開發骨架、Compose、健康檢查 | 100% | 未跑 | T04 已交 | 正式 Gate 驗收 |
| 帳號、租戶、不可變上傳 | 100% | 未跑 | T05 已交，bootstrap 與 account 流程可用 | 產品案例尚未跑 |
| DSL v1、canonical、受限求值 | 100% | 未跑 | T06 已交 | 產品案例尚未跑 |
| 有界匯入解析（CSV/JSON/Parquet） | 100% | 未跑 | T07 已交 | 產品案例尚未跑 |
| 建立前 metadata 預覽 | 100% | 未跑 | AX-49 的 metadata/f it 分工已接入 | 產品案例 AC-49-09~10 未跑 |
| 語意確認與固定 split | 75% | 部分 | 單一輸入、domain、切分、draft research，以及時間序與群組切分防線（`TIME_ORDERED`／`GROUPED_ROWS`）已交 | refit policy 仍維持明確拒絕、產品案例未跑 |
| 已知公式整合與 fit/development 評分 | 100% | 未跑 | 已有本機研究預檢與已知公式整合 | 產品案例未跑 |
| 研究帳本與 PROFILE 任務 | 100% | 未跑 | 兩層預算、PROFILE、事件與收據已交 | 產品案例未跑 |
| 正式封存與曝光帳本 | 100% | 未跑 | formal seal 與 authority 已交 | 產品案例未跑 |
| 證據包 | 100% | 未跑 | READY 同交易證據包已交 | 產品案例未跑 |
| 刪除傳播對外入口與異步收斂 | 75% | 部分 | dry-run、宣告、讀回、relay 收斂已交 | outbox、索引/快取實際清除、備份還原重播 |
| 最小 Trace / 決策紀錄基線 | 50% | 部分 | M1 起最小 trace chunk 與 journal 基線已規劃並部分落地 | 完整 AX-50 分級 trace 鏈、HRR、自動重審未做 |
| M1 端到端展示 | 50% | 未跑 | 可跑局部示範：上傳→確認→研究→已知公式求值 | 文件明示 M1 仍 IN_PROGRESS |

## M2：單序列引擎與隔離驗證

| 功能 | 實作完成度 | 驗收狀態 | 目前狀態 | 仍缺 |
|---|---:|---|---|---|
| 線性策略共用介面收斂 | 100% | 未跑 | M2-T1 已交 | 正式產品驗收未跑 |
| 多項式策略接入 | 100% | 未跑 | M2-T2 已交 | 正式產品驗收未跑 |
| 固定頻率諧波策略接入 | 100% | 未跑 | M2-T3 已交 | 正式產品驗收未跑 |
| SEARCH 派送、投影模式、逐策略 checkpoint 續跑 | 100% | 部分 | 切片 3 已交，SEARCH 完成後自動接上既有 FIT root | 切口僅待產品驗收，FIT 已補 |
| root/child 排程、租約、checkpoint | 100% | 未跑 | M2-T4 已交 | 正式產品驗收未跑 |
| 候選凍結 API、FrozenSubmission、snapshot_hash | 100% | 部分 | M2-T5 已交 | 該切口整體已無功能缺口，但驗收未跑 |
| FinalEvaluationSlot 資料層與 FINAL_ONLY validate | 100% | 部分 / 阻擋 | 槽位、派送、結果落庫、對外讀取已交 | D-03 未關，G2 仍 BLOCKED |
| ValidationRun 最終結果引用 | 100% | 部分 | 物件、證據包引用、身分核對與結果數值語意硬化（`result_semantics.verify`）已交 | 產品案例未跑 |
| FIT 執行管線 | 100% | 部分 | FIT 根任務管線落地：`attach`／`relay_fit`／`catalog.fit_tick`／`fit` 專用 queue／隔離重算／兩筆 ValidationRun，並附測試 | 正式產品驗收未跑 |
| 正式產品 Gate（G2） | 0% | 阻擋 | 文件明示 D-03 未關 | 需正式門檻決策與正式基準 |
| Sonar / coverage 驗證接線 | 75% | 部分 | 前後端報告、CI artifact、報告路徑檢查與可選 Sonar 匯入已接線，並附 `tests.test_coverage_reports` 反例測試 | Sonar 伺服器實際匯入與正式 new_coverage 門檻驗收 |

## M3：互動 MVP / 工作台

| 功能 | 實作完成度 | 驗收狀態 | 目前狀態 | 仍缺 |
|---|---:|---|---|---|
| 真實 Vue 路由外殼與模組化頁面 | 100% | 未跑 | 前台已改為真頁路由，不依賴設計殼 | 產品案例未跑 |
| 研究工作台真實版本 / 任務 / 候選 / 事件流程圖 | 100% | 未跑 | 已接真實資料流程 | 完整驗收未跑 |
| 研究清單 / 新建研究 / 工作台三拆頁 | 100% | 未跑 | 路由已拆出，文件有追溯 | 產品案例未跑 |
| 候選比較 UI | 100% | 部分 | 候選比較與多候選並排已交 | 切口整體仍 PARTIAL |
| SSE 斷線重連與 snapshot 還原 | 100% | 部分 | 已交 | 完整 M3 驗收未跑 |
| Run 清單與重開研究 | 100% | 部分 | 已交 | 完整 M3 驗收未跑 |
| 上傳與語意確認 UI | 100% | 部分 | 已交 | refit policy 深化仍未開放 |
| 證據檢視 UI 與最終評估面板 | 100% | 部分 | 已交 | 完整 M3 驗收未跑 |
| SEARCHING 與候選進度顯示 | 100% | 部分 | 切片 3 已交 | 完整 M3 驗收未跑 |
| 40 頁 UIUX 重製版整合 | 70% | 部分 | 40 頁 SSOT 已逐頁驗收：`frontend/src/lib/ssotPages.ts` 以 pages.json 建單一註冊表，`App.vue` 導覽與麵包屑由此推導，`frontend/tests/ssotPages.test.ts` 8 項檢查擋住漏做／張冠李戴／孤兒路由／英文標籤／圖片冒充組件，並附[循證](<docs/技術文件/M0/t07-m3-ssot-pages-validation.json>) | 跨頁互動、40 頁版面細節人工比對 |
| 完整跨頁互動 | 50% | 未跑 | 研究線、資料線、發現線多頁已拆 | 全鏈跳轉與細節整合仍待補 |
| E2E 測試 | 0% | 未跑 | 文件明示仍待補 | 全量 M3 E2E |
| 資安驗證 | 0% | 未跑 | 文件明示仍待補 | G5 對應驗證 |
| 壓測 | 0% | 未跑 | 文件明示仍待補 | G7 對應壓測與容量上限 |
| 備份 / 還原驗收 | 0% | 未跑 / 阻擋 | 文件明示仍待補，且受 D-06 影響 | BackupSet、恢復演練、journal 重播 |

## M4：記憶、AI 與 REQ-011~014 擴充

M4 在文件中的總狀態是「未開工」，但它包含很多獨立功能。以下按功能拆開。

| 功能 | 規格來源 | 實作完成度 | 驗收狀態 | 目前狀態 | 仍缺 |
|---|---|---:|---|---|---|
| 受限單輸入表徵搜尋 | AX-49 | 25% | 未跑 | 只有 M1~M3 的 identity 表徵、結構預覽與固定 split 基線 | 真正的 representation search、branch、Pareto 比較 |
| RepresentationSpec、row 依賴、正逆映射 artifact | AX-49 | 25% | 未跑 | 有凍結與 recipe 前置概念 | 完整 spec、信息損失、正逆映射凍結 |
| 原空間 Pareto 比較與跨表徵核對 | AX-49 | 0% | 未跑 | 尚無 docs 證據顯示已實作 | 多表徵比較、硬限制、selection bias 披露 |
| 表徵可回編 DSL v1 單輸入 AST | AX-49 | 0% | 未跑 | 尚未開工 | recipe 回編與凍結驗證 |
| 經驗記憶與檢索索引 | AX-16/17、AX-52 | 0% | 未跑 | 缺口清單明示 M4 未開工 | memory index、隔離、刪除鏈 |
| AI Gateway schema / budget / routing | AX-18、AX-52 | 0% | 未跑 | 尚未開工 | candidate model registry、routing、budget、fallback |
| AI runtime record 與 usage capture | AX-52 | 0% | 未跑 | 尚未開工 | AIRuntimeRecord、usage_source、PARTIAL/UNKNOWN |
| AI 原始紀錄儲存 policy 與 storage root | AX-52 | 0% | 未跑 | 尚未開工 | StoragePolicy、path policy、capacity、retention |
| archive / lossless 壓縮 / manifest | AX-52 | 0% | 未跑 | 尚未開工 | ArchiveManifest、校驗、原子切換 |
| ExperienceVersion / 摘要與經驗歸納 | AX-52 | 0% | 未跑 | 尚未開工 | support/oppose case、selection bias、supersedes |
| HRR 假設恢復與自動重審 | AX-50 | 0% | 未跑 | 尚未開工 | trigger、minimum_change、max_revisits、REASSESS |
| 失敗分類與 judgment 強度模型 | AX-50 | 25% | 未跑 | M1 有少量最小 trace / 診斷基線 | 完整 failure classes、judgment、故障注入 |
| 經驗先驗、no-memory 對照、反偏見 | AX-50/51 | 0% | 未跑 | 尚未開工 | priority 調整、negative transfer、calibration |
| RAG / 外部記憶 / 規則 / 權重三層晉級 | AX-52 | 0% | 未跑 | 尚未開工 | 記憶、規則、權重的獨立驗收與回退 |
| 本地模型候選驗收與路由基準 | AX-52 | 0% | 未跑 | 只有文件候選清單，沒有實作證據 | digest、能力實測、OOM / latency / canary |

## M5：推演、證明、逆解

| 功能 | 規格來源 | 實作完成度 | 驗收狀態 | 目前狀態 | 仍缺 |
|---|---|---:|---|---|---|
| 多軸 EvidenceAssessment 基線 | AX-51 | 25% | 未跑 | M1~M3 有最小數值/實證基線 | 完整多軸 status、artifact、理由模型 |
| 機率、區間與校準契約 | AX-51 | 0% | 未跑 | 尚未開工 | posterior / p-value / coverage / calibration contract |
| MAVE 多路徑驗證計畫 | AX-51 | 0% | 未跑 | 尚未開工 | method_group / assumption_group / implementation_group |
| 形式化 proof / checker 路徑 | AX-14、AX-51 | 0% | 未跑 / 阻擋 | 尚未開工，且受 D-07 影響 | proof graph、kernel 版本、可重放證書 |
| 正向 / 逆向證明與子目標 | AX-51 | 0% | 未跑 | 尚未開工 | sufficient conditions、subgoals、checked lemmas |
| InverseProblemResult 與五種逆解工作 | AX-51 | 0% | 未跑 | 尚未開工 | solution_status、identifiability、forward_check |
| 證據充分性的可信判定器 | AX-51 | 0% | 未跑 | 尚未開工 | evidence_sufficient trusted evaluator |
| 競爭解釋、反例與 scenario-only 因果輸出 | AX-51 | 0% | 未跑 | 尚未開工 | competitive explanations、counterfactual / causal guard |

## M6：雙序列與低維表徵

| 功能 | 規格來源 | 實作完成度 | 驗收狀態 | 目前狀態 | 仍缺 |
|---|---|---:|---|---|---|
| 雙序列資料模型與 split/lag guard | AX-15、AX-49、AX-51 | 0% | 未跑 | 尚未開工 | dual-series contract、假相關 guard |
| 時間對齊 / 時滯 / 多尺度輸出 | AX-15、AX-49 | 0% | 未跑 | 尚未開工 | alignment、lag、irregular sampling、multiscale |
| 二維 / 三維表徵 | AX-49、AX-15 | 0% | 未跑 | 尚未開工 | 2D/3D coordinates、representation artifacts |
| 有條件反演 | AX-51 | 0% | 未跑 | 尚未開工 | conditional inversion、domain constraints |
| 多維反演與低維觀測 | AX-49、AX-51 | 0% | 未跑 | 尚未開工 | multidimensional inverse problems |
| 新 major DSL / API 契約 | AX-30、AX-49 | 0% | 未跑 | 尚未開工 | 不能沿用 DSL v1，需新契約與遷移 |

## M7：多序列、訓練與策略演化

| 功能 | 規格來源 | 實作完成度 | 驗收狀態 | 目前狀態 | 仍缺 |
|---|---|---:|---|---|---|
| 多序列研究引擎 | AX-15、AX-19 | 0% | 未跑 | 尚未開工 | multiseries modeling |
| 狀態重建 | AX-49、AX-19 | 0% | 未跑 | 尚未開工 | state reconstruction |
| Strategy learning / ranking / controlled training | AX-19、AX-52 | 0% | 未跑 | 尚未開工 | training jobs、selection policy、rollback |
| TrainingDatasetManifest 與原觀測隔離 | AX-52 | 0% | 未跑 | 尚未開工 | partition_assignments、observation_group_id |
| LearningRelease / canary / rollback | AX-52 | 0% | 未跑 | 尚未開工 | baseline、ablation、canary、rollback |
| 校準 / 消融 / 負遷移監控 | AX-19、AX-52 | 0% | 未跑 | 尚未開工 | calibration、ablation、negative transfer |
| 選配微調 / adapter / 模型版本治理 | AX-19、AX-52 | 0% | 未跑 | 尚未開工 | adapters、weights、versioned releases |

## 全域阻擋與非功能缺口

| 項目 | 完成度 | 狀態 | 說明 |
|---|---:|---|---|
| 產品驗收矩陣執行 | 0% | 未跑 | AX-46 全表仍 `NOT_RUN` |
| G2 數學 Gate | 0% | 阻擋 | D-03 未關，正式 Gate 不可宣告通過 |
| G3 AI / 記憶 Gate | 0% | 未跑 | M4 後能力尚未開工 |
| G5 安全 Gate | 0% | 未跑 | M3 資安驗證未完成 |
| G7 營運 Gate | 0% | 未跑 / 阻擋 | 備份還原與 D-06 尚未完成 |
| 容量 / 壓測 / SLO | 25% | 未跑 | Sonar 已清零，但 coverage / 壓測 / 正式上限未完成 |

## 目前最接近「下一步就能做」的未完成功能

這些不是遠期規格，而是文件明示可逆開發、但尚未完成的項目：

1. `M3` 的完整 E2E / 資安 / 壓測 / 備份還原  
2. coverage 報告接線與 `tests.test_coverage_reports` 已於 2026-10-28 補上；續驗 Sonar 伺服器匯入與正式 new_coverage 門檻
3. 刪除傳播最後一段 outbox + 索引/快取實際清除  
4. `refit policy` 於語意確認的明確拒絕仍未開放  
5. `FIT` 執行鏈已於 2026-10-28 交付；續驗正式產品案例與循證文件

## 結論

- **主幹（含 FIT 執行鏈）已收斂，但還不是「大部分都收尾」的狀態。**
- `M1~M3` 屬於「主幹已長出來，但驗收與少數關鍵功能缺口還在」；本輪已補上 `M2` 的 FIT 執行鏈、時間／群組切分與結果語意硬化。
- `M4~M7` 屬於「規格很完整，但實作基本還沒展開」。
- 如果只看功能級完成度：
  - `M1~M3` 大多落在 `75%~100%`
  - `M4` 大多落在 `0%~25%`
  - `M5~M7` 幾乎都還是 `0%`
