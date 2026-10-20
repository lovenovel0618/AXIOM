# T04｜Run／Attempt 持久化控制核心

日期：2026-10-20；owner／SELF_REVIEW：project-owner。先行設計，依 AX-21／38／48 及 runtime-v2、research-v2、task-input-v2、event-v2 契約實作。

## 交付範圍

本輪延續 T04：以無研究版本的 INGEST 根任務實作控制核心，保存完整 RunRecord／AttemptRecord、不可變 TaskInput／ExecutionManifest／初始 BudgetAccount 快照及 RUN stream 事件。公開 DTO 只按 research schema 的 allowlist 投影；控制層不開 HTTP 業務路由。SEARCH／子樹、研究預算、final slot、外部產物提交、計量與 checkpoint 暫不啟用，輸入直接拒絕而非悄悄放行。

這一輪的真實 Celery smoke 僅執行控制流程：持久排隊→worker 領取→心跳→取消→worker 確認停止，最後 CANCELLED。它不讀取上傳物件、不解析資料、不產生 DatasetVersion，也沒有宣稱 INGEST 成功的 SUCCEEDED 入口。T05 會接入租戶及不可變物件授權，T07 才接實際匯入執行與提交。控制服務的 tenant UUID 為可信呼叫者傳入的範圍，並非認證系統。

## 持久化與驗證

Run、Attempt、輸入快照、事件分表；Run row 為控制鎖，Attempt 外鍵與 (run,generation) 唯一鍵保存歷史。INGEST 根滿足 root_run_id=id、parent=null、is_root=true、research_version=null、dataset_id 非 null，budget 為同租戶／同 root、初始全零用量與空預留。只有此明確子集可入列。

契約 schema 隨映像唯讀打包；以 offline Registry 驗證所有引用、format、required、extra fields，不允許網路抓取 schema。AX-48 canonical profile 限深32、2MiB、安全整數，拒絕 float、非有限數、surrogate；TaskInput hash 及 plugin config hash 實際重算。入列同時核對 tenant、run、input／execution IDs、environment digest、seed、重試上限與 backoff。提交前重驗 immutable snapshot，不能在重試時換成最新設定。

輸入快照的更新／刪除及 Run 身分欄位變更以 PostgreSQL trigger 阻擋；不只覆寫 ORM.save。Run／Attempt／事件 shape 仍由可信服務驗證，DB 額外約束身分一致、有效狀態、世代與事件序號唯一；沒有宣稱通用 JSON Schema 可在 DB 中原生執行。

## 控制交易

所有操作先以 tenant+run_id 取得 Run row lock，再取得該 Run 的 Attempt。時間一律查詢 PostgreSQL clock_timestamp()，不信任 worker 傳入時間。租約60秒，heartbeat 建議15秒；heartbeat 只更新 Attempt，不增加公開 revision。

- claim：要求 QUEUED、未超 queue deadline、重試等待已到且訊息世代相符；建立新 Attempt，generation+1、Run→RUNNING，同交易寫 RunStarted。重複／過期派送無新 attempt。
- heartbeat：核對 tenant、run、active attempt、generation、worker、root epoch、未過期租約；拒絕舊 worker，無 revision／業務事件副作用。
- recovery：到期 Attempt 記 EXPIRED，保留歷史；未超 max_attempts／根 wall deadline 則 QUEUED 並保存指數退避及 queue deadline；耗盡則 FAILED／DEPENDENCY_FAILURE 或 BUDGET_EXHAUSTED。重試不重置根開始時間。只有 lease-loss 可自動重試。
- cancel：核對 expected revision，根鎖內設 CANCEL_REQUESTED、epoch+1、dispatch CLOSED，寫事件。重複取消在相同條件下不重複增加 epoch；終態拒絕，heartbeat 不造成前置 revision 衝突。
- stop confirmation：可信控制 worker 的確認可收斂此控制流程。控制 worker 不啟動外部子程序，確認時先停止其控制工作；沒有把租約到期當作真實 sandbox 已回收。只在本輪 control-only 任務無外部工作這個條件下可 CANCELLED。

事件與狀態在同一 PostgreSQL 交易寫入，sequence 與 current_event_cursor 同步；heartbeat 不寫事件。Relay 由持久 QUEUED/CANCEL_REQUESTED 紀錄重送，Redis 只作通知，訊息不攜 manifest 或憑證。broker 重送不增加有效 claim。事件表是本輪 durable outbox，尚未提供 SSE 或宣稱通知 exactly-once。

## 驗證設計與完成界線

測試使用真實 PostgreSQL：並行 claim、不同 tenant、輸入 hash／跨引用、DB immutable trigger、世代／worker／epoch／到期 fencing、heartbeat revision 不變、queue timeout、有限重試與 backoff、cancel 競態與事件交易回滾、公開投影不洩漏內部欄位。真實 broker／worker smoke 驗證完整控制生命週期並保存契約可驗證紀錄。根目錄 strict Pyright、Sonar、文件及既有測試維持通過，再 commit／push 並查 CI。

T04 工程控制切片與正式產品驗收分開。完整 AX-38 任務樹、資源停止確認、budget reservation／UsageReport 及 ingest 結果提交未實作時仍明列 NOT_RUN，不能以控制 smoke 關閉這些案例。
