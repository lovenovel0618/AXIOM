# AXIOM 技術文件

依 [企劃案開發流程](<../企劃案/11-交付/31-工作拆解WBS與依賴.md>)，每輪先交技術設計，再交對應程式、測試、代碼檢測、自我檢查與實測紀錄，最後 commit／push。

| 階段／工作票 | 技術設計 | 驗證紀錄 | 實際狀態 |
|---|---|---|---|
| M0／T01 | [開發基線與驗證工具](<M0/T01-開發基線與驗證工具.md>) | [本輪驗證](<M0/T01-驗證紀錄.md>) | 工具與測試已實作；已確認單人開發／SELF_REVIEW；決策及 M0 整體交付尚未完成 |
| M0／T02 | [技術選型與相容性驗證](<M0/T02-技術選型與相容性驗證.md>) | [本輪驗證](<M0/T02-驗證紀錄.md>) | macOS／Linux arm64 與 Node 24 驗證通過；Windows WSL2、完整授權及產品 gate 尚未驗收 |
| M0／T03 | [公開基準與盲測隔離基線](<M0/T03-公開基準與盲測隔離基線.md>) | [本輪驗證](<M0/T03-驗證紀錄.md>) | 四個公開 oracle、分區／投影參考驗證與 Linux 真實 UID canary 通過；正式盲測及產品隔離尚未驗收 |
| M0／T04（基礎切片） | [產品工程骨架](<M0/T04-產品工程骨架.md>) | [本輪驗證](<M0/T04-驗證紀錄.md>) | 本機 Compose、Django／Vue、遷移、健康檢查與合成派送已實作；已續交 INGEST 根 Run／Attempt 控制核心，完整領域整合仍待 M1 |
| M0／T05 | [租戶與不可變上傳](<M0/T05-租戶與不可變上傳設計.md>) | [驗證紀錄](<M0/T05-租戶與不可變上傳驗證紀錄.md>) | session／CSRF、租戶分區、版本化本機 adapter、冪等與雙路 HTTP smoke；真實 INGEST／S3／正式對外尚未啟用 |
| M0／T06 | [安全 DSL 求值](<M0/T06-安全DSL求值設計.md>) | [驗證紀錄](<M0/T06-安全DSL求值驗證紀錄.md>) | 本機有界編譯／求值、單位與域檢查、canonical 身分及獨立 oracle；真實 INGEST 整合待 T07 |
| M0→M1／T07（解析前置切片） | [有界匯入解析](<M0/T07-有界匯入解析設計.md>) | [驗證紀錄](<M0/T07-有界匯入解析驗證紀錄.md>) | 三格式解析、Linux程序限制及固定版本預覽；已續交下一切片的真正INGEST，研究版本待後續 |
| M0→M1／T07（INGEST／Artifact） | [提交設計](<M0/T07-INGEST與Artifact提交設計.md>) | [驗證紀錄](<M0/T07-INGEST與Artifact提交驗證紀錄.md>) | 明確啟用的真實Run／專用queue／原子版本及metadata Artifact，三格式HTTP實測；已續交研究草稿；PROFILE／已知公式整合仍待後續 |
| M0→M1／T07（研究草稿） | [語意確認設計](<M0/T07-研究草稿與語意確認設計.md>) | [驗證紀錄](<M0/T07-研究草稿與語意確認驗證紀錄.md>) | owner 私有研究、現行 Dataset access_class、精確語意／域／切分及不可變 DRAFT；PROFILE／正式封存／評估待後續 |
| M0→M1／T07（研究預檢與已知公式） | [整合設計](<M0/T07-研究預檢與已知公式整合設計.md>) | [驗證紀錄](<M0/T07-研究預檢與已知公式整合驗證紀錄.md>) | 三格式有界品質／精確單位轉換、fit 統計與已知 DSL 的 fit／development 評分、遮罩與不可變記錄；正式 PROFILE／帳本／封存仍待後續 |
| M0→M1／T07（研究帳本與 PROFILE） | [任務設計](<M0/T07-研究帳本與PROFILE任務設計.md>) | [驗證紀錄](<M0/T07-研究帳本與PROFILE任務驗證紀錄.md>) | 兩層預留與不可變用量收據、真 HTTP／專用 worker、遮罩品質與 fit-only 結構、取消／恢復與私有事件；正式封存及 READY 尚未開放 |
| M0→M1／T07（正式封存與曝光帳本） | [封存登記設計](<M0/T07-正式封存與曝光帳本設計.md>) | [驗證紀錄](<M0/T07-正式封存與曝光帳本驗證紀錄.md>) | Evaluator 私有 SQLite authority、tenant-scoped 曝光 token 與 append-only journal、Unix socket RPC 及 UID 10002／10004 隔離；真 HTTP→INGEST→PROFILE→封存→READY 與 `formal_seal: IMPLEMENTED` 已實測，SEARCH／候選凍結／最終評分仍待後續 |
| M0→M1／T07（證據包） | [證據包設計](<M0/T07-證據包設計.md>) | [驗證紀錄](<M0/T07-證據包驗證紀錄.md>) | READY 同交易自動登記不可變證據包、租戶一致 404、複合 FK 與引用 guard；真 HTTP 直取與前端同源皆實測，validation 引用、SEARCH 與交付仍待後續 |
| M0→M1／T07（刪除傳播與 tombstone） | [刪除傳播與 tombstone 設計](<M0/T07-刪除傳播與tombstone設計.md>) | [驗證紀錄](<M0/T07-刪除傳播與tombstone驗證紀錄.md>) | 服務層失效宣告、同交易 tombstone 與刪除工作、讀取回查；policy 未放行時 Fail-Closed 停在 BLOCKED，真 HTTP 直取與前端同源皆實測，對外刪除 API／outbox 與異步清除仍待後續 |
| M0→M1／T07（SEARCH 執行器） | [搜尋執行器設計](<M0/T07-SEARCH執行器設計.md>) | [驗證紀錄](<M0/T07-SEARCH執行器驗證紀錄.md>) | 三策略離線擬合（線性最小平方、多項式 degree 2／3、固定頻率諧波字典）、AX-38 manifest 驗證、canonical DSL 身分與正規化去重、EquationVersion 不可變落庫；SEARCH run 身分與候選／擬合／凍結已由候選凍結切片交付，`final_test` 評估仍待後續 |
| M0→M1／T07（候選凍結與比較） | [候選凍結與比較設計](<M0/T07-候選凍結與比較設計.md>) | [驗證紀錄](<M0/T07-候選凍結與比較驗證紀錄.md>) | 五張 catalog 表（Candidate／FitRun／FrozenCandidate／ObservationSplit／RepresentationSpec）、`development_rank` 持久化與同結構去重、最小不可變 recipe、凍結鏈逐條 Fail-Closed 與零候選診斷、`SEARCH`／`FIT` root 不被既有 relay 派送、`FrozenSubmission`／`snapshot_hash`（catalog 0021／0022）與租戶一致的讀取 API、`FinalEvaluationSlot`（runtime 0007／0008）與 FINAL_ONLY `VALIDATE` root 的固定輸入派送（`final_manifest` + `enqueue` 同交易快照與 outbox、`final_bindings` 身分核對、runtime 0009／catalog 0024 guard）、最終結果的同一權威提交（`settle` 於 `COMPLETED` 逐欄核對身分與政策後，將 `ValidationRun`（runtime 0010／0011）、證據包與 `ValidationFinished` outbox 與槽位、提交狀態同交易落庫）、曝光預留與消耗接線（`catalog/sealing.py` 的 `reserve`／`consume`／`retire` 於 `acquire` 派送時預留、`settle` 時消耗或保守退役）；派送觸發的凍結 API、隔離 Evaluator 的 `final_test` 執行與 `Vault.read_final` 授權讀取仍待後續 |

