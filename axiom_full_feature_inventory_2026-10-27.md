# AXIOM 全功能總表與完成度盤點

更新日期：2026-10-28

2026-10-28 接續實作：已補上前後端 coverage 報告、CI 保存與路徑檢查、可選的 Sonar 匯入，操作見 [coverage 說明](tools/coverage/README.md)。原盤點其餘功能狀態維持；正式 new_coverage 門檻及產品 Gate 尚未驗收。

這份文件的目標不是只回答「哪個階段做完沒」，而是把 **AXIOM 完整產品規格中的全部功能** 拆出來，包含：

- 功能需求 `REQ-001 ~ REQ-014`
- 非功能需求 `NFR-001 ~ NFR-007`
- 40 頁 UI/UX SSOT 畫面
- 研究線、資料線、驗證線、記憶線、模型/Ollama 線、訓練線、設定線
- 支援頁面與執行期頁面（登入、任務詳情、產物詳情、候選詳情）
- Gate / 驗收 / 阻擋條件

## 讀法

### 狀態欄位

- `規格狀態`
  - `已定義`：文件已明確定義功能
  - `未定義`：權威文件還沒有正式定義
- `前端頁面`
  - `已落地`：有 Vue view 與 route
  - `部分`：有頁面或共用殼，但仍依大量推導或缺資料
  - `無`
- `後端能力`
  - `已交付`：docs 已明示功能主體已交
  - `部分`：已有局部能力，但非完整功能
  - `未開工`：缺口清單或文件明示未開工
  - `缺端點/缺模組`：前端頁存在，但後端沒有專屬能力
- `驗收`
  - `NOT_RUN`
  - `PARTIAL`
  - `BLOCKED`

### 重要說明

1. 本表以 `docs/` 為權威來源，不以零散程式碼片段自行腦補完成度。
2. 「有頁面」不等於「有後端能力」。
3. 「有後端能力」不等於「已通過產品驗收」。
4. 對 Ollama 相關功能，特別拆出「規格 / 頁面 / 後端接線 / 訓練」四層來看。

## 權威來源

- `docs/企劃案/01-需求/02-需求規格與使用情境.md`
- `docs/企劃案/02-流程/04-端到端研究流程.md`
- `docs/企劃案/08-前端UX/23-頁面清單與資訊架構.md`
- `docs/企劃案/08-前端UX/24-畫面線框與互動流程.md`
- `docs/企劃案/11-交付/30-里程碑與分階段開發計畫.md`
- `docs/企劃案/11-交付/31-工作拆解WBS與依賴.md`
- `docs/企劃案/13-專題深化/46-驗收矩陣與交付證據.md`
- `docs/企劃案/14-自主研究/49-數據結構與自主表徵探索.md`
- `docs/企劃案/14-自主研究/50-研究決策軌跡與錯誤恢復.md`
- `docs/企劃案/14-自主研究/51-正確性證據與正逆向驗證.md`
- `docs/企劃案/14-自主研究/52-AI紀錄封存與經驗演化.md`
- `docs/技術文件/缺口清單.md`
- `docs/技術文件/M0/T08-缺口審查與下一輪工作票.md`
- `frontend/src/router.ts`
- `frontend/src/views/*.vue`

## A. 完整需求總表（REQ / NFR）

