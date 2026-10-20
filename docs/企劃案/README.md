# AXIOM｜專案企劃與工程設計規格

> 文件版本 v2.9｜2026-10-20｜設計已修訂；產品實作、基準與發布簽核尚未執行

AXIOM（Adaptive eXploration, Inference, and Objective Mathematics，公理探索）是數據驅動的公式發現、獨立驗證、推演與經驗學習平台。MVP 僅單變量實數顯式函數：匯入、DSL v1、三基線策略、拒答、版本與工作台；記憶與 AI 在 M4，推演及雙／多序列在後續階段。

完整產品還包含自主表徵、決策與錯誤重審、正逆向多路徑驗證、AI紀錄與經驗演化；詳見AX-49～52，按M1～M7分段交付。

本目錄包含 54 篇編號章節（AX-00～53）、本索引、整合紀錄與全量審查清單，共 57 份 Markdown，另有 machine-readable contracts 與文件檢查工具。目前沒有可執行產品或產品 Compose 實作，Docker 命令是待實作的操作介面。文件／fixture 檢查通過不等同產品測試通過。

## 建議閱讀路徑

準備開始開發：先讀 [AX-31 開發流程與步驟](<11-交付/31-工作拆解WBS與依賴.md#依企劃案落地的開發流程>)，按 M0～M7 與 T01～T08 開工清單拆票；工程規範與目錄見 AX-53。

- 首次閱讀：[AX-00 專案憲章](<00-總覽/00-專案憲章.md>) → [AX-01 閱讀導航與文件地圖](<00-總覽/01-閱讀導航與文件地圖.md>) → [AX-02 需求規格與使用情境](<01-需求/02-需求規格與使用情境.md>) → [AX-30 里程碑與分階段開發計畫](<11-交付/30-里程碑與分階段開發計畫.md>) → [AX-48 共用契約與文件治理](<00-總覽/48-共用契約與文件治理.md>)。
- 數學／QA：[AX-10 公式DSL與等價正規化](<04-數學核心/10-公式DSL與等價正規化.md>) → [AX-05 基準測試與持續學習流程](<02-流程/05-基準測試與持續學習流程.md>) → [AX-28 數學基準測試規格](<10-測試/28-數學基準測試規格.md>) → [AX-13 可識別性不確定性與主動採樣](<04-數學核心/13-可識別性不確定性與主動採樣.md>) → [AX-34 術語表與證據等級](<12-附錄/34-術語表與證據等級.md>) → [AX-36 研究案例與情境測試](<12-附錄/36-研究案例與情境測試.md>) → [AX-46 發布驗收矩陣與交付證據](<13-專題深化/46-發布驗收矩陣與交付證據.md>)。
- 後端／資料：[AX-04 端到端研究流程](<02-流程/04-端到端研究流程.md>) → [AX-47 完整研究物件契約](<13-專題深化/47-完整研究物件契約.md>) → [AX-43 資料庫ERD與關係約束](<13-專題深化/43-資料庫ERD與關係約束.md>) → [AX-21 API與任務契約](<07-資料與API/21-API與任務契約.md>) → [AX-38 演算法插件與研究協調](<03-架構/38-演算法插件與研究協調.md>) → [AX-26 安全隱私與可信執行](<09-非功能/26-安全隱私與可信執行.md>)。
- 前端：[AX-22 設計系統與視覺規範](<08-前端UX/22-設計系統與視覺規範.md>) → [AX-23 頁面清單與資訊架構](<08-前端UX/23-頁面清單與資訊架構.md>) → [AX-24 畫面線框與互動流程](<08-前端UX/24-畫面線框與互動流程.md>) → [AX-44 研究工作台畫面詳細規格](<13-專題深化/44-研究工作台畫面詳細規格.md>) → [AX-35 畫面驗收清單](<12-附錄/35-畫面驗收清單.md>) → [AX-21 API與任務契約](<07-資料與API/21-API與任務契約.md>)。
- 維運：[AX-08 部署與運算資源規劃](<03-架構/08-部署與運算資源規劃.md>) → [AX-41 Docker本地架設指南](<03-架構/41-Docker本地架設指南.md>) → [AX-27 可觀測性備份與故障復原](<09-非功能/27-可觀測性備份與故障復原.md>) → [AX-45 非功能SLO與壓測方案](<13-專題深化/45-非功能SLO與壓測方案.md>) → [AX-37 決策待確認清單](<12-附錄/37-決策待確認清單.md>) → [AX-46 發布驗收矩陣與交付證據](<13-專題深化/46-發布驗收矩陣與交付證據.md>)。
- 記憶／AI：[AX-16 經驗記憶與檢索架構](<05-記憶/16-經驗記憶與檢索架構.md>) → [AX-17 知識圖譜與理論演化](<05-記憶/17-知識圖譜與理論演化.md>) → [AX-18 ChatGPT與Ollama協作](<06-AI/18-ChatGPT與Ollama協作.md>) → [AX-19 策略學習微調與蒸餾](<06-AI/19-策略學習微調與蒸餾.md>) → [AX-26 安全隱私與可信執行](<09-非功能/26-安全隱私與可信執行.md>)。
- 自主研究／治理：[AX-49 數據結構與自主表徵探索](<14-自主研究/49-數據結構與自主表徵探索.md>) → [AX-50 研究決策軌跡與錯誤恢復](<14-自主研究/50-研究決策軌跡與錯誤恢復.md>) → [AX-51 正確性證據與正逆向驗證](<14-自主研究/51-正確性證據與正逆向驗證.md>) → [AX-52 AI紀錄封存與經驗演化](<14-自主研究/52-AI紀錄封存與經驗演化.md>) → [全量審查、缺口與逐章覆蓋](<REVIEW.md>) → [AX-53 工程治理與開發者工作流](<15-工程/53-工程治理與開發者工作流.md>) → [AX-48 共用契約與文件治理](<00-總覽/48-共用契約與文件治理.md>)。

## v2.9 的核心規則

- 本地平台維持 ADR-006：macOS 開發、Windows 11 + WSL2 架設。
- 里程碑唯一依 AX-30；當期 MUST 以 AX-02／46 為準，不將全部未來能力當 MVP 前置。
- 搜尋只讀 fit/development；final_test 由隔離 Evaluator 在候選凍結後一次評估，詳細結果另查封存授權。
- 最終評估以持久化槽位跨run去重；盲測資格按觀測內容／可信來源雙token追蹤，來源檔變動不重置曝光。
- 研究固定欄位映射與EvaluationPolicy，凍結包包含policy hash；零候選以診斷報告正常結束，不建立空提交包。
- 研究版本累計預算與root預算分開，重新驗證不重置累計；曝光journal須獨立恢復到可信最新水位。
- 研究必填固定domain；時間切分依時間排序位置驗gap，原始row_id只供追溯。
- DSL v1、研究／內部物件 v2、API v2、事件 v2 有明確欄位與合法範例；跨物件、租戶與數學語意仍由實作驗證。
- 舊 worker 提交、取消／完成競態及預算預留以權威交易裁決；凍結後僅派最終評估，PROFILE停止後可回DRAFT重試。
- 預註冊聯集重擬合保存實際列與hash；封存消耗不可逆，同提交故障恢復不重置盲測資格。
- 研究快照與審核唯讀API可還原事件過期後的證據、品質報告及審核內容。
- 單位scale／offset與群組依賴顯式固定；所有求值使用canonical SI，評估保留完整分母及失敗列。
- 永久作者責任鏈防止自審，發布固定PublicationClaim；獨立摘要須另經政策核准且可由列表重新發現。
- 上傳鎖定不可變object version；執行manifest、有界重試、派送唯一鍵與租戶准入共同約束故障恢復。
- E/P 證據分軸；UNKNOWN、超時與數值近似都不能假標形式化證明。
- 外部 LLM 預設停用；正式基準、容量、保留與 RPO/RTO 等未決項有負責角色、階段期限與阻擋 gate。

## 全部章節

### 00-總覽

- [AX-00 專案憲章](<00-總覽/00-專案憲章.md>)
- [AX-01 閱讀導航與文件地圖](<00-總覽/01-閱讀導航與文件地圖.md>)
- [AX-48 共用契約與文件治理](<00-總覽/48-共用契約與文件治理.md>)

### 01-需求

- [AX-02 需求規格與使用情境](<01-需求/02-需求規格與使用情境.md>)
- [AX-03 成功指標與研究品質](<01-需求/03-成功指標與研究品質.md>)

### 02-流程

- [AX-04 端到端研究流程](<02-流程/04-端到端研究流程.md>)
- [AX-05 基準測試與持續學習流程](<02-流程/05-基準測試與持續學習流程.md>)

### 03-架構

- [AX-06 總體技術架構](<03-架構/06-總體技術架構.md>)
- [AX-07 模組邊界與事件契約](<03-架構/07-模組邊界與事件契約.md>)
- [AX-08 部署與運算資源規劃](<03-架構/08-部署與運算資源規劃.md>)
- [AX-38 演算法插件與研究協調](<03-架構/38-演算法插件與研究協調.md>)
- [AX-41 Docker本地架設指南](<03-架構/41-Docker本地架設指南.md>)

### 04-數學核心

- [AX-09 數據語意與前處理](<04-數學核心/09-數據語意與前處理.md>)
- [AX-10 公式DSL與等價正規化](<04-數學核心/10-公式DSL與等價正規化.md>)
- [AX-11 搜尋策略與公式組合](<04-數學核心/11-搜尋策略與公式組合.md>)
- [AX-12 參數最佳化與數值精度](<04-數學核心/12-參數最佳化與數值精度.md>)
- [AX-13 可識別性不確定性與主動採樣](<04-數學核心/13-可識別性不確定性與主動採樣.md>)
- [AX-14 推演一般化與形式化證明](<04-數學核心/14-推演一般化與形式化證明.md>)
- [AX-15 雙序列與多序列研究](<04-數學核心/15-雙序列與多序列研究.md>)

### 05-記憶

- [AX-16 經驗記憶與檢索架構](<05-記憶/16-經驗記憶與檢索架構.md>)
- [AX-17 知識圖譜與理論演化](<05-記憶/17-知識圖譜與理論演化.md>)

### 06-AI

- [AX-18 ChatGPT與Ollama協作](<06-AI/18-ChatGPT與Ollama協作.md>)
- [AX-19 策略學習微調與蒸餾](<06-AI/19-策略學習微調與蒸餾.md>)

### 07-資料與API

- [AX-20 資料模型與儲存規劃](<07-資料與API/20-資料模型與儲存規劃.md>)
- [AX-21 API與任務契約](<07-資料與API/21-API與任務契約.md>)

### 08-前端UX

- [AX-22 設計系統與視覺規範](<08-前端UX/22-設計系統與視覺規範.md>)
- [AX-23 頁面清單與資訊架構](<08-前端UX/23-頁面清單與資訊架構.md>)
- [AX-24 畫面線框與互動流程](<08-前端UX/24-畫面線框與互動流程.md>)

### 09-非功能

- [AX-25 效能與成本治理](<09-非功能/25-效能與成本治理.md>)
- [AX-26 安全隱私與可信執行](<09-非功能/26-安全隱私與可信執行.md>)
- [AX-27 可觀測性備份與故障復原](<09-非功能/27-可觀測性備份與故障復原.md>)
- [AX-40 資料治理倫理與領域適用性](<09-非功能/40-資料治理倫理與領域適用性.md>)

### 10-測試

- [AX-28 數學基準測試規格](<10-測試/28-數學基準測試規格.md>)
- [AX-29 驗收測試與品質閘門](<10-測試/29-驗收測試與品質閘門.md>)
- [AX-39 推導證明與理論演化測試](<10-測試/39-推導證明與理論演化測試.md>)

### 11-交付

- [AX-30 里程碑與分階段開發計畫](<11-交付/30-里程碑與分階段開發計畫.md>)
- [AX-31 工作拆解WBS與依賴](<11-交付/31-工作拆解WBS與依賴.md>)
- [AX-32 風險登錄與決策紀錄](<11-交付/32-風險登錄與決策紀錄.md>)

### 12-附錄

- [AX-33 語言框架與套件選型](<12-附錄/33-語言框架與套件選型.md>)
- [AX-34 術語表與證據等級](<12-附錄/34-術語表與證據等級.md>)
- [AX-35 畫面驗收清單](<12-附錄/35-畫面驗收清單.md>)
- [AX-36 研究案例與情境測試](<12-附錄/36-研究案例與情境測試.md>)
- [AX-37 決策待確認清單](<12-附錄/37-決策待確認清單.md>)

### 13-專題深化

- [AX-42 公式搜尋與推演決策樹](<13-專題深化/42-公式搜尋與推演決策樹.md>)
- [AX-43 資料庫ERD與關係約束](<13-專題深化/43-資料庫ERD與關係約束.md>)
- [AX-44 研究工作台畫面詳細規格](<13-專題深化/44-研究工作台畫面詳細規格.md>)
- [AX-45 非功能SLO與壓測方案](<13-專題深化/45-非功能SLO與壓測方案.md>)
- [AX-46 發布驗收矩陣與交付證據](<13-專題深化/46-發布驗收矩陣與交付證據.md>)
- [AX-47 完整研究物件契約](<13-專題深化/47-完整研究物件契約.md>)

### 14-自主研究

- [AX-49 數據結構與自主表徵探索](<14-自主研究/49-數據結構與自主表徵探索.md>)
- [AX-50 研究決策軌跡與錯誤恢復](<14-自主研究/50-研究決策軌跡與錯誤恢復.md>)
- [AX-51 正確性證據與正逆向驗證](<14-自主研究/51-正確性證據與正逆向驗證.md>)
- [AX-52 AI紀錄封存與經驗演化](<14-自主研究/52-AI紀錄封存與經驗演化.md>)

### 15-工程

- [AX-53 工程治理與開發者工作流](<15-工程/53-工程治理與開發者工作流.md>)

### 機器可讀契約與公開 fixture

- [attachment-requests-v1.json](<contracts/attachment-requests-v1.json>)
- [capability-registry-v1.json](<contracts/capability-registry-v1.json>)
- [error-codes-v1.json](<contracts/error-codes-v1.json>)
- [policy-registry-v1.json](<contracts/policy-registry-v1.json>)
- [research-learning-v1.schema.json](<contracts/research-learning-v1.schema.json>)
- [research-learning-v1.examples.json](<contracts/research-learning-v1.examples.json>)
- [api-v2.examples.json](<contracts/api-v2.examples.json>)
- [benchmark-v1.json](<contracts/benchmark-v1.json>)
- [conformance-v2.examples.json](<contracts/conformance-v2.examples.json>)
- [dsl-v1.examples.json](<contracts/dsl-v1.examples.json>)
- [dsl-v1.schema.json](<contracts/dsl-v1.schema.json>)
- [event-v2.examples.json](<contracts/event-v2.examples.json>)
- [event-v2.schema.json](<contracts/event-v2.schema.json>)
- [openapi-v2.json](<contracts/openapi-v2.json>)
- [review-coverage-v1.json](<contracts/review-coverage-v1.json>)
- [research-v2.examples.json](<contracts/research-v2.examples.json>)
- [research-v2.schema.json](<contracts/research-v2.schema.json>)
- [runtime-v2.examples.json](<contracts/runtime-v2.examples.json>)
- [runtime-v2.schema.json](<contracts/runtime-v2.schema.json>)
- [task-input-v2.examples.json](<contracts/task-input-v2.examples.json>)
- [task-input-v2.schema.json](<contracts/task-input-v2.schema.json>)

## 文件檢查方式

執行依賴鎖定於 [requirements.txt](<tools/requirements.txt>)；編輯與靜態檢查另使用 [requirements-dev.txt](<tools/requirements-dev.txt>)，包含Pyright及jsonschema型別宣告。T04 起從專案根目錄以 Python 3.13 建立含 backend runtime／stubs 的共用開發環境，再執行嚴格型別與文件檢查：

```sh
uv venv --python 3.13 .venv-backend
uv pip sync --python .venv-backend/bin/python --require-hashes backend/requirements-dev.lock
.venv-backend/bin/pyright
.venv-backend/bin/python docs/企劃案/tools/check_docs.py
```

專案根目錄的pyrightconfig.json採 strict 模式檢查 docs/企劃案/tools、tools、tests 及 backend；VS Code 設定預設使用專案 .venv-backend。若編輯器已選其他Python，執行「Python: Select Interpreter」選擇 .venv-backend/bin/python，然後重新啟動語言伺服器。.venv／.venv-backend 與 Python cache 不納入 Git。純執行驗證可只安裝requirements.txt；不能將執行通過當成靜態型別檢查通過。SonarQube for VS Code使用「Analyze Current File with SonarQube」或「Analyze Changed Files with SonarQube」檢查工具；維持S3776的預設15上限，不以停用規則消除提示。JSON動態欄位的Any僅用於schema資料邊界；工具函式、容器、Registry及第三方驗證器介面仍明確標註型別，不關閉診斷。

編輯後經審查再以 `--write-manifest` 重建清單，接著無參數重跑確認。工具檢查本地連結、編號、標頭版本、AC 追溯與決策引用、公開／內部 schema 正反例及投影一致、OpenAPI 雙向端點覆蓋、330 組跨契約參考情境、錯誤碼／能力／政策三份登錄與 AX-21／26／30／37／53 的雙向一致性、公開資料 oracle 與 manifest；不執行搜尋引擎、安全隔離、備份恢復或瀏覽器驗收。

## 整合與維護

[整合紀錄](<INTEGRATION.md>) 保存來源合併與本輪審查修訂；來源 `AXIOM_Project` 已在整合校驗後依使用者指示刪除。原 41 研究物件契約改為 AX-47，AX-41 保留 Docker。共用規則集中 AX-48，其餘章節保留各自的專屬案例。

[MANIFEST.json](<MANIFEST.json>) 包含 Markdown、contracts 及工具的 bytes／SHA-256，排除自身、.DS_Store 與 Python cache；受控副檔名為 `.md`、`.json`、`.py`、`.txt`、`.yml`、`.yaml`、`.toml`。documents 是 Markdown 數，file_count 是全部受控檔案數，files 筆數等於 file_count。

`14-自主研究/sources` 目錄以 `.txt` 保存四份使用者提供的原始討論原文，經 [attachment-requests-v1.json](<contracts/attachment-requests-v1.json>) 以 SHA-256／bytes 追蹤；來源中的助手建議不是已核准技術事實，採納或修正後才進權威規格。

## v2.9 這輪修訂

補齊十組可重現一致性缺口（RG-29～RG-38）：建立前結構預覽與 PROFILE 循環依賴、公開與封存共用 trace 鏈、canonical 格式與跨語言身分、凍結綁定表徵與驗證計畫、證據充分性自填、逆解多解與唯一性、訓練分區洗白原觀測、回退版本繼承污染、JSON 悄悄接受重複鍵與非有限數，以及錯誤碼、能力與政策缺登錄與閘門契約。新增 AX-49～52 自主研究與 research-learning-v1 契約，並新增 AX-53 工程治理與開發者工作流，將錯誤碼、能力與政策三份登錄收斂為單一真實來源（contracts/error-codes-v1.json、capability-registry-v1.json、policy-registry-v1.json），與 AX-21／26／30／37／53 及 OpenAPI Error.code enum 雙向校驗。同步 attachment-requests 與 review-coverage 基線。研究／事件schema升2.0、HTTP為/api/v2，DSL保持1.0；草案v1可從Git歷史取得，沒有既有部署或已遷移資料聲明。

[contract_scenarios.py](<tools/contract_scenarios.py>)僅實作公開fixture的參考裁決；不是真正的排程器、符號引擎或權限服務。正式產品的發布阻擋項仍依AX-37／46。

## 整體審查基線

[全量審查、缺口與逐章覆蓋](<REVIEW.md>)集中列出本版閉合的規格、待決策阻擋及實作驗收界線；機器覆蓋清單位於contracts/review-coverage-v1.json。文件已定義不代表產品已實作，所有產品案例仍NOT_RUN。
