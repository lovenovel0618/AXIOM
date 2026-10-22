# 21｜API與任務契約

> AXIOM v2.9 設計規格｜文件 ID AX-21｜狀態：待實作、待驗收｜2026-10-20

## 文件定位與決策摘要

MVP API 以 /api/v2 為前綴，JSON 使用 UTF-8，傳輸使用 HTTPS（本機開發可 HTTP）；v2 瀏覽器採同源 session cookie 與 CSRF，服務帳號採限制 scope 的 bearer token。

## 契約範圍與認證

MVP API 前綴 /api/v2，JSON 使用 UTF-8，傳輸使用 HTTPS（本機開發可 HTTP）。機器可讀端點、請求與回應見 [openapi-v2.json](<../contracts/openapi-v2.json>)。v2 瀏覽器採同源 session cookie 與 CSRF，服務帳號採限制 scope 的 bearer token；細節見 AX-26。M4 以後的 /experiences、/models、/proofs 尚非 MVP API，未啟用時回 FEATURE_DISABLED，不能暗中啟用外部路由。

## 逐端點語意

所有 {id} 皆 UUID；列表回 items 與 next_cursor，limit 預設 50、上限 200，cursor 為不透明字串。排序固定 created_at、id，cursor 綁租戶與篩選，未知／過期回 INVALID_CURSOR。/datasets、/researches 預設依建立時間倒序；候選未凍結按 created_at/id 升序，凍結後按 development_rank/id 升序；cursor 綁定排序模式及snapshot版本，模式變更回 INVALID_CURSOR 要求重新列表。研究、版本及run列表按 created_at/id 倒序；同租戶仍須租戶分區過濾。

| Method / 路徑（省略前綴） | 輸入 | 成功／副作用 |
|---|---|---|
| POST /datasets | name | 201 Dataset，尚無可用版本 |
| GET /datasets | cursor、limit | 200 DatasetPage，不能枚舉其他租戶 |
| POST /datasets/{id}/uploads | filename、format、size_bytes、sha256 | 201 UploadSession，回15分鐘有效的signed PUT URL，條件式建立／版本固定依AX-09 |
| POST /uploads/{id}/complete | checksum | 202 INGEST run；掃描、schema、hash 全過後才建立 DatasetVersion |
| GET /datasets/{id}/versions | cursor、limit | 200 VersionPage，僅可引用 AVAILABLE 版本 |
| GET /researches | cursor/limit | 200 ResearchPage |
| GET /researches/{id} | — | 200 Research，可供重新開啟 |
| GET /researches/{id}/versions | cursor/limit | 200 ResearchVersionPage，版本列表 |
| GET /research-versions/{id}/runs | cursor/limit | 200 RunPage，含已終態及子run，is_root標示根 |
| GET /research-versions/{id}/events | Last-Event-ID | 200 研究生命週期SSE，不因某run終態關閉 |
| GET /frozen-submissions/{id} | — | 200 FrozenSubmission |
| GET /frozen-candidates/{id} | — | 200 FrozenCandidate，固定FitRun與參數 |
| POST /researches | name | 201 Research 容器，與執行分離 |
| POST /researches/{id}/versions | dataset_version_id、semantic_profile、observation_split、domain、evaluation_policy、budget、purpose、可選refit_policy | 201 DRAFT ResearchVersion，內容固定，新修改另建版本 |
| GET /research-versions/{id} | — | 200 ResearchVersion+X-Control-Revision，取得狀態轉移前置版本 |
| GET /evidence-bundles/{id} | — | 200 EvidenceBundle+X-Control-Revision，取得目前證據快照與版本 |
| POST /research-versions/{id}/validate | 可選run_budget | 202 PROFILE run，合法時版本 READY，否則 DRAFT+品質報告 |
| POST /research-versions/{id}/runs | type=SEARCH、seed、可選run_budget | 202 QUEUED run，須 READY；原子預留預算 |
| GET /runs/{id} | — | 200 Run+X-Control-Revision，包括 status、phase、attempt、stop_reason、成本與有效產物引用 |
| POST /runs/{id}/cancel | {} | 202 CANCEL_REQUESTED 或已確認 CANCELLED；終態／子run 409 |
| GET /runs/{id}/events | Last-Event-ID | 200 text/event-stream；只輸出該 run 的事件 |
| GET /runs/{id}/candidates | cursor、limit | 200 CandidatePage；未驗證UI由validation_status顯示E0／P0，完成後讀ValidationRun兩軸 |
| GET /equation-versions/{id} | — | 200 EquationVersion，DSL 與 hash 用於候選顯示 |
| GET /fit-runs/{id} | — | 200 FitRun，參數與精度 |
| GET /validation-runs/{id} | FINAL_TEST 依 access_class 分類政策 | 200 ValidationRun，指標／覆蓋率與證據雙軸 |
| GET /artifacts/{id} | access_class／lineage政策 | 200 Artifact metadata，資料來源與 hash |
| GET /artifacts/{id}/content | access_class／lineage政策 | 200 受控串流內容，禁止跳轉未授權物件 URI |

