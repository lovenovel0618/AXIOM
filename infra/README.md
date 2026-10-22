# 本機開發環境（T04）

目前只供本人在 loopback 使用，已有本機 session 認證與資料集／上傳切片，完整研究 API 尚未完成。設計／驗收界線見 [T04 技術文件](<../docs/技術文件/M0/T04-產品工程骨架.md>)。Compose 提供 PostgreSQL、Redis、一次性 migration、web、worker、relay、Vue；T05 已提供版本化本機物件與租戶分區；MinIO／S3 尚未實作。

## 啟動

需要 Docker Engine／Compose v2。從倉庫根目錄執行：

```sh
cp .env.example .env
python3 -c 'import secrets; print(secrets.token_urlsafe(60))'
```

把產生的值填入 `.env` 的 AXIOM_SECRET_KEY；另產生不同亂數填入 AXIOM_DB_PASSWORD，勿重用正式密鑰。`.env` 已忽略，可 `chmod 600 .env`。若埠被占用，在 `.env` 改 AXIOM_WEB_PORT／AXIOM_FRONTEND_PORT；預設 18000／15173。

```sh
docker compose up --build -d --wait --wait-timeout 120
curl --fail http://127.0.0.1:18000/health/ready/
curl --fail http://127.0.0.1:15173/health/ready/
docker compose run --rm web python manage.py probe_smoke
docker compose run --rm web python manage.py runtime_smoke
```

開啟 <http://127.0.0.1:15173>；前端 ready 經 Vite 代理回 web。ready 檢查資料表及 Redis；probe_smoke 必須由常駐 relay 首次派送、worker 完成後再故意重播兩次訊息，完成計數仍為一。沒有 worker／relay 時 smoke 會逾時失敗。

## 測試與代碼檢測

```sh
docker compose run --rm web python manage.py test foundation.tests runtime.tests catalog.tests -v 2
docker compose run --rm web python manage.py makemigrations --check --dry-run
docker compose run --rm frontend sh -c 'npm run typecheck && npm test && npm run build'
```

Python 測試使用實際 PostgreSQL 的 `test_axiom`，需要開發帳號有建立測試資料庫權限；只在這組本機專用資料庫執行。不要把 Compose 指向正式資料庫。依賴版本、hash 與映像 digest 由 T02 沿用；backend runtime lock 引用 T02 runtime lock 並加入 offline schema 驗證器；dev lock 引用 backend runtime lock 及文件 dev requirements，再加入 Django／Celery／Redis 型別套件，CI 安裝時校驗 hash。

本機編輯器與根目錄 Pyright 共用 `.venv-backend`（VS Code 已提供 defaultInterpreterPath，既有手動選取的解譯器需切換一次）：

```sh
uv venv --python 3.13 .venv-backend
uv pip sync --python .venv-backend/bin/python --require-hashes backend/requirements-dev.lock
.venv-backend/bin/pyright
.venv-backend/bin/python -m unittest discover -s tests -v
.venv-backend/bin/python docs/企劃案/tools/check_docs.py
```

前端可使用容器中的型別檢查與測試；需要編輯器本機解析 Vue 型別時，以 Node 24.22.0 在 frontend 執行 `npm ci --ignore-scripts`，不更動系統預設 Node。

## 故障與保留資料

```sh
docker compose logs --tail 100 web worker relay
docker compose stop redis
# ready 應為 503；live 仍為 200。未完成紀錄不刪除。
docker compose start redis
# ready 恢復後重新執行 probe_smoke。
docker compose run --rm web python manage.py migrate --noinput
docker compose down
```

一般 `down` 保留資料。`down --volumes` 會刪除本 Compose 專案資料，只能用於確定可丟棄的測試環境。變更既有 volume 的 DB 密碼時需另做資料庫帳號密碼更新，不能只改 .env。測試可用 `-p axiom-t04-check` 建獨立專案，結束後只清除此專案。

private 網路不提供外連；只有 web／frontend 額外接 edge bridge 以提供 loopback 入口。edge 不等於正式 Solver 出站沙箱；web 開發程序仍具有此 bridge 的外連能力。worker 非 root、只聽 foundation queue，尚未達到正式任務權限隔離。正式部署、TLS、備份恢復、SLO 與 WSL2 仍待驗收。

