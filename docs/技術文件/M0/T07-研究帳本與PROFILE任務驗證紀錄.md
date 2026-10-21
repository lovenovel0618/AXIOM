# T07｜研究帳本與 PROFILE 任務驗證紀錄

日期：2026-10-21；owner／SELF_REVIEW：project-owner；承接 160eb8b。[設計](<T07-研究帳本與PROFILE任務設計.md>)先於代碼。交付 PROFILE 與兩層用量帳本；T07 仍 IN_PROGRESS。

## 交付及界線

DRAFT 建立時原子建立研究額度帳本；PROFILE 以同一 Reservation 預留研究／root 額度，持久不可變 UsageReceipt 同交易增量投影兩層。POST validate 實際建立 root／TaskInput／manifest，經 relay、broker 與獨立 profile worker 執行既有可信品質引擎。成功保存 owner 私有 QualityReport 與 FIT_ONLY／UNKNOWN StructureAssessment；品質阻擋只保存遮罩報告。

每個研究同時一個 PROFILE，結束後仍 DRAFT；報告 readiness=BLOCKED／SEALED_TEST_NOT_REGISTERED。正式封存／曝光 ledger、READY／SEARCH、通用重試及任務樹、時間／群組／refit、工作台尚未交付。歷史 CLI Inspection 成本保留原實測，不回溯冒充已扣研究帳本。未啟用時 validate 仍 503。

## 驗證結果

| 檢查 | 實測 |
|---|---|
| 完整後端 | PostgreSQL／Linux arm64 266／266，既有 241＋新增 25，無 skip |
| 工程工具 | 74／74；baseline PASS、m0_ready=false |
| 前端 | strict typecheck、8／8 與 build 通過；本批無 UI 變更 |
| 嚴格型別 | 根與 backend Pyright 0 errors／0 warnings |
| 實際 Sonar | 124 Python／3 IaC 檔，診斷均 0；未關閉規則或加入 suppression |
| 真正 PROFILE | CSV／JSON／Parquet 真 HTTP→INGEST→DRAFT→PROFILE queue／worker→品質與 fit 結構；六個 root 完成 |
| 帳本 | 三格式每 root CPU／wall 向上取整各 1 秒；同研究第二 root 累計各 2 秒；每 root 一 receipt、reservation RELEASED、root CLOSED |
| 拒絕流程 | 剩餘容量不足 429 且不留新 root；非法 final 標記遮罩，撤權後 Run／Artifact／事件及快取重送 404 |
| 既有流程 | default gate、catalog 直連／前端代理、probe／runtime、解析預覽、真正 INGEST、研究草稿及已知公式 CLI smoke 通過 |
| 遷移／容量 | 空庫套 catalog 0009／0010、runtime 0005；makemigrations --check 通過；實際 profile container 2GiB／1 CPU／64 pids、raw volume 唯讀 |

證據：[後端測試](<t07-profile-backend-tests.txt>)、[前端檢查](<t07-profile-frontend-tests.txt>)、[真服務報告](<t07-profile-smoke.json>)、[來源與檢查摘要](<t07-profile-validation.json>)。本機 Linux arm64；遠端 amd64 依本提交 Actions，不推論 WSL2 或正式容量已驗收。完整測試後另修正舊 CLI smoke 的描述標籤為 NOT_EXECUTED_BY_CLI，重跑該真服務示範；不改品質邏輯。

## SELF_REVIEW

- 同 key 並行只一 root／預留；不同 key 同 revision 競爭為 202／412。RunPage 跨頁找回 root，簽章 scope／過期機制與現行 ACL 避免重開時繞權。研究事件每次最多 100 筆，Last-Event-ID 精確檢查 stream／scope／序號，並非常駐 SSE。
- root 先鎖，再鎖研究狀態、研究帳本及 root 帳本；actor／Dataset 授權可在 root 前鎖，解析期間不持 DB 鎖。額度、狀態、產物、Run／Attempt 終態及 receipt 在同交易；結果 callback 寫完部分 Artifact 後故障全部回滾，但 owning handler 停止確認仍如實入帳一次。
- CPU／wall／token 等 usage＋held 不雙算；不同 root 不重置研究消耗；歷史 memory peak 不再加入新預留。event／attempt sequence 衝突、倒退、偽造 worker 拒絕；相同重送不重扣，舊序號只保存 receipt 不改投影。
- 真正超支 101 保留 101 並進 CLOSING，遲到 102 繼續保留，無裁切／清零。原生 deferred guard 比對研究＝各 root 合計、root＝各 attempt 最新 receipt 合計，peak 使用 max；限額與身分不可變、receipt／研究事件不能改刪。SQL guard 的 JSON operator 括號及 PL/pgSQL alias 衝突已修正並經完整回歸。
- 未開始 queue timeout／取消可釋放零成本。已開始失聯保留 UNCERTAIN，拒絕新預留；取消不假稱 child 已停止。原 owning handler 在子程序結束／reap 後才釋放，lease 過期或 Run 已終態仍入帳；不接受遲到產物、不向終態 Run 補事件。
- 執行前及提交前重新查 owner、User／Account、Dataset grant、source SHA／固定物件版本與 environment；child 結束後撤權或 lease 過期均不提交結果。其他 ADMIN 即使有 Dataset grant 也不能讀私有研究報告；raw／TaskInput 仍 404。結構只分析 fit，週期／內在維度 UNKNOWN，不捏造識別成果。
- CPU／wall 向上取整，RSS 為 process high-water 保守和；涵蓋 handler 主要執行區間與 child，wall 至結算前，不含最後 DB commit／broker／跨程序成本。2GiB cgroup 是實際容量限制，並不表示每 root 實耗 2GiB或完整計費／租戶 quota。

## 升級、回退及後續

升級先排空並備份，同版 web／worker／relay 套 catalog 0009／0010、runtime 0005；readiness 要求新 migration。既有 DRAFT backfill 零帳本，因舊版本只有明示 CLI 成本；本輪實測空庫安裝，未宣稱大型歷史庫遷移／恢復演練完成。既有 PROFILE root 時 reverse 會拒絕直接切回 INGEST-only guard；應另制定有備份的遷移，不能刪帳本取回配額。

清理只限 axiom-t07e-check 的可丟棄容器與 volume。未啟用正式 sensitive source、AI／GPU、正式封存、公開服務或產品 Gate。下一步需先定正式 SealedTest／曝光與取得 READY 的技術路徑，再接工作台；D-01～09 未決不因本批測試自動核准。