Upload URL 只可 PUT 指定暫存 key，不可讀／列 bucket；大小超限 413，格式不允許 415，checksum 不符 422 CHECKSUM_MISMATCH。v2 單檔暫定 50 MiB，容量正式門檻見 D-01。complete 重送不重建版本；未完成暫存 24 小時過期清理。CSV／JSON／Parquet 的支援與品質規則見 AX-09。

## 請求前置條件與冪等

所有 POST 需 Idempotency-Key（ASCII 1～128 字元），scope=(tenant,actor,method,canonical_path,key)，保留 24 小時。第一次原子保存 request_hash 與結果；相同 key 同內容回相同 HTTP status/body/resource_id，不能重扣費；同 key 不同 body 回 409 IDEMPOTENCY_CONFLICT。相同請求尚在處理回 409 REQUEST_IN_PROGRESS、Retry-After=1。24 小時後重新送視為新操作，但業務唯一約束仍防重複版本／終態動作；客戶端須先 GET 狀態。

validate、提交 SEARCH、cancel 額外要求 If-Control-Revision: <revision>；對應 GET 回 X-Control-Revision。缺前置條件 428 PRECONDITION_REQUIRED，版本不同 412 REVISION_CONFLICT。每次請求（含冪等重播）先重新確認當前身分與租戶分區；內容已不可讀時拒絕回放。相同key的已完成操作不重跑副作用或revision檢查，回原操作回應，該回應表示當時操作結果而非最新研究有效性；客戶端再GET權威snapshot顯示現況。首次執行的租戶、revision與狀態更新同一交易。

## 錯誤與認證

| HTTP | code | retryable／處理 |
|---|---|---|
| 400 | INVALID_JSON / INVALID_CURSOR | false，修正輸入 |
| 405 | METHOD_NOT_ALLOWED | false，改用該端點允許的方法 |
| 500 | INTERNAL_ERROR | false，不洩漏例外，依 request_id 查詢稽核／服務紀錄 |
| 401 / 403 | AUTH_REQUIRED / CSRF_FAILED | false，先完成認證 |
| 404 | NOT_FOUND | false，跨租戶或不存在資源同樣回 404 |
| 409 | INVALID_TRANSITION / RUN_ALREADY_TERMINAL / IDEMPOTENCY_CONFLICT / REQUEST_IN_PROGRESS / ARTIFACT_UNAVAILABLE / CHILD_RUN_NOT_CANCELLABLE / UPLOAD_OBJECT_CHANGED | 僅 REQUEST_IN_PROGRESS 可相同 key 重試 |
| 410 | EVENT_CURSOR_EXPIRED | false，GET snapshot 後從新游標接續 |
| 413 / 415 | UPLOAD_TOO_LARGE / UNSUPPORTED_MEDIA_TYPE | false |
| 422 | INVALID_SCHEMA / CHECKSUM_MISMATCH / DOMAIN_VIOLATION / AST_LIMIT_EXCEEDED / UNSUPPORTED_OPERATOR / UNIT_MISMATCH / UNKNOWN_SYMBOL / INSUFFICIENT_DATA / SEMANTIC_PROFILE_INCOMPLETE / EVALUATION_POLICY_INVALID / INVALID_RESEARCH_DOMAIN / SOURCE_COLUMN_CONFLICT / SOURCE_COLUMN_NOT_FOUND / SPLIT_DEPENDENCE_CONFLICT / UNIT_CONVERSION_INVALID | false，修正內容 |
| 428 / 412 | PRECONDITION_REQUIRED / REVISION_CONFLICT | false，重新讀取並確認差異 |
| 429 | QUOTA_EXCEEDED / RATE_LIMITED / RESEARCH_BUDGET_EXHAUSTED / RUN_BUDGET_EXHAUSTED / TENANT_ADMISSION_DENIED | 僅限流可依 Retry-After 重送；其餘需調整預算或租戶准入 |
| 503 | DEPENDENCY_UNAVAILABLE | true，有限退避重試且保留 key |