## Run／Attempt 控制核心

`runtime_smoke` 透過同一常駐 relay／worker 跑合成 INGEST 根控制流程，最後 CANCELLED，明確回 business_ingest_status=NOT_RUN。它不讀 upload，不產 DatasetVersion；只有控制基線，不提供 HTTP API。輸入與政策快照為 DB immutable，Attempt 保留重試歷史；根期限與 queue timeout 由 DB 時間及協調器裁決。技術設計見 [Run／Attempt 控制核心](<../docs/技術文件/M0/T04-Run與Attempt控制核心.md>)。

ready 另確認 foundation、runtime、catalog與session及新INGEST guards migrations已套用。T04 控制函式仍是可信服務介面，不公開成 Run API；T05 資料集／上傳 API 已另接真實 session 與固定租戶分區。控制 worker 與未來實際 INGEST handler 分開，本輪 DB 約束禁止將 control_only 直接關閉。

## 帳號與上傳操作（T05）

於本機開發環境預先建立帳號，互動輸入至少12字元密碼，不把密碼放命令參數或 shell history：

```sh
docker compose exec web python manage.py provision_account dino local
```

每帳號固定一租戶；不要用請求 header 選租戶。命令輸出 actor／tenant UUID，不輸出密碼。後續同租戶帳號使用相同 tenant 名稱；需要不同行政租戶時使用不同名稱。帳號管理是本機受信任管理操作，沒有遠端邀請／註冊／公開分享。

資料庫重建（含 `down --volumes`）後為空，`migrate` 服務會在遷移完成後接著執行 `bootstrap_account`：讀 `AXIOM_BOOTSTRAP_USER`／`AXIOM_BOOTSTRAP_PASSWORD`（選配 `AXIOM_BOOTSTRAP_TENANT`，預設 `local`）建立 User＋租戶＋Account。命令冪等：帳號已存在即不改密碼、不重建，只有 Django user 缺 catalog account 時補建（輸出 `status=CREATED`／`REPAIRED`／`EXISTS`）。未設 `AXIOM_BOOTSTRAP_USER` 或值為空白時輸出 `status=SKIPPED` 且不寫入任何資料，因此 CI 與未配置環境不受影響。密碼不足 12 字元即非零退出（Fail-Closed），migrate 失敗時 web 不會啟動。

開啟 <http://127.0.0.1:15173/auth/login> 或後端18000的同一路徑。GET表單取得 axiom_csrf，POST帳密成功回status=ok並輪替 axiom_session；cookie名與其他 localhost 專案分開。/auth/logout只可POST＋X-CSRFToken。後續請求需目前session及CSRF header；Idempotency-Key為研究資源POST的必填header。

| 入口 | 目前行為 |
|---|---|
| GET／POST /api/v2/datasets | 依租戶分頁清單／建立資料集；POST body={name} |
| POST /api/v2/datasets/{id}/uploads | body={filename,format,size_bytes,sha256}；CSV／JSON／PARQUET、最高50MiB |
| UploadSession.put_url | 只可PUT原bytes，攜帶required_headers及session／CSRF；簽章不放URL query |
| POST /api/v2/uploads/{id}/complete | 驗現行租戶歸屬、checksum與固定版本；預設503，明確啟用後依下節建立真正Run |

前台已提供可用 MVP（`frontend/src/views/DatasetsView.vue`）：於 <http://127.0.0.1:15173/datasets> 登入後建立資料集、以檔案選擇器上傳 CSV／JSON／PARQUET 並查看版本列表。前端自行以 `crypto.subtle` 計算 SHA-256，將 `put_url` 轉為相對路徑沿用同源 proxy，並在每個 POST／PUT 帶 `X-CSRFToken`。complete 回503時畫面顯示「匯入功能可能尚未啟用」，不以假資料填充版本；版本由非同步 worker 產生，完成後按「重新載入」即可看到。

