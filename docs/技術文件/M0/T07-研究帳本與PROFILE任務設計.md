# T07 研究帳本與 PROFILE 任務設計

日期：2026-10-21；狀態：IMPLEMENTED_LOCAL（完整 T07 仍 IN_PROGRESS）；承接 160eb8b。沿 AX-21／38／43 的兩層預留、UsageReport 去重、root→研究帳本→root帳本鎖順序，將既有可信品質引擎接至實際 HTTP／broker／worker。

## 範圍及前提

新增原生 ResearchBudgetAccount、root BudgetAccount、Reservation 與不可變 UsageReceipt，建立 DRAFT 時原子建研究帳本；既有 DRAFT 在遷移時建立零起始帳本，因先前沒有正式研究任務。歷史 CLI Inspection 成本仍屬明示的本機預檢，不冒充已回溯計入研究帳本。研究配置原列保持 immutable，新增研究狀態投影保存 revision／active PROFILE／品質及 fit 結構引用，GET 合成權威 ResearchVersion；帳本用量改變不增加 control revision。

本批只擴充 PROFILE root，SEARCH／FIT／VALIDATE／REVOKE 仍停用。預設 PROFILE_ENABLED=false，明確啟用專用 worker／設定後才開放 validate；既有 INGEST gate 與隔離不變。POST 要求 CreateProfileRun、Idempotency-Key、If-Control-Revision；重送先查 ACL，再回原 Run，不重驗已完成操作的舊 revision。每個研究同時只一個 PROFILE，並持續保留跨 root 消耗。

品質引擎仍為 4096 列、無時間／群組／refit、精確單位與 float64 邊界政策；正式 PROFILE 不接受模型或讀 final 評分。quality Artifact 只含遮罩阻擋或 fit 統計；fit 結構 Artifact 可合法為 UNKNOWN，保存 fit_rows_hash、研究 ID、方法 manifest，不能假稱已識別週期或內在維度。因 SealedTest／曝光 ledger 仍未完成，品質成功也保持 DRAFT，報告明記 readiness=BLOCKED／SEALED_TEST_NOT_REGISTERED，不開搜尋或正式 final。

## 配額與權威資料

ResearchBudgetAccount 固定限額等於版本 budget；root 可帶較小 run_budget，省略時由剩餘額度與當期固定 worker 容量計算。CPU／GPU／token／candidate／研究順序 root 的 wall 以累計 usage+held 檢查；記憶體只檢查 active reservations，不將歷史 peak 再加到預留。PROFILE 同版本序列化，因此跨 root wall 累計不含並行重疊。root與研究使用同一 Reservation ID，唯一權威 receipt 同時將增量投影至兩層，不能把 root 彙總再次加回研究。

預留先建立 root 並鎖 root，再鎖研究帳本及 root 帳本；失敗整筆回滾。領取前 usage=0；完成／停止確認後才釋放餘額。UsageReport 具 usage_event_id、attempt／sequence、cumulative_usage；同 event／sequence 不同內容拒絕，完全相同重送不再扣帳，較舊 sequence 不覆蓋新用量。CPU／wall／token 等累計值不得倒退，peak 用 max，不把各歷史 peak 相加。已耗用增量從 held 移到 consumed，避免雙算。

已開始但失聯：Run 可 FAILED，但 reservation 保守標 UNCERTAIN，研究暫停新任務，不能當作零成本釋放。未 claim 的排隊逾期可確認未執行，釋放預留且不增加消耗。真正 owning handler 在固定 child 結束／reap 後可回報遲到用量與停止確認；即使 lease 過期或 Run 已終態仍入帳，不能提交產物或向終態 RUN stream 補事件。真正超支保留實際量並阻擋新預留，不裁切或清零。沒有自動重試未知成本。

## 派送、取消與結果

TaskInput／ExecutionManifest 保存實際來源版本、semantic、split、domain、evaluation_policy、ImportLimits、code／environment hash。專用 profile queue、單 concurrency、每 task 重啟 pool child、raw volume唯讀、container memory 2GiB；當期 PROFILE 預留 memory 至少 2GiB。root CPU／wall 須覆蓋固定 parser deadline 與控制餘裕，否則拒絕派送。這是本機固定 worker 容量，不是 D-01 正式 SLO／多租戶 sandbox 驗收。

worker 按既有 lease／generation／epoch 派送，來源讀取前與提交前重查 owner、User／Account 與 Dataset 寫 ACL、raw checksum、環境。actor／Dataset 授權鎖可先於 root；取得 root 後才鎖研究狀態及兩層帳本，不能持狀態／帳本再回頭鎖 root。解析時釋放 DB 鎖。結果、Artifact、狀態投影、用量／預留結算與 Run／Attempt 終態同交易；失敗不留半份結果。

只有擁有原 attempt 的停止證明可釋放；取消 epoch 先行時禁止任何產物，仍記帳並在 child 停止後確認 CANCELLED。relay 有界恢復 queue／lease；PROFILE recovery 及取消後收斂不走 INGEST handler。普通 GET Run／版本／Artifact 皆重新查 owner 研究與 Dataset ACL；研究 Artifact 原生綁研究版本，避免只靠 Dataset grant 暴露私有研究。原始與 TaskInput 仍 SEALED_DETAIL。

研究版本提供 owner／Dataset ACL 交集的 RunPage，依固定建立時間及 UUID 降序、最多 200 筆；15 分鐘簽章 cursor 綁 actor／tenant／研究版本，讓重新開頁可找回 root。SSE 每次回傳至多 100 個事件後關閉，客戶端以 Last-Event-ID 續接，每次重新驗權；不是常駐串流或完整工作台。

## 遷移及驗證

新增表以同租戶複合 FK、不可變身分／限額、receipt 唯一鍵、研究 active root／結果引用 guard 保護；runtime 僅放行有完整 PROFILE binding／帳本的非 control root。DRAFT immutable 內容不放寬，狀態投影禁止 READY。readiness 要求新 guards。停寫／排空後遷移，回退先備份；已有 PROFILE root／帳本時不可直接恢復 INGEST-only guard。

測試需涵蓋研究／root超額、相同請求、跨 root 累計、並行預留競爭、序號／event衝突、held→consumed、不加歷史 peak、取消與失聯後遲到、排隊超時、未知用量不釋放、原子回滾、ACL／跨租戶／原生 SQL 防改；真 HTTP→relay→專用 PROFILE worker→報告／用量／DRAFT。完整回歸、strict typing、實際 Sonar、文件檢查、SELF_REVIEW 後 commit／push 並核對 CI。