內部 worker 另有 STALE_ATTEMPT、ROOT_CANCELLED、TASK_TREE_MISMATCH、TEST_ALREADY_RESERVED、TEST_ALREADY_CONSUMED、CHECKPOINT_INCOMPATIBLE、DATASET_CONTAMINATION、FEATURE_DISABLED、DISPATCH_STAGE_VIOLATION、REFIT_POLICY_INVALID、BLIND_ELIGIBILITY_DENIED、EQUATION_DOMAIN_MISMATCH、EVALUATION_POLICY_MISMATCH、EXPOSURE_RECOVERY_BLOCKED；不可當成通用 500。所有錯誤包含 AX-48 envelope，unknown fields 拒絕；details 不洩漏租戶外資料與秘密。

## 兩種事件流與生命週期

Event schema_version="2.0"。共用欄位 event_id、event_type、tenant_id、stream_scope、stream_id、research_version_id（無則null）、run_id（研究事件可null）、sequence、occurred_at、trace_id、producer_version、payload。序號只在 (stream_scope,stream_id) 內單調；同一權威交易新增outbox及相應snapshot/cursor。投遞至少一次，event_id去重，不以跨stream抵達順序推因果。

| stream_scope／端點 | event_type | payload 必要欄位 |
|---|---|---|
| RUN／GET /runs/{id}/events | DatasetVersionAvailable | dataset_version_id、artifact_hash |
| RUN／同上 | RunQueued / RunStarted | status、attempt_id（queued可null）、generation |
| RUN／同上 | CandidateFound | candidate_id、equation_version_id、validation_status |
| RUN／同上 | ValidationFinished | validation_run_id、evidence_bundle_id、outcome_status |
| RUN／同上 | RunCancelRequested / RunCancelled / RunFinished | status、stop_reason、revision |
| RESEARCH／GET /research-versions/{id}/events | ResearchVersionReady | research_version_id、quality_report_id |
| RESEARCH／同上 | ResearchVersionStateChanged | status、revision |
| RESEARCH／同上 | SubmissionFrozen | submission_id、snapshot_hash |

RUN stream_id 必等於 run_id；RESEARCH stream_id 必等於 research_version_id。研究事件的 run_id 僅可作來源關聯，不能以該run的sequence或終態決定研究事件存活。RunFinished／RunCancelled後不可追加該RUN stream；研究狀態事件只追加RESEARCH stream。

SSE id 為 `<scope>:<stream_uuid>:<sequence>`，event=event_type、data=完整JSON；15秒comment heartbeat。Last-Event-ID需同scope/id，跨stream／未來序號400 INVALID_CURSOR；事件至少保留7天，游標過期410 EVENT_CURSOR_EXPIRED。未帶游標也回410，客戶端先取snapshot；snapshot的0游標允許空stream起始。

GET /runs/{id} 與 GET /research-versions/{id} 各回一致性snapshot/current_event_cursor：state與cursor須在相同DB一致性讀點取得。過期時先取snapshot再從該cursor補發；研究snapshot含bundle／submission／structure報告引用，能重建畫面。RESEARCH stream在任務完成後繼續存在，連線可由proxy定期中斷並正常重連。

研究版本進入終態後仍有研究狀態事件；客戶端訂閱研究stream即可更新畫面，不需要猜新run_id。schema及正反例見event-v2；舊ValidationCompleted等別名不再是合法事件。

## 章節驗收案例

以下為預定測試，狀態皆 NOT_RUN；實際證據依 AX-46 登錄。

| ID | 請求 | 預期 |
|---|---|---|
| AC-21-01 | 同 key 兩次合法 SEARCH，body 相同 | 同 run_id／202，只有一次預算預留 |
| AC-21-02 | 同 key 改 seed；或缺／錯 If-Control-Revision | 依序 409、428、412，無新副作用 |
| AC-21-03 | SSE 重送同序號後游標過期 | UI 去重；410 後 snapshot+補發無缺漏 |
| AC-21-04 | 租戶 A 帶 B 的 run_id、cursor 或 upload_id | 404，無內容與存在性洩漏 |

## 內部子任務與凍結

SEARCH 根協調器派送內部 FIT／VALIDATE run，皆引用同研究版本及root帳本。最終Evaluator只接受FrozenSubmission；公開端點不能任意提交final_test。EvidenceBundle與Artifact由可信服務產生。ResearchVersionReady／ResearchVersionStateChanged在RESEARCH stream持久化，來源run_id僅供追溯；DatasetVersionAvailable在INGEST run。根取消與遲到計量依AX-38，不把所有子工作視為同機程序。

