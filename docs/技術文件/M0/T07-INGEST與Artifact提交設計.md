# T07｜INGEST 與 Artifact 提交設計

日期：2026-10-20；owner／SELF_REVIEW：project-owner；承接c8de96a。先交設計，再實作／測試／檢測及提交。

## 本輪範圍

承接有界parser，把complete→真實QUEUED INGEST→專用Celery worker→原子DatasetVersion／Artifact提交接起來。T07的人工語意、ResearchVersion及已知公式整合仍待後續，不因此關閉M1。預設不啟用；需AXIOM_INGEST_ENABLED=1及完整AXIOM_IMPORT_LIMITS JSON，Compose另外開ingest profile。只供有權處理的本機公開／合成資料；不接受正式blind來源、不代表D-05政策核准。

## 交易及派送

complete沿現行session／CSRF／actor／Dataset access_class，鎖Upload並核對checksum、實際bytes、固定object version及期限。原子建立真實Run、TaskInput Artifact、ExecutionManifest／Budget快照、provenance、Upload→Run唯一binding，才把Upload標COMPLETED。completed的重送（含過期及24h後）重新查現行 access_class／checksum後回同一Run，不重新派生Run；不同request key不影響這項領域冪等性。

Run本身是持久待派送紀錄，relay對非control INGEST重送固定ingest queue；原T04 foundation worker不掛原檔、不執行業務INGEST。新增ingest profile worker，只聽ingest、concurrency=1、每處理一task更換pool child，掛原始volume唯讀。重複派送以現有Run／Attempt世代claim拒絕；本輪business max_attempts=1，失聯／逾期不自動重跑未知用量。

worker先取得lease，再在短交易查目前actor（含Django User.is_active）、Dataset access_class及upload固定版本，讀取最多50MiB已驗證bytes；釋鎖後執行有界parser。提交時依actor→dataset→upload→run順序重新檢查、重驗bytes／lease／epoch／deadline；刪除、隔離、掉包、舊attempt或取消都不能產生版本。成功與Attempt／Run狀態、事件、audit及binding.result在同一交易提交。parser／授權失敗只寫失敗code，不寫觀測值。

## 模型與產物

Catalog新增Artifact、DatasetVersion、IngestBinding。原生複合FK保護tenant／dataset／raw-object／artifact／Run；immutable trigger保護身分、內容、hash、snapshot和已提交result。DatasetVersion以(dataset,sha256)唯一；持dataset鎖去重，兩個成功Run可以指同一版本。若相同bytes被宣告成不同格式，拒絕格式衝突，不改原版本。

Artifact本機採DB immutable JSON或固定StoredObject二選一，公開artifact_uri是受控 proxy 路徑。TaskInput與原始Artifact為SEALED_DETAIL，當期HTTP一律404；只有可信產生的METADATA_ONLY預覽為PROJECT。一般自有原始資料採保守封存策略，不把來源直接交Solver；正式blind授權尚未啟用。

預覽content符合StructureAssessment，periodicity／time_basis皆UNKNOWN、fit_rows_hash／research_version_id／intrinsic_dimension_estimate皆null，不推論時間、座標或內在維度。原schema沒有欄名／型別／列數的承載欄位，本輪以向後相容的可選source_metadata補齊；實作的METADATA_ONLY報告必填它，舊fixture仍可驗證。observation／representation_dimension只記來源欄數，不宣稱座標或內在維度。

GET datasets/{id}/versions、runs/{id}、artifacts/{id}及artifacts/{id}/content沿現行 access_class 政策；Artifact內容為attachment JSON、nosniff及no-store，重算SHA／size，不redirect至儲存位置。沒有一般原檔下載、公開研究或正式封存入口。

## 身分、資源與失敗界線

manifest保存實際Python／平台／Polars、requirements.lock digest、執行代碼SHA與parser完整config；INGEST尚無SemanticProfile，semantic_profile_hash以canonical null的hash表示「不適用」，不用全零假hash。manifest.input_hash排除TaskInput.execution_manifest_id自身；舊t04-control-only合成snapshot保留歷史full-task hash相容，新業務不採用。source_policy只記當期本機限制，不是來源合法性或D-05核驗收據。固定seed=0不代表硬體bitwise重現。

保留parser的1GiB address-space、CPU及wall限制；Run預算配置為parser秒數+固定協調餘量、2GiB memory上限，INGEST不分配GPU／token／candidate。CPU／wall向上取整秒；memory用父／child process high-water的保守和（非精確同時RSS），保留metering說明。不重置已完成用量；失聯worker的精確用量未知，Run失敗且不重試，不以零使用量宣稱執行免費。這不是全域quota、cgroup RSS或正式AX-25／SLO驗收。

每次claim持60秒lease，parser最多30秒；讀檔若卡住或worker失聯，coordinator依租約／deadline拒絕晚到提交。原T04控制probe仍不能冒充業務成功。取消後只由持有原attempt且已回收parser的handler確認停止；對失聯程序不能假裝已停止，當期不開business cancel HTTP。

## 驗證與回退

真PG測空庫migration、複合FK、SQL不可變、complete並行／永久冪等、去重、交易失敗回滾、刪除或隔離／停用、source掉包、舊世代／deadline、parser失敗、metadata無labels、raw封存拒絕與重新查 access_class。真HTTP＋relay＋ingest worker測三格式到SUCCEEDED及Artifact內容；舊控制／上傳／數學／parser全面回歸，strict Pyright、Sonar及CI須通過。

預設gate關閉時仍503，舊既有tests沿原行為。啟用需顯式配置limits，關閉只停止新complete／派送，已有Run不可當作從未存在；重新啟用依lease恢復裁決。回退先停ingest／relay及web並備份DB與原物件，逆序回退catalog新表／guards與runtime control flag限制；存在業務Run時不能直接恢復control_only=true約束，須保留資料或另作具名遷移，不宣稱無損降版。