| ID | 功能 | 階段 | 規格狀態 | 後端能力 | 前端頁面 | 驗收 | 目前判定 |
|---|---|---|---|---|---|---|---|
| REQ-001 | 資料匯入與品質報告 | M1 | 已定義 | 已交付 | 已落地 | NOT_RUN | MVP 主幹已有 |
| REQ-002 | 自動公式候選生成 | M2 | 已定義 | 部分 | 已落地 | NOT_RUN | 三策略已交，但 FIT 未完 |
| REQ-003 | 獨立驗證與拒答 | M1~M2 | 已定義 | 部分 | 已落地 | NOT_RUN / BLOCKED | final gate 仍受阻 |
| REQ-004 | 公式片段與經驗記憶 | M4 | 已定義 | 未開工 | 頁面存在但多為推導/占位 | NOT_RUN | 記憶主體未做 |
| REQ-005 | AI 假說與策略協調 | M4 | 已定義 | 未開工 | 頁面存在但無後端接線 | NOT_RUN | Ollama / Gateway 未完成 |
| REQ-006 | 公式推演與證明 | M5 | 已定義 | 未開工 | 頁面存在 | NOT_RUN | proof / checker 未做 |
| REQ-007 | 雙序列關係 | M6 | 已定義 | 未開工 | 規格頁有、實頁無完整能力 | NOT_RUN | 尚未開工 |
| REQ-008 | 多序列研究 | M7 | 已定義 | 未開工 | 規格頁有、實頁無完整能力 | NOT_RUN | 尚未開工 |
| REQ-009 | 研究工作台 | M3 | 已定義 | 部分 | 已落地 | NOT_RUN | 工作台主體已成形 |
| REQ-010 | 可重現與版本化 | M1 | 已定義 | 已交付 | 已落地 | NOT_RUN | 版本、Run、Artifact 主幹已有 |
| REQ-011 | 自主結構與表徵探索 | M1→M4→M6/M7 | 已定義 | 部分 | 部分 | NOT_RUN | 只有 M1 結構確認基線 |
| REQ-012 | 決策軌跡與錯誤重審 | M1→M4 | 已定義 | 部分 | 部分 | NOT_RUN | 只有最小 trace 基線 |
| REQ-013 | 多軸正確性 / 正逆 / 多路徑 | M1→M5~M7 | 已定義 | 部分 | 部分 | NOT_RUN | 只有最小證據基線 |
| REQ-014 | AI 紀錄封存與模型演化 | M4 / M7 | 已定義 | 未開工 | 頁面存在但後端無 | NOT_RUN | capture / archive / training 未做 |
| NFR-001 | 效能延遲與吞吐 | M1~M3 | 已定義 | 部分 | 不適用 | NOT_RUN | 壓測與正式數據未完成 |
| NFR-002 | 可靠度與故障復原 | M1~M3 | 已定義 | 部分 | 不適用 | NOT_RUN | 備份還原與恢復演練未完成 |
| NFR-003 | 安全與租戶隔離 | M1~M3 | 已定義 | 部分 | 部分 | NOT_RUN | 基線有，資安驗收未完 |
| NFR-004 | 成本與預算治理 | M2 | 已定義 | 部分 | 部分 | NOT_RUN | 帳本有，coverage 與正式上限未完 |
| NFR-005 | 可及性與前端體驗 | M3 | 已定義 | 部分 | 部分 | NOT_RUN | 頁面多，但完整 UX 驗收未跑 |
| NFR-006 | 環境可重現性 | M0 | 已定義 | 部分 | 不適用 | NOT_RUN | 本機基線有，正式驗收未跑 |
| NFR-007 | 資料治理與保留 | M1 | 已定義 | 部分 | 部分 | NOT_RUN / BLOCKED | D-05 未關閉 |

## B. 核心執行功能總表

| 模組 | 子功能 | 前端 | 後端 | 驗收 | 狀態摘要 |
|---|---|---|---|---|---|
| 身分與登入 | login / logout / session / CSRF | 已落地 | 已交付 | NOT_RUN | 基線完成 |
| 租戶隔離 | tenant-scoped 404 / access_class | 無專頁 | 已交付 | NOT_RUN | 基線完成 |
| 不可變上傳 | upload session / sha / immutable object | 已落地 | 已交付 | NOT_RUN | 主幹完成 |
| 匯入解析 | CSV / JSON / Parquet bounded parsing | 已落地 | 已交付 | NOT_RUN | 主幹完成 |
| metadata 預覽 | 建立前結構預覽 | 已落地 | 已交付 | NOT_RUN | 主幹完成 |
| 語意確認 | domain / split / target / inputs | 已落地 | 部分 | PARTIAL | 時間/群組/refit 未開 |
| DSL 求值 | parser / canonical / bounded evaluator | 無專頁 | 已交付 | NOT_RUN | 主幹完成 |
| PROFILE | quality / structure assessment / research budget | 已落地 | 已交付 | NOT_RUN | 主幹完成 |
| SEARCH | strategy dispatch / projection / checkpoint | 已落地 | 已交付 | PARTIAL | SEARCH 主體完成 |
| FIT | SEARCH 後擬合 root / worker / 結果落庫 | 無完整專頁 | 部分 | PARTIAL | 關鍵未完 |
| 候選凍結 | FrozenCandidate / FrozenSubmission | 已落地 | 已交付 | PARTIAL | 主體已交 |
| 最終驗證 | FinalEvaluationSlot / FINAL_ONLY validate | 已落地 | 已交付 | BLOCKED | D-03 卡住 |
| ValidationRun | final result readback | 已落地 | 部分 | PARTIAL | FINAL_TEST 語意驗證未完 |
| 證據包 | evidence bundle / artifact linkage | 已落地 | 已交付 | NOT_RUN | 主幹完成 |
| 刪除傳播 | deletion request / dry-run / relay | 無專頁 | 部分 | PARTIAL | 最後一段清除鏈未完 |
| Trace / 決策紀錄 | trace chunk / decision graph / replay | 記憶頁面存在 | 部分 | NOT_RUN | 只有最小基線 |
| Backup / Restore | BackupSet / replay / journal recovery | 無專頁 | 部分 | NOT_RUN / BLOCKED | 尚未完成 |