帳號由服務端預先建立；瀏覽器認證介面在同源 /auth/login（GET 表單／CSRF；POST 驗證帳密並輪替 session）、/auth/logout（POST＋CSRF，使 session 失效），不屬 /api/v2 研究資源。禁止 GET 登出與透過 API URL 傳帳密；登入失敗回通用訊息並限流。正式 SSO／邀請／公網分享屬後續獨立契約，MVP 不暗示已支援。

Run 回 evidence_bundle_ids／child_run_ids，Candidate 回 fit_run_ids／validation_run_ids，讓前端可沿唯讀端點取得公式、參數、誤差與證據。Artifact registry 供報告／原始資料下載，artifact_uri 僅內部儲存位置，非公開可分享 URL；content endpoint 每次驗證租戶分區與 access_class 分類政策，QUARANTINED／DELETED 回 409 ARTIFACT_UNAVAILABLE。QUARANTINED 的歷史報告在UI保留metadata及隔離警示；MVP原內容下載回409 ARTIFACT_UNAVAILABLE。

## 新增流程驗收

| ID | 情境 | 預期 |
|---|---|---|
| AC-21-05 | 重新登入且無建立時回應 | 研究→版本→runs列表可找回工作，租戶分區與cursor均有效 |
| AC-21-06 | run已完成後再送研究狀態變更 | RUN不再追加；RESEARCH依序收到ResearchVersionReady／ResearchVersionStateChanged |
| AC-21-07 | 跨stream cursor或研究cursor過期 | 前者400，後者410→snapshot→補發，不漏最新狀態 |
| AC-21-08 | 重送已完成Idempotency-Key | 不回洩漏的舊快取內容、不重執行操作 |

## 控制版本與HTTP快取

X-Control-Revision／If-Control-Revision是v2明確定義的業務前置條件，值為revision十進位字串，適用狀態轉移及取消。它們不宣稱是HTTP representation ETag。GET可變snapshot回Cache-Control: no-store；heartbeat與成本計量可改內部／usage資料但不改control revision，客戶端不可用revision當整份回應的內容hash。歷史已凍結Artifact以sha256辨識內容。成本的遲到結算由GET run重讀顯示，不向已終態RUN stream追加事件。

## 快照還原與操作結果

ResearchVersion 必填 evidence_bundle_ids／frozen_submission_ids，以及可null的quality_report_id。由對應GET取得完整資源，品質報告透過Artifact metadata/content讀取；引用、研究狀態與current_event_cursor在同一一致性讀點讀出。新增證據更新投影與RESEARCH outbox同交易，游標過期後仍能從快照重建目前證據，不靠七天前事件內容。引用仍逐項重新檢查租戶分區；不因歷史引用直接放行內容。

Run.outcome_status為操作級研究結論；ValidationRun.outcome_status為單次評估結論。SEARCH根依AX-13／28彙整證據，不把某一子結果機械複製為研究結論；無可用驗證時為INSUFFICIENT_EVIDENCE。非研究判定操作、尚未形成結論或取消時為null。skipped_phases記錄被略過階段與原因；不得從phase跳躍猜測。

| ID | 情境 | 預期 |
|---|---|---|
| AC-21-09 | 研究事件已過保留期後重新登入 | snapshot引用→GET bundle／structure報告完整還原 |
| AC-21-10 | PROFILE品質不通過後重開 | quality_report_id可讀報告；無產物時明確null |

CreateResearchVersion.refit_policy省略／null表示禁用重擬合；提供時依AX-28預註冊並產生refit_policy_artifact_id。政策Artifact與研究版本同交易登記，不接受客戶端直接指定政策Artifact ID。

## 封存回應與定義域

ValidationRun.split_role=FINAL_TEST、含final證據的EvidenceBundle及其Artifact皆標記AX-26的access_class分類政策。GET Artifact metadata與content使用相同access_class及lineage裁決，不能只限制下載。所有列表／快照／SSE／冪等回放同樣檢查。OpenAPI在相應GET端點標記artifact-class-and-lineage-v1政策，實際服務端仍待實作。

CreateResearchVersion.domain為必填ResearchDomain，與DSL domain相同的有限有理上下界格式，MVP恰含一個輸入、名稱與semantic_profile一致；使用者必須確認，不從final資料自動推算。反向、空域、錯變數名回422 INVALID_RESEARCH_DOMAIN；資料或求值超出域回DOMAIN_VIOLATION。研究保存的domain不可變，修改另建ResearchVersion；預設建議、公式域及外插定義依AX-10。PROFILE TaskInput亦保存相同domain，SEARCH／FIT／VALIDATE由不可變研究版本解析並驗證相符。