上傳後的任務可由「查看任務」進入 <http://127.0.0.1:15173/runs/{id}>（`RunView.vue`）：顯示後端 Run 公開投影、以 `Last-Event-ID` 每批續接最多 100 筆事件直到終態，並對 PROFILE 任務提供取消（帶現行 `revision` 作 `If-Control-Revision` 與 `Idempotency-Key`）；非 PROFILE 任務畫面明示後端只回 503，不假裝支援。產物連結走 <http://127.0.0.1:15173/artifacts/{id}>（`ArtifactView.vue`）；後端只對存取等級 PROJECT 的產物提供 metadata 與內容，版本表格裡的原始 bytes 屬非 PROJECT，因此不提供連結。

研究工作台在 <http://127.0.0.1:15173/researches>（`ResearchView.vue`／`ResearchVersionForm.vue`）：建立研究容器後，表單由所選版本的結構預覽（`GET /api/v2/artifacts/{id}/content`）帶入欄名與列數，再由使用者指定輸入／目標來源欄位、七維單位與換算、值域、固定 60／20／20 依列序 EXPLICIT 切分與評估政策；送出前顯示完整請求 JSON，卡片與 `lib/semantics.ts` 只重述文件化規則，後端仍為唯一權威。版本為不可變 DRAFT；「觸發 PROFILE 驗證」會先重讀版本取得現行 `revision`，再以 `If-Control-Revision` 與 `Idempotency-Key` 呼叫 validate，成功後版本任務列表連回 RunView。後端 `AXIOM_PROFILE_ENABLED` 關閉時回 503，畫面明示未啟用；時間序、群組依賴與 refit 後端未實作，因此表單一律不宣告。

Dataset／Upload建立回應可依相同key與payload重讀；不同payload回409。逾期簽章需新session，不能藉重播延長。列表cursor綁actor／租戶並重新查現行歸屬。讀取一律限同租戶，Research 與其版本另限 owner；系統已無角色或逐筆授權，其他帳號即使同租戶也讀不到不屬於自己的資源。

預設配置只有web掛載object-data；foundation worker、frontend沒有原始物件volume。明確啟用ingest profile時另給專用ingest worker唯讀掛載。原始filename只作metadata，實際檔名由UUID產生。檔案固定版本且每次驗SHA／大小；沒有匿名下載、目錄列表或靜態原檔；受租戶與 access_class 限制的 metadata Artifact API見T07段落，原檔仍不可經普通API下載。一般down保留DB和物件volume，down --volumes同時刪除，勿用於有保留需求的環境。這是local-versioned-v1，不是S3／MinIO驗收。

以下smoke會建立隔離的隨機合成帳號、資料集及小檔，只能在可丟棄的本機／CI環境執行，不對正式資料庫使用：

```sh
docker compose exec -T web python manage.py catalog_smoke
docker compose exec -T web python manage.py catalog_smoke --frontend
```

兩者均經真實HTTP登入、建資料集、PUT、查固定版本、測另一租戶，最後 business_ingest_status=NOT_RUN。--frontend另外走Vite同源代理（僅額外允許Compose內部frontend hostname，不使用萬用Host allowlist）。parser／DatasetVersion及真正Run提交已由下節的明確啟用流程接入；掃描、總配額、GC／備份及公網政策仍待後續，不以檔案傳輸通過宣稱全部安全政策已驗收。


## 有界結構預覽（T07前置切片）

Linux容器可針對同租戶且未過期的原始upload執行預覽，五項limits必填：

```sh
docker compose exec -T web python manage.py ingest_preview ACTOR_UUID UPLOAD_UUID --max-rows 10000 --max-columns 32 --max-cell-utf8-bytes 65536 --max-decoded-bytes 8388608 --max-parse-seconds 10
```

重新查現行actor／tenant／Dataset歸屬，核對固定版本SHA後，清除繼承環境並交獨立Python程序解析。CSV／JSON／Parquet皆只回欄名、格式型別及列數，沒有樣本或標籤統計。程式不猜單位／特徵／時間語意。原始row序不改、空值不補、問題列不靜默丟棄。這是受信任本機CLI，不可把actor UUID當遠端登入憑證。

子程序有1GiB address-space、CPU、wall deadline及輸出限制；同UID並非檔案系統／網路沙箱，不能用來跑插件。只有Linux實測，宿主macOS會拒絕此入口。原檔不可變，temporary copy在正常／解析失敗時清除；父程序crash遺留、總配額與GC仍待後續。詳細限制見[技術設計](<../docs/技術文件/M0/T07-有界匯入解析設計.md>)。