## C. 40 頁 SSOT 畫面總表

### C1. 已有真頁路由的 40 個 SSOT 畫面

依 `frontend/src/router.ts` 與 `frontend/src/views/*.vue`，40 頁 SSOT 對應的真頁 **已全部存在路由 / view**。  
但「頁面存在」不代表「後端完整」。

| 頁碼 | 畫面 | 路由/頁面 | 前端頁面 | 後端資料完整度 | 目前判定 |
|---|---|---|---|---|---|
| 01 | 系統總覽 | `/overview` | 已落地 | 部分 | 頁面有，資料為局部快照推導 |
| 02 | 研究活動中心 | `/activity` | 已落地 | 部分 | 沒有全域任務端點 |
| 03 | 待處理事件 | `/pending` | 已落地 | 部分 | 由既有狀態推導 |
| 04 | 資源監控 | `/resources` | 已落地 | 部分 | 無即時硬體觀測端點 |
| 05 | 研究清單 | `/researches` | 已落地 | 部分 | 任務統計只涵蓋已讀頁 |
| 06 | 新建研究 | `/researches/new` | 已落地 | 部分 | 治理策略/外部傳輸欄位未揭露 |
| 07 | 研究工作台 | `/researches/:id` | 已落地 | 部分 | 真實研究流程已接入，但仍未完整驗收 |
| 08 | 研究詳情 | `/researches/:id/detail` | 已落地 | 部分 | 研究層摘要端點不存在，靠推導 |
| 09 | 研究分支圖 | `/researches/:id/graph` | 已落地 | 部分 | 分支依賴靠推導 |
| 10 | 研究任務紀錄 | `/researches/:id/timeline` | 已落地 | 部分 | 事件重播端點不存在，靠推導 |
| 11 | 資料集清單 | `/datasets` | 已落地 | 部分 | 有真頁，許多欄位未揭露 |
| 12 | 資料上傳精靈 | `/datasets/:id/upload` | 已落地 | 部分 | 四步精靈有，治理欄位未揭露 |
| 13 | 資料預覽 | `/datasets/:id/preview` | 已落地 | 部分 | 無 samples / 統計 / semantic details |
| 14 | 資料品質 | `/datasets/:id/quality` | 已落地 | 部分 | 品質面向多數未揭露 |
| 15 | 前處理管線 | `/datasets/:id/pipeline` | 已落地 | 部分 | 無完整 DAG 與參數資料 |
| 16 | 多維探索 | `/datasets/:id/explore` | 已落地 | 部分 | 投影與高維產物多數未揭露 |
| 17 | 資料版本比較 | `/datasets/:id/diff` | 已落地 | 部分 | lineage / rollback 流程未揭露 |
| 18 | 候選公式庫 | `/discoveries` | 已落地 | 部分 | 沒有全域候選端點 |
| 19 | 公式比較 | `/discoveries/compare` | 已落地 | 部分 | 依現有候選讀取範圍推導 |
| 20 | 隱藏變數探索 | `/discoveries/latent` | 已落地 | 部分 | intrinsic dimension 多為未取得 |
| 21 | 研究推演 | `/discoveries/derivation` | 已落地 | 部分 | 依現有節點/證據推導 |
| 22 | 驗證中心 | `/verification` | 已落地 | 部分 | 多軸矩陣仍多欄未揭露 |
| 23 | 反例搜尋 | `/verification/falsify` | 已落地 | 部分 | 反例空間與邊界條件未揭露 |
| 24 | 逆向推導 | `/verification/inverse` | 已落地 | 部分 | inverse solver 尚未真正交付 |
| 25 | 形式化證明 | `/verification/proof` | 已落地 | 部分 | proof/checker 後端未完成 |
| 26 | 證據關聯圖 | `/verification/graph` | 已落地 | 部分 | graph 仍多靠推導 |
| 27 | 知識庫 | `/memory` | 已落地 | 缺端點/缺模組 | 沒有專屬知識庫端點 |
| 28 | 研究經驗 | `/memory/experience` | 已落地 | 缺端點/缺模組 | 沒有經驗庫後端 |
| 29 | 失敗案例 | `/memory/failure` | 已落地 | 缺端點/缺模組 | 失敗知識主體未做 |
| 30 | 假設恢復 | `/memory/recovery` | 已落地 | 缺端點/缺模組 | HRR 未做 |
| 31 | 知識演化 | `/memory/evolution` | 已落地 | 缺端點/缺模組 | theory / knowledge evolution 未做 |
| 32 | Ollama 模型管理 | `/models` | 已落地 | 缺端點/缺模組 | 後端沒有模型 registry |
| 33 | 模型路由 | `/models/routing` | 已落地 | 缺端點/缺模組 | 沒有路由策略端點 |
| 34 | 模型能力評估 | `/models/evaluation` | 已落地 | 缺端點/缺模組 | 沒有 benchmark/score 端點 |
| 35 | Token 與儲存 | `/models/storage` | 已落地 | 缺端點/缺模組 | 沒有 token/storage 端點 |
| 36 | 訓練資料集 | `/training` | 已落地 | 缺端點/缺模組 | 沒有 training dataset 後端 |
| 37 | 微調任務 | `/training/finetune` | 已落地 | 缺端點/缺模組 | 沒有 finetune / LoRA 後端 |
| 38 | 模型版本發布 | `/training/release` | 已落地 | 缺端點/缺模組 | 沒有 release 後端 |
| 39 | 系統與安全設定 | `/settings` | 已落地 | 缺端點/缺模組 | 沒有角色/金鑰/MFA/加密治理端點 |
| 40 | 研究策略設定 | `/settings/research` | 已落地 | 部分 | 只投影已有 research version 固定欄位 |