| ID | 情境 | 預期 |
|---|---|---|
| AC-21-11 | 沿candidate／bundle／artifact引用尋找final內容 | 每個端點再查access_class分類政策，不能以間接引用繞過 |
| AC-21-12 | 建立研究缺domain、反向界或變數名不符 | 422；合法domain固定保存並由PROFILE／插件驗證 |

## v2.6 研究輸入與不足結束

CreateResearchVersion必填evaluation_policy；semantic_profile.inputs／target必填source_column。未知來源欄／同欄角色衝突回422 SOURCE_COLUMN_NOT_FOUND／SOURCE_COLUMN_CONFLICT，政策不合法回422 EVALUATION_POLICY_INVALID。UNSPECIFIED誤差模型與NONE比較方法可探索但不得形成SUPPORTED。PROFILE／SEARCH的可選run_budget僅限制root，不能重置ResearchVersion累計；研究／root超額各回429 RESEARCH_BUDGET_EXHAUSTED／RUN_BUDGET_EXHAUSTED，狀態及預留保持原子。

Run的diagnostic_artifact_ids供零候選／預算不足報告讀取，沿既有Artifact端點取用；SUCCEEDED不表示數學受支持。根outcome=INSUFFICIENT_EVIDENCE且無有效bundle時，版本維持DRAFT，不產生SUPPORTED結論。新政策／映射需新研究版本；跨版本重用final仍受曝光ledger限制。內部政策hash不一致回EVALUATION_POLICY_MISMATCH，恢復曝光資格未驗證回EXPOSURE_RECOVERY_BLOCKED，不能重試繞過。

| ID | 情境 | 預期 |
|---|---|---|
| AC-21-13 | 建立UTF-8欄位映射與完整evaluation_policy | 正確保存並可重開；修改需新版本 |
| AC-21-14 | 無有效bundle的root結束；或新root超研究預算 | 前者維持DRAFT且無SUPPORTED結論，後者429；皆無新預留副作用 |

## v2.7 完整導航契約

以下端點列入OpenAPI；路徑相對/api/v2，全部重新檢查tenant與資源邊界，列表沿既有cursor／limit契約。

| 方法與路徑 | 輸入／輸出 | 控制 |
|---|---|---|
| GET /datasets/{id}/runs | RunPage，僅該dataset的INGEST | 支援重新登入後尋回匯入工作；不可經此查研究任務 |

新增穩定錯誤：422 UNIT_CONVERSION_INVALID、SPLIT_DEPENDENCE_CONFLICT；409 UPLOAD_OBJECT_CHANGED；429 TENANT_ADMISSION_DENIED。上述皆retryable=false，修正設定／新版本後才重新操作，不能自動重試。曝光復原未通過仍沿原503閘門，不能混成新研究輸入錯誤。

## v2.8 可驗證研究軌跡

Run必填research_trace_artifact_ids，透過既有GET run、研究runs列表及GET Artifact metadata/content找回TraceChunk；列表逐項檢查租戶分區與access_class分類，SEALED_DETAIL chunk依分類政策回傳。trace追加不改control revision；snapshot與Artifact registry一致讀出，尚未產生chunk時為空。chunk payload使用research-learning-v1，API Run仍為2.0未部署草案修訂2.8，內部payload不是新增HTTP資源。

目前不新增高階job或多維HTTP端點；M4／M6／M7實作前須另交付匹配任務、預算／取消／恢復及新major契約。現行OpenAPI及六類TaskInput只描述已凍結首期介面，不允許將新kind塞進Run.type猜測執行。

## v2.9 結構報告導航

DatasetVersion.structure_preview_artifact_id及ResearchVersion.structure_assessment_artifact_id為可null的Artifact引用，分別由既有dataset版本列表／研究snapshot恢復；依AX-49，AVAILABLE／READY等完成狀態必有對應引用，依既有access_class分類政策回傳。沒有新增preflight或高階job端點。公開Run及Artifact仍是現行導航邊界，trace鏈按獨立可見stream驗證，不返回隱藏stream ID或hash。

本機 INGEST 的 GET /runs/{id} 另回 X-Usage-Status=NOT_STARTED／MEASURED_UPPER_BOUND／UNKNOWN。UNKNOWN 表示已開始的 attempt 失聯而無法確認用量，不得把零欄位解讀為免費執行；MEASURED_UPPER_BOUND 的 CPU／wall 為向上整秒、memory 為 process high-water 的保守和，非精確同時 RSS 或正式 SLO。此 header 不改 Run JSON，亦不代表完整 quota／budget gate 已驗收。

## 共用規則

版本、錯誤、證據與契約規則見 [AX-48 共用契約與文件治理](<../00-總覽/48-共用契約與文件治理.md>)；本章的專屬限制及驗收條件仍須同時滿足。