可丟棄環境另執行 `docker compose exec -T web python manage.py ingest_preview_smoke`，會經真實HTTP建立三格式合成上傳再預覽。這個前置工具本身不呼叫complete或建立版本；真正Run／Artifact依下一節明確啟用，研究版本由下節草稿流程接入。


## 真正 INGEST 與版本／Artifact（T07第二切片）

預設gate關閉，complete仍503。以下僅用於有權使用的本機公開／合成資料；五項limits全部必填，沒有正式D-01容量或D-05接收核准聲明：

```sh
AXIOM_INGEST_ENABLED=1 AXIOM_IMPORT_LIMITS='{"max_rows":10000,"max_columns":32,"max_cell_utf8_bytes":65536,"max_decoded_bytes":8388608,"max_parse_seconds":10}' docker compose --profile ingest up --build -d --wait --wait-timeout 120
```

要持續使用同一設定可放入既有未追蹤.env；不要將秘密或個人資料提交。後續重建需沿用啟用設定。新增ingest worker只聽ingest queue、concurrency=1、每個task重啟pool child，raw volume唯讀；foundation worker／frontend仍無原始volume。relay持久重送，lease拒絕重複／晚到提交；每Run只一個business attempt，失聯不自動重跑未知用量。

啟用後complete回202 Run；同一upload永久指同一Run，已COMPLETED即使過期也回同一ID，但重查現行租戶歸屬及checksum。成功才提交DatasetVersion與StructureAssessment metadata Artifact；同dataset／SHA去重。失敗要檢查診斷並另開upload／Run，不重置原Run。新增讀取入口：

- GET /api/v2/datasets/{id}/versions：同Dataset租戶範圍的游標清單。
- GET /api/v2/runs/{id}：公開Run、X-Control-Revision及X-Usage-Status。
- GET /api/v2/artifacts/{id}、/content：現行租戶歸屬及class檢查、JSON attachment／no-store／nosniff。

原始與TaskInput Artifact當期一律SEALED_DETAIL且HTTP回404；只有純結構預覽與不含原值的錯誤碼診斷為PROJECT。UNKNOWN用量不能當零成本；CPU／wall向上取整，memory為process high-water保守和，非精確同時RSS。這不是cgroup／quota／公網／正式blind驗收。

可丟棄環境可執行 `docker compose exec -T web python manage.py business_ingest_smoke`，會建立三格式合成資料，實際等待relay／worker並讀metadata、測去重／非法資料。停止新匯入時先停ingest worker，設定AXIOM_INGEST_ENABLED=0並重建web／relay；既有queued Run依期限裁決，不刪除或改成control probe。

metadata中的source_metadata只含欄名／格式型別／row_count，不猜語意、不取labels統計；人工語意與 ResearchVersion 草稿依下節操作；PROFILE 依第五切片明確啟用。執行環境／hash、遷移與限制見[技術設計](<../docs/技術文件/M0/T07-INGEST與Artifact提交設計.md>)。


## 人工語意與研究草稿（T07第三切片）

完成前述真實 INGEST 後，已登入且為資源 owner 的帳號可呼叫現行 v2 API；前台提供研究頁表單（見上節），也可用同源 HTTP client。POST 皆帶 session、CSRF 及 Idempotency-Key：

- POST／GET /api/v2/researches，GET /api/v2/researches/{id}：建立、分頁及重開 owner 私有研究，POST body 為 {"name":"研究名稱"}。
- POST／GET /api/v2/researches/{id}/versions：提交 CreateResearchVersion 或查目前可讀草稿列表。
- GET /api/v2/research-versions/{id}：重開固定快照。修改設定需建立新版本，沒有 PATCH。
- POST /api/v2/research-versions/{id}/validate：預設通過租戶與 owner 驗證後回 503；明確啟用見第五切片。

版本請求必須提供 dataset_version_id、semantic_profile、budget、purpose、observation_split、domain、evaluation_policy，完整形狀沿企劃案 contracts/openapi-v2.json。可執行的合成範例見 backend/catalog/management/commands/research_draft_smoke.py 的 configuration。原始欄名精確比對，單位比例／偏移及誤差界以十進位字串確認，domain 使用已約分的有理數。domain／解析度／界限以 canonical SI 計；本步只固定宣告，尚未讀值或執行數值轉換。

