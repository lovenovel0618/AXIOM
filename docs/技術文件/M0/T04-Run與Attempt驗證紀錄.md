# T04｜Run／Attempt 控制核心驗證紀錄

日期：2026-10-20；開發／SELF_REVIEW：project-owner。先行設計見 [控制核心](<T04-Run與Attempt控制核心.md>)；承接前輪 b47e58f 的本機骨架。

## 本輪交付

新增 backend/runtime：持久 RunRecord／AttemptRecord、不可變輸入／ExecutionManifest／初始預算快照、DB 時間租約、heartbeat、root epoch 取消、queue timeout、有限 lease-loss 重試、RUN 事件與公開 DTO allowlist。只接受 INGEST 根且強制 control_only；沒有研究 API、業務成功提交或實際上傳讀取。

| 驗證 | 實測 |
|---|---|
| 既有工程工具 | 74／74 unittest 通過 |
| PostgreSQL 後端 | 56／56 通過：18 基礎／健康檢查、38 新控制／canonical 案例 |
| Pyright | 根目錄及 backend 設定 strict，0 errors／0 warnings |
| Sonar Python | 48 檔 diagnostics=[]；保留 S3776 上限15，未使用忽略規則 |
| Sonar IaC | 兩份 Dockerfile 與 Compose，3 檔 diagnostics=[] |
| 編譯與 migration | compileall 通過；空庫套用 runtime.0001／0002，makemigrations --check 無差異 |
| 真實 Celery | runtime_smoke PASS；Run／Attempt 最後 CANCELLED，只有一筆 generation=1 Attempt |
| 事件 | RunQueued→RunStarted→RunCancelRequested→RunCancelled，cursor 序號4；heartbeat 不增加 revision 或事件 |
| 原骨架 | probe_smoke 仍 PASS、completions=1 |
| 文件／基線 | check_docs、330 組參考情境、權威來源 hash、自我檢查與 git diff --check 通過 |

完整紀錄見 [控制 smoke](<t04-run-smoke.json>)、[後端測試](<t04-run-tests.txt>)、[機器驗證](<t04-run-validation.json>)。Linux arm64 容器 Python 3.13.16，本機工具 Python 3.13.15；amd64 由 product-check 重跑同組 PostgreSQL／Celery 測試及 runtime_smoke，CI 最終結果以對應提交為準，WSL2 未測。

## 反例與自我檢查

- 四個並行 worker 只能建立一個有效 Attempt；重複訊息、錯 worker／generation、過期租約及取消前 epoch 均不能通過提交檢查。
- 輸入／環境／config hash、跨租戶引用、初始用量、backoff、超出 datetime 表達範圍等在入列前拒絕；相同 run_id 相同輸入重播不新增 row／事件，改輸入回衝突。
- PostgreSQL trigger 阻擋 QuerySet.update／delete 修改輸入快照及事件，並保護 Run 身分欄位；DB check 阻止把 control_only 改成 false。
- worker 不在線時，協調器仍能將 QUEUED 超時裁決為 FAILED；一批先做全部 recovery，再接觸 broker，發送失敗不跳過其他 row 的 deadline。輪詢時間輪替批次，等待 backoff 的任務不永久佔住首批。
- 根期限不因 heartbeat／重試延後；零 wall 額度不能當無限。租約重試保留原始起始時間、相同輸入 hash 與全部 Attempt 歷史，達上限後不再入列。
- 取消先提交時舊 lease 立即 ROOT_CANCELLED；只有可信控制流程確認無外部工作後收斂 CANCELLED。這不是實體 sandbox／遠端節點停止驗收。
- 事件寫入失敗時 Attempt／Run 同交易回滾；外層建立交易回滾不留下待派 Run 或事件。DTO 投影不含內部輸入、取消 epoch、帳本或 heartbeat 欄位。
- canonical 固定 UTF-8／Unicode code point 排序、安全整數、深32／2MiB；串流編碼有界累積，拒絕 float、非有限數、surrogate 及超限值。這是可信服務物件邊界；HTTP 嚴格 JSON 解析仍須在之後 API 接入時實作。

本輪沒有前端功能變更，前端 typecheck／8 項測試／build 由既有 product-check 前端 job 維持回歸。新增 runtime schema 驗證依賴後，backend runtime lock 以 T02 lock 為基礎另鎖 hash；dev lock 引用新的 runtime lock。新增 [runtime SBOM](<t04-runtime-sbom.cdx.json>) 來自 requirements lock，套件元資料／授權盤點不是法務核准。

## 遷移、回退與下一步

runtime.0001 建四表及 FK／唯一鍵／control-only 約束；0002 加 immutable／身分 trigger。既有 DispatchProbe 資料不搬移、不冒充 Run。ready 要求新 migration 已套用。降版須先停止 relay／worker，再回退0002移除 trigger；刪0001會失去控制紀錄，持久環境須先備份，本輪只用獨立測試 volume。

T04 最小工程控制基線可銜接 T05；完整 AX-38、產品 gate 及 M0 仍未關閉。下一步實作租戶／不可變物件／授權，再於 T07 接真實 INGEST 的 Run handler 及結果提交。預算快照不是 Reservation／UsageReport 帳本，零用量是未執行業務的控制 fixture；環境／plugin 的零 hash 亦明記合成占位，不是實際執行環境證據。研究任務樹、研究雙層預算、外部停止確認、checkpoint、final slot、搜尋與正式 SSE 等保持 NOT_RUN。沒有對外部署、正式盲測或 AI 請求。
