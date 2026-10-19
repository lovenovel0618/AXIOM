# 21｜API與任務契約

> AXIOM v2.2 設計規格｜文件 ID AX-21｜狀態：待實作、待驗收｜2026-10-19

## 契約範圍與認證

MVP API 前綴 /api/v1，JSON 使用 UTF-8，傳輸使用 HTTPS（本機開發可 HTTP）。機器可讀端點、請求與回應見 [openapi-v1.json](<../contracts/openapi-v1.json>)。v1 瀏覽器採同源 session cookie 與 CSRF，服務帳號採限制 scope 的 bearer token；細節與角色矩陣見 AX-26。M4 以後的 /experiences、/models、/proofs 尚非 MVP API，未啟用時回 FEATURE_DISABLED，不能暗中啟用外部路由。

## 逐端點語意

所有 {id} 皆 UUID；列表回 items 與 next_cursor，limit 預設 50、上限 200，cursor 為不透明字串。排序固定 created_at、id，cursor 綁租戶與篩選，未知／過期回 INVALID_CURSOR。/datasets、/researches 預設依建立時間倒序；候選按已凍結 development rank 升序。

| Method / 路徑（省略前綴） | 輸入與權限 | 成功／副作用 |
|---|---|---|
| POST /datasets | name；researcher | 201 Dataset，尚無可用版本 |
| GET /datasets | cursor、limit；具讀取權 | 200 DatasetPage，不能枚舉其他租戶 |
| POST /datasets/{id}/uploads | filename、format、size_bytes、sha256；owner/editor | 201 UploadSession，回單次 signed PUT URL，15 分鐘有效 |
| POST /uploads/{id}/complete | checksum；owner/editor | 202 INGEST run；掃描、schema、hash 全過後才建立 DatasetVersion |
| GET /datasets/{id}/versions | cursor、limit；具讀取權 | 200 VersionPage，僅可引用 AVAILABLE 版本 |
| POST /researches | name；researcher | 201 Research 容器，與執行分離 |
| POST /researches/{id}/versions | dataset_version_id、semantic_profile、split_policy、budget、purpose；editor | 201 DRAFT ResearchVersion，內容固定，新修改另建版本 |
| GET /research-versions/{id} | reader | 200 ResearchVersion+ETag，取得狀態轉移前置版本 |
| GET /evidence-bundles/{id} | reader | 200 EvidenceBundle+ETag，取得撤銷前置版本 |
| POST /research-versions/{id}/validate | {}；editor | 202 PROFILE run，合法時版本 READY，否則 DRAFT+品質報告 |
| POST /research-versions/{id}/runs | type=SEARCH、seed；editor | 202 QUEUED run，須 READY；原子預留預算 |
| GET /runs/{id} | reader | 200 Run+ETag，包括 status、phase、attempt、stop_reason、成本與有效產物引用 |
| POST /runs/{id}/cancel | {}；editor | 202 CANCEL_REQUESTED 或已確認 CANCELLED；終態 409 |
| GET /runs/{id}/events | Last-Event-ID；reader | 200 text/event-stream；只輸出該 run 的授權事件 |
| GET /runs/{id}/candidates | cursor、limit；reader | 200 CandidatePage；未驗證候選明列 E0／P0 |
| GET /equation-versions/{id} | reader | 200 EquationVersion，DSL 與 hash 用於候選顯示 |
| GET /fit-runs/{id} | reader | 200 FitRun，參數與精度 |
| GET /validation-runs/{id} | reader | 200 ValidationRun，指標／覆蓋率與證據雙軸 |
| GET /published-artifacts/{id} | reader | 200 PublishedArtifact，附當前有效性由 EvidenceBundle 查詢 |
| GET /artifacts/{id} | reader | 200 Artifact metadata，資料來源與 hash |
| GET /artifacts/{id}/content | reader | 200 受控串流內容，禁止跳轉未授權物件 URI |
| POST /research-versions/{id}/reviews | decision、evidence_bundle_id、comment；獨立 reviewer | 201 ReviewDecision；核准且證據有效才發布 |
| POST /evidence-bundles/{id}/revoke | reason、counterexample_artifact_id；reviewer | 202 撤銷工作，權威讀取立刻排除，清理傳播見 AX-26 |