目前支援無時間／群組依賴的 EXPLICIT 或 axiom-iid-sha256-v1 IID_ROWS，必須完整分配每列且不交疊；IID 依 seed 重算 60/20/20（取整邊界），不得自行偽稱隨機切分。TIME_ORDERED／GROUPED_ROWS／refit 依賴仍未實作，合法但尚未支援者回 503；互相矛盾的設定回 422。POST body 上限仍為 64 KiB，因此大型列集合不能在此階段提交；後續需另設版本化有界切分入口，不能放大限制後直接對外開放。

研究僅 owner 可見且須為同租戶。版本及其 Dataset 皆須同租戶並屬本人；建立與冪等重送同樣限 owner。他人或跨租戶一律 404，版本清單只列本人研究。Research 容器本身屬 owner。

新草稿為 DRAFT／revision=0，尚無品質結果或 fit 結構報告；PROFILE 執行後投影見第五切片。sealed_final_test=true 是禁止一般讀取最終原始資料的政策；sealed_test_id 為 null，不代表正式盲測或曝光 ledger 已登記。普通 raw Artifact 仍一律 404，沒有輸出觀測值、Solver 投影、最終評估或發布。研究額度與零起始帳本於同一交易建立，PROFILE 正式用量依第五切片累計。

啟用 ingest profile 的可丟棄環境可執行：

```sh
docker compose exec -T web python manage.py research_draft_smoke
```

它會經真實 HTTP 上傳含中文欄名的合成資料，等待 queue／worker 成功，確認語意與 cm→m 宣告、建立及重開 DRAFT、重送同 key、驗證 PROFILE 503。它不驗證物理單位宣告的真實性，也不宣稱資料品質或研究結論通過。

升級需先排空舊程序，再執行 catalog 0005／0006 migration 並重新啟動同一版本的 web／worker／relay；readiness 要求 0006。新增表不修改既有版本內容。當期 Research／ResearchVersion 整列不可變，後續狀態機需專屬 migration。若要降級，先停寫並備份，將相關草稿與 provenance／冪等關係納入恢復；直接 reverse 到 0004 會移除新增研究表，不能當無損回退。


## 研究預檢與已知公式（T07第四切片）

既有 DRAFT 可由受信任本機 CLI 檢查：

```sh
docker compose exec -T web python manage.py research_inspect ACTOR_UUID RESEARCH_VERSION_UUID --max-rows 100 --max-columns 8 --max-cell-utf8-bytes 4096 --max-decoded-bytes 65536 --max-parse-seconds 10
```

可另加 `--dsl-file /tmp/known-formula.json --parameters '{"a":"2","b":"1"}'`；檔案路徑位於容器內，沒有任意程式／shell 執行。DSL 形狀沿既有 dsl-v1 schema；模型變數、七維單位、輸出量綱及 domain 必須完全對應研究，參數是固定十進位字串且不得缺漏或多出。模型不做擬合或搜尋，請提供已固定的已知公式。

只接受當期支援的 IID／EXPLICIT DRAFT、owner 身分與目前 Dataset 歸屬，User／Account 必須啟用。actor UUID 僅供本機可信操作，不是 HTTP 認證。4096 列為此預檢硬上限，ImportLimits 可再縮小。各格式重讀不可變 raw、校驗 SHA 及固定 metadata，先切分後轉 canonical SI，不補值、不丟列；只有 fit 統計與 fit／development 模型評分。任一 selected input／target 不合法或不在域內，回 quality=BLOCKED、通用碼，統計／評分均 null，沒有 final 列號、原值或分區錯誤計數。

CSV／JSON 十進位觀測以精確值轉換；Parquet float 保留二進位原值。canonical 值再轉 float64（53 bits），溢位、非零下溢及域邊界捨入越界皆阻擋，不放寬有理邊界。fit 的 unique_x 指實際 float64 輸入的不同值數；target min/max/mean/IQR 為轉換後精確有理數字串。模型錯誤列保留在 selected_count／failed_count，coverage 降低且 MAE／RMSE 為 null，不能用成功子集冒充完整通過。