### C2. 非 40 頁但屬執行期支援頁

| 功能頁 | 路由 | 狀態 |
|---|---|---|
| 登入頁 | `/login` | 已落地 |
| 任務詳情 | `/runs/:id` | 已落地 |
| 產物詳情 | `/artifacts/:id` | 已落地 |
| 候選詳情工作區 | `/candidates/:id?run=<searchRunId>` | 已落地 |

## D. Ollama / AI / 記憶 / 訓練 全功能總表

這一段是你特別在意的，我拆得最細。

### D1. Ollama / Gateway / 模型路由

| 功能 | 規格來源 | 前端 | 後端 | 驗收 | 判定 |
|---|---|---|---|---|---|
| LLM Gateway 結構化提案 schema | AX-18 | 無專頁，但模型頁相關 | 未開工 | NOT_RUN | 規格有，後端沒有 |
| Ollama 本地提案 | AX-18 | 模型頁存在 | 未開工 | NOT_RUN | 尚未接線 |
| ChatGPT / 外部 adapter 可替換接口 | AX-18 | 無專頁 | 未開工 | NOT_RUN / BLOCKED | D-04 未關前外部 adapter 停用 |
| 模型路由（難度/隱私/成本/歷史表現） | AX-18 | `/models/routing` 已落地 | 缺端點/缺模組 | NOT_RUN | 前端有頁，後端無路由器 |
| AI 提案 JSON schema 驗證 | AX-18 | 無專頁 | 未開工 | NOT_RUN | 尚未接線 |
| token 預算 / 速率限制 / 退避 / 成本上限 | AX-18 | `/models/storage` 頁存在 | 缺端點/缺模組 | NOT_RUN | 規格有，後端無 |
| 本地模型池 capability / memory 硬篩選 | AX-18、AX-52 | `/models` 相關頁存在 | 缺端點/缺模組 | NOT_RUN | 無 model registry / capability registry 端點 |
| AIRuntimeRecord | AX-18、AX-52 | 無專頁 | 未開工 | NOT_RUN | 核心缺失 |
| thinking / stream / usage 對帳 | AX-52 | 模型頁只顯示由 budget 推導的用量 | 未開工 | NOT_RUN | 沒有真實 AI runtime capture |

### D2. 記憶 / 經驗 / 知識演化