Upload URL 只可 PUT 指定暫存 key，不可讀／列 bucket；大小超限 413，格式不允許 415，checksum 不符 422 CHECKSUM_MISMATCH。v1 單檔暫定 50 MiB，容量正式門檻見 D-01。complete 重送不重建版本；未完成暫存 24 小時過期清理。CSV／JSON／Parquet 的支援與品質規則見 AX-09。

## 請求前置條件與冪等

所有 POST 需 Idempotency-Key（ASCII 1～128 字元），scope=(tenant,actor,method,canonical_path,key)，保留 24 小時。第一次原子保存 request_hash 與結果；相同 key 同內容回相同 HTTP status/body/resource_id，不能重扣費；同 key 不同 body 回 409 IDEMPOTENCY_CONFLICT。相同請求尚在處理回 409 REQUEST_IN_PROGRESS、Retry-After=1。24 小時後重新送視為新操作，但業務唯一約束仍防重複版本／終態動作；客戶端須先 GET 狀態。

validate、提交 SEARCH、cancel、review、revoke 額外要求 If-Match: "<revision>"；對應 GET 回 ETag。缺前置條件 428 PRECONDITION_REQUIRED，版本不同 412 REVISION_CONFLICT。重送已完成的相同 idempotency key 時先回既有結果，不再因目前 revision 改變而失敗。首次請求的授權及 revision 檢查與狀態更新同一交易。

## 錯誤與授權

| HTTP | code | retryable／處理 |
|---|---|---|
| 400 | INVALID_JSON / INVALID_CURSOR | false，修正輸入 |
| 401 / 403 | AUTH_REQUIRED / FORBIDDEN / CSRF_FAILED | false，先完成認證／權限 |
| 404 | NOT_FOUND | false，跨租戶或無可見權同樣回 404 |
| 409 | INVALID_TRANSITION / RUN_ALREADY_TERMINAL / IDEMPOTENCY_CONFLICT / REQUEST_IN_PROGRESS / ARTIFACT_UNAVAILABLE | 僅 REQUEST_IN_PROGRESS 可相同 key 重試 |
| 410 | EVENT_CURSOR_EXPIRED | false，GET snapshot 後從新游標接續 |
| 413 / 415 | UPLOAD_TOO_LARGE / UNSUPPORTED_MEDIA_TYPE | false |
| 422 | INVALID_SCHEMA / CHECKSUM_MISMATCH / DOMAIN_VIOLATION / AST_LIMIT_EXCEEDED / UNSUPPORTED_OPERATOR / UNIT_MISMATCH / UNKNOWN_SYMBOL / INSUFFICIENT_DATA / SEMANTIC_PROFILE_INCOMPLETE | false，修正內容 |
| 428 / 412 | PRECONDITION_REQUIRED / REVISION_CONFLICT | false，重新讀取並確認差異 |
| 429 | QUOTA_EXCEEDED / RATE_LIMITED | 限流可依 Retry-After 重送；總配額不足需調整預算 |
| 503 | DEPENDENCY_UNAVAILABLE | true，有限退避重試且保留 key |

內部 worker 另有 STALE_ATTEMPT、CHECKPOINT_INCOMPATIBLE、DATASET_CONTAMINATION、FEATURE_DISABLED；不可當成通用 500。所有錯誤包含 AX-48 envelope，unknown fields 拒絕；details 不洩漏租戶外資料與秘密。

## 事件目錄、投遞與 SSE

唯一事件名稱為 DatasetVersionAvailable、ResearchVersionReady、RunQueued、RunStarted、CandidateFound、ValidationFinished、RunCancelRequested、RunCancelled、RunFinished、ReviewRecorded、EvidenceRevoked。舊名稱 DatasetIngested／ValidationCompleted 等不再作 API 名稱。M4 之後新增事件需契約升版。