結果與設定／模型／參數、研究快照、source／environment hash 保存於私有不可變 ResearchInspection 表。相同環境／設定重送回同記錄，仍重新驗租戶與 owner、驗 raw；執行後 owner 變更、source 掉包、environment 改變都不能提交。並行相同設定可能重複做有界計算，但唯一鍵只保存一筆；這不構成 exactly-once 計算或累計成本帳本。measured_execution_usage 為當次 CLI 子程序與父程序執行期間的 CPU／wall 上取整及 process high-water 保守和，不含前置 source I/O、compiler 與 DB 提交；cache 回既有實測，不表示重新執行耗用零成本。

沒有新增普通 HTTP 報告入口或 Artifact，避免繞過 owner 私有研究。CLI 輸出不是完整 PROFILE Run／QualityReport／FIT_ONLY StructureAssessment，不更新 DRAFT、quality_report_id 或研究任務用量。本 CLI 不更動正式帳本；另啟用第五切片後可經 validate 建立 PROFILE／報告及事件，正式封存仍待後續。固定 worker 只有資源限制，尚非多租戶 FS／網路 sandbox，不用於未核准的敏感或正式 blind 來源。

可丟棄且已啟用 ingest profile 的環境可執行：

```sh
docker compose exec -T web python manage.py research_inspection_smoke
```

它會走真 HTTP 建立三格式合成上傳及研究，執行本機 CLI，獨立核對 y=2x+1 經比例轉換後在 fit／development 的 coverage=1、MAE／RMSE=0，另測品質遮罩與快取重送。測試仍不是正式 blind 或產品驗收。

升級需套 catalog 0007／0008 並重建同版本程序，readiness 要求 0008。新表經同租戶複合 FK、研究／來源快照 guard 及 UPDATE／DELETE 阻擋保護。回退先停寫、備份；reverse 移除 Inspection 表會失去本批記錄，不能當無損回退。


## 研究帳本與PROFILE任務（T07第五切片）

先完成 INGEST 及人工語意草稿；PROFILE 預設關閉。僅在可丟棄的本機公開／合成資料環境明確啟用，兩組五項 limits 都需完整提供：

```sh
AXIOM_INGEST_ENABLED=1 AXIOM_IMPORT_LIMITS='{"max_rows":100,"max_columns":8,"max_cell_utf8_bytes":4096,"max_decoded_bytes":65536,"max_parse_seconds":10}' AXIOM_PROFILE_ENABLED=1 AXIOM_PROFILE_LIMITS='{"max_rows":100,"max_columns":8,"max_cell_utf8_bytes":4096,"max_decoded_bytes":65536,"max_parse_seconds":10}' docker compose --profile ingest --profile profile up --build -d --wait --wait-timeout 120
```

PROFILE 專用 worker 只聽 profile queue，concurrency=1、每 task 重建 child；raw volume 唯讀，container memory=2GiB、CPU=1、pids=64。每 root 必須預留至少 2GiB memory、parser deadline+3 秒 CPU、deadline+10 秒 wall；CPU／wall 限額最高 300 秒。省略 run_budget 時依剩餘額度與固定容量計算，研究餘額不足回 429，不建立半份任務。這是本機固定容量政策，不是正式 D-01 配額或多租戶 sandbox。

已登入且為研究 owner 的帳號：

1. GET /api/v2/research-versions/{id} 取得 revision／X-Control-Revision。
2. POST /api/v2/research-versions/{id}/validate，body 為 `{}` 或 `{"run_budget":完整BudgetLimit}`，帶 session／CSRF、Idempotency-Key 及 If-Control-Revision。成功回 202 原始 Run；同 key 重送回同一操作回應，另以 GET Run 查最新狀態。缺 revision 回 428，過時回 412。
3. GET /api/v2/research-versions/{id}/runs 可在重開後找回 PROFILE；limit 1～200、簽章 cursor 15 分鐘，綁 actor／tenant／研究版本。GET /api/v2/runs/{id} 取得最新 revision 與 X-Usage-Status。
4. GET /api/v2/runs/{id}/events、/api/v2/research-versions/{id}/events 為有界 SSE 批次，每次最多 100 個事件並關閉；以 Last-Event-ID 續接，空批次 keepalive，沒有 query 篩選。每次重連重新驗權，非持續連線。研究用量變動不增加 control revision；需重讀版本取得帳本投影。
5. POST /api/v2/runs/{id}/cancel，body `{}`，帶該 Run 的 If-Control-Revision、Idempotency-Key／CSRF。排隊中可確認未啟動而立即 CANCELLED；已啟動須等固定 child 結束／回收後確認，不宣稱即時中斷 SLO。