企劃中的產品驗收維持 NOT_RUN。T04 控制設計見 [Run／Attempt 控制核心](<M0/T04-Run與Attempt控制核心.md>)，實測見 [控制核心驗證](<M0/T04-Run與Attempt驗證紀錄.md>)。T05 已完成本機租戶／物件版本／上傳基線；T06 已提供本機有界安全 DSL 求值；T07 已交有界解析及明確啟用的真正 INGEST／Artifact；已續交人工語意與 ResearchVersion 草稿，已續交本機可信品質預檢與已知公式整合，已續交明確啟用的 PROFILE 任務與研究帳本，已續交 Evaluator 專用封存登記與曝光帳本，已續交 READY 版本唯讀證據包（品質報告與結構評估兩項封存產物），已續交來源失效宣告與 tombstone（tombstone 立即生效、D-05 未決前刪除工作 Fail-Closed 停在 BLOCKED），已續交 SEARCH 執行器離線策略核心與 EquationVersion 不可變落庫（三策略 fit／development 擬合、canonical 身分與正規化去重），已續交候選凍結與比較離線核心（五張 catalog 表、`development_rank` 持久化與同結構去重、最小不可變 recipe、凍結鏈 Fail-Closed 與零候選診斷、`FrozenSubmission` 與 `snapshot_hash` 及租戶一致的讀取 API），已續交最終評估槽位資料層與 FINAL_ONLY `VALIDATE` root 的固定輸入派送（runtime 0007／0008 的業務鍵唯一、必為 PENDING 起始、單向結算與不可改刪，runtime 0009／catalog 0024 放行 guard；`catalog/final_manifest.py` 產生 `FINAL_TEST` 文件並經 `runtime.control.enqueue` 與快照及 outbox 同交易落庫，`final_bindings` 交叉核對身分），已續交最終結果的同一權威提交（`catalog/final_evaluation.py` 的 `settle` 於 `COMPLETED` 逐欄核對 `run_id`／`submission_id`／`frozen_candidate_id`／`fit_run_id`／政策雜湊等身分後，將不可變 `ValidationRun`（runtime 0010／0011）、只引用結果的證據包與 `ValidationFinished` outbox 與槽位引用、提交聚合狀態同交易落庫），已續交曝光預留與消耗接線（`catalog/sealing.py` 的 `reserve`／`consume`／`retire` 於 `acquire` 派送時以凍結提交預留封存包、`settle` 於 `COMPLETED` 先消耗後落庫、`FAILED` 保守退役；`sealed_authority()` 收斂為全 catalog 共用夾具，`test_final_evaluation.py` 改以真實 `Vault.register` 逐案核對 `RESERVED`／`CONSUMED`／`RETIRED`；隔離 Evaluator 的 `final_test` 執行與 `Vault.read_final` 授權讀取未寫），下一步接最終盲測評估執行段與工作台整合。不因骨架測試通過就啟用 AI、正式盲測或對外開放。

人員基線：只有使用者本人開發；Backend／Frontend／Math／QA／SRE 為兼任責任，不是招募需求。工作票預設依序執行，自我檢查為單人流程紀錄，不冒充獨立覆核。

T01 的 JSON 保存當時規劃快照，實際技術交付進度與重現證據以本索引及各輪驗證紀錄為準。

服務交接與型別／繁體中文註解規範見 [規範](<M0/T07-服務常駐與型別註解規範.md>)，修正前狀態、可操作服務與當輪實測見 [驗證紀錄](<M0/T07-服務與型別強化驗證紀錄.md>)。開發服務 axiom-dev 保留運行；測試環境清理與使用者開發服務分開。

尚未交付的技術文件切片（T08、M1 完整、M2～M7 及各 T07 剩餘切片）只列範圍與依賴，見 [技術文件缺口清單](<缺口清單.md>)。