Event 必填 event_id(UUID)、schema_version="1.0"、event_type、tenant_id、research_version_id（無則 null）、run_id、sequence、occurred_at、trace_id、producer_version、payload。sequence 是同 run 持久化單調遞增整數；不得用跨 run 的抵達順序推斷因果。權威交易同時寫 outbox；投遞至少一次，消費者以 event_id 去重。

| event_type | payload 必要欄位 |
|---|---|
| DatasetVersionAvailable | dataset_version_id、artifact_hash |
| ResearchVersionReady | research_version_id、quality_report_id |
| RunQueued / RunStarted | status、attempt_id（queued 可 null）、generation |
| CandidateFound | candidate_id、equation_version_id、validation_status |
| ValidationFinished | validation_run_id、evidence_bundle_id、outcome_status |
| RunCancelRequested / RunCancelled / RunFinished | status、stop_reason、revision |
| ReviewRecorded | review_id、decision、evidence_bundle_id |
| EvidenceRevoked | evidence_bundle_id、revocation_id、reason_code |

SSE id 是該 run 的 sequence 十進位字串，event 是 event_type，data 是完整 Event JSON；15 秒送 comment heartbeat。Last-Event-ID 只接受同 run 有效序號，重連由 cursor 後補發；未來序號回 400 INVALID_CURSOR。事件至少保存 7 天；缺失／過期 cursor 回 410。GET /runs/{id} 回 current_event_cursor 與一致性 snapshot；410 後先取 snapshot 再從 cursor 接續。重複事件不重複更新 UI，頁面顯示最近同步時間。terminals 後送 final 事件再關串流；授權撤銷須停止長連線。

## 契約驗收

| ID | 請求 | 預期 |
|---|---|---|
| AC-21-01 | 同 key 兩次合法 SEARCH，body 相同 | 同 run_id／202，只有一次預算預留 |
| AC-21-02 | 同 key 改 seed；或缺／錯 If-Match | 依序 409、428、412，無新副作用 |
| AC-21-03 | SSE 重送同序號後游標過期 | UI 去重；410 後 snapshot+補發無缺漏 |
| AC-21-04 | 租戶 A 帶 B 的 run_id、cursor 或 upload_id | 404，無內容與存在性洩漏 |

## 內部子任務與事件歸屬

SEARCH 協調器以同版本凍結 manifest 建立內部 FIT／VALIDATE 詳細紀錄；v1 不另開允許客戶端任意提交 final_test 的端點。EvidenceBundle、ProofArtifact 與 PublishedArtifact 只由可信服務產生。ReviewRecorded 以所審核的最後 VALIDATE run 作事件歸屬；EvidenceRevoked 以 REVOKE run 歸屬；DatasetVersionAvailable 以 INGEST run 歸屬。ResearchVersionReady 以 PROFILE run 歸屬。重送業務動作仍須維持相同事件歸屬及唯一事件。

帳號由管理員預先建立；瀏覽器認證介面在同源 /auth/login（GET 表單／CSRF；POST 驗證帳密並輪替 session）、/auth/logout（POST＋CSRF，撤銷 session），不屬 /api/v1 研究資源。禁止 GET 登出與透過 API URL 傳帳密；登入失敗回通用訊息並限流。正式 SSO／邀請／公網分享屬後續獨立契約，MVP 不暗示已支援。

Run 回 evidence_bundle_ids／child_run_ids，Candidate 回 fit_run_ids／validation_run_ids，讓前端可沿唯讀端點取得公式、參數、誤差與證據。Artifact registry 供報告／原始資料下載，artifact_uri 僅內部儲存位置，非公開可分享 URL；content endpoint 每次驗證 ACL、敏感政策與撤銷，QUARANTINED／DELETED 回 409 ARTIFACT_UNAVAILABLE。已撤銷但允許保留的歷史報告只提供帶撤銷標記版本，不以舊有效報告繞過檢查。