| 功能 | 規格來源 | 前端 | 後端 | 驗收 | 判定 |
|---|---|---|---|---|---|
| 知識庫索引 | AX-16、AX-52 | `/memory` | 缺端點/缺模組 | NOT_RUN | 頁面存在，後端未做 |
| 研究經驗庫 | AX-17、AX-52 | `/memory/experience` | 缺端點/缺模組 | NOT_RUN | 頁面存在，後端未做 |
| 失敗案例庫 | AX-50、AX-52 | `/memory/failure` | 缺端點/缺模組 | NOT_RUN | 頁面存在，後端未做 |
| 假設恢復 HRR | AX-50 | `/memory/recovery` | 未開工 | NOT_RUN | 核心未做 |
| 知識演化圖 | AX-17、AX-50、AX-52 | `/memory/evolution` | 缺端點/缺模組 | NOT_RUN | 主體未做 |
| ExperienceVersion / 支持反對案例 | AX-52 | 無完整專頁 | 未開工 | NOT_RUN | 未做 |
| 記憶、規則、權重三層晉級 | AX-52 | 部分占位 | 未開工 | NOT_RUN | 未做 |

### D3. 訓練 / 微調 / 發布

| 功能 | 規格來源 | 前端 | 後端 | 驗收 | 判定 |
|---|---|---|---|---|---|
| TrainingDatasetManifest | AX-19、AX-52 | `/training` | 缺端點/缺模組 | NOT_RUN | 未做 |
| partition_assignments / observation_group_id | AX-52 | 無 | 未開工 | NOT_RUN | 未做 |
| finetune / LoRA 任務 | AX-19、AX-52 | `/training/finetune` | 缺端點/缺模組 | NOT_RUN | 未做 |
| LearningRelease / baseline / canary / rollback | AX-19、AX-52 | `/training/release` | 缺端點/缺模組 | NOT_RUN | 未做 |
| paired A/B / negative transfer / calibration | AX-19、AX-52 | 無 | 未開工 | NOT_RUN | 未做 |
| 自動訓練 job 狀態 / 取消 / 恢復 API | AX-30、AX-52 | 無 | 未開工 | NOT_RUN | 未做 |

## E. 目前最不完整的區塊

如果用「離完整產品最遠」來排，現在最欠的是：

1. `M4`：記憶、AI Gateway、Ollama、AIRuntimeRecord、archive、HRR
2. `M5`：proof、checker、多路徑驗證、inverse problem
3. `M6`：雙序列、多維、時滯、2D/3D、conditional inverse
4. `M7`：多序列、state reconstruction、training、release、rollback
5. `M2` 剩餘缺口：`FIT` 執行管線
6. `M3` 剩餘缺口：E2E、資安、壓測、備份還原

## F. 關於「Ollama 有沒有做」

最直接的結論：

- **規格有，而且規格寫得很多**
- **前端 32~35 頁真頁都有**
- **但後端真正的 Ollama / model registry / routing / runtime capture / training 幾乎都還沒有完成**

具體證據：

- `frontend/src/views/ModelView.vue` 一開始就明寫：  
  後端沒有模型 registry 端點，模型名稱、上下文長度與模型版本一律標示「未取得」。
- `frontend/src/lib/modelCenter.ts` 也明寫：  
  後端沒有模型 registry、路由策略、基準測試或儲存配額端點。
- 缺口清單明寫 `M4` 未開工，而 `M4` 正是 AI Gateway / 記憶 / capture / HRR 那一整塊。

所以答案很明確：

- **Ollama 相關規格：有**
- **Ollama 相關畫面：有**
- **Ollama 相關後端實作：大部分沒有**
- **Ollama 相關驗收：沒有**

## G. 最終判定

如果你的問題是：

### 1. 「我要做的功能只有這些嗎？」
不是。  
完整產品功能遠多於目前已完成部分，尤其 `M4~M7` 還有大量未實作能力。

### 2. 「現在算夠完整、夠齊全嗎？」
不算。  
目前比較像：

- `M1~M3`：主幹做出來了，但還有關鍵缺口
- `M4~M7`：規格完整，但實作大多未開始

### 3. 「Ollama 相關有做嗎？」
只有 **規格 + 前端模型頁框架**，真正後端接線大多還沒做。

## H. 下一步若要再往下挖

這份已經是「全產品功能總表」等級。  
如果你要再更狠一層，我下一份可以直接做成：

1. `每個功能 -> 對應程式檔案 -> 是否真的落地`
2. `每個畫面 -> 用到哪些 API -> API 是否存在`
3. `Ollama / 記憶 / 訓練 -> 缺哪些 backend model / service / endpoint / queue / storage`

那份會更接近你要的「到底還差哪些程式要寫」。