每個研究同時只一個 PROFILE。品質成功產生 PROJECT QualityReport 與 FIT_ONLY StructureAssessment，僅 fit 統計，結構／週期可為 UNKNOWN；任一分區資料品質不合格只回遮罩 BLOCKED、統計 null、不建立結構報告。一般 Artifact 存取仍驗 owner 與目前 Dataset 歸屬；raw／TaskInput 仍 404。品質通過後研究仍 DRAFT，報告 readiness=BLOCKED／SEALED_TEST_NOT_REGISTERED；沒有正式封存、曝光 ledger、SEARCH 或最終評估。

研究帳本跨 root 累計 CPU／GPU／token／wall／candidate，root 與研究帳本由同一不可變 receipt 增量更新；記憶體以 max peak 和 active 預留分開計算。重送不重扣，舊序號不覆蓋新值，真正超支保留實際量並阻擋新 root。失聯且已開始的預留標 UNCERTAIN、不當成零成本釋放，X-Usage-Status=UNKNOWN；只有原 attempt owning handler 確認 child 停止後可遲到結算，終態 Run 不因此補事件。不得手改帳本或用新 root 洗掉未知成本。

CPU／wall 向上取整、RSS 為 process high-water 保守和；量測涵蓋 owning handler 的主要執行區間及子程序，wall 至提交結算前，未含最後 DB commit／broker／跨程序基礎設施成本。不是精確費用帳單或完整租戶配額。可信 CLI Inspection 歷史成本保留原記錄，不追溯冒充已扣正式研究帳本；正式 PROFILE 執行中拒絕本機預檢。

```sh
docker compose exec -T web python manage.py profile_smoke
```

此示範經真 HTTP／INGEST／DRAFT／PROFILE queue，驗三格式、跨 root 累計、品質遮罩、餘額拒絕與事件續接。僅在可丟棄資料庫執行。停止新 PROFILE 時先停止 profile worker，將 AXIOM_PROFILE_ENABLED=0 並重建 web／relay；排隊及失聯任務依持久狀態恢復，不刪帳本。升級須排空程序、備份並套 catalog 0009／0010、runtime 0005，再啟動同版服務；readiness 驗這些 migration。已有 PROFILE root 後不可直接 reverse 至 INGEST-only guards。設計與限制見 [任務設計](<../docs/技術文件/M0/T07-研究帳本與PROFILE任務設計.md>)。


## 開發服務保留與型別註解規範

預設專案為 axiom-dev；提供使用者操作的服務完成工作後保留運行與資料 volume，不使用 down --volumes 清理。只有明確命名的可丟棄測試專案可以清理。`docker compose ps`、`curl --fail http://127.0.0.1:18000/health/ready/` 與 `curl --fail http://127.0.0.1:15173/health/ready/` 必須實際成功。前端已有可用 MVP（登入、建立資料集、上傳檔案、版本列表、研究工作台語意確認與 PROFILE 觸發）；候選比較與證據檢視仍屬後續里程碑，健康檢查成功不表示所有企劃功能已完成。

要讓重建後仍啟用本機 INGEST／PROFILE，將上述四個 AXIOM_INGEST_ENABLED／AXIOM_IMPORT_LIMITS／AXIOM_PROFILE_ENABLED／AXIOM_PROFILE_LIMITS 寫入既有未追蹤 .env，另設 `COMPOSE_PROFILES=ingest,profile`，即可用一般 `docker compose up --build -d --wait` 同時啟動兩個 worker。不要輸出或提交 .env。詳細型別邊界與中文註解要求見 [本輪規範](<../docs/技術文件/M0/T07-服務常駐與型別註解規範.md>)；本機及 CI 皆執行 `python tools/typing_policy.py` 與 Pyright strict，既有 Any 額度不會自動授予新檔。
