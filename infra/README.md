# 本機開發環境（T04）

目前只供本人在 loopback 使用，已有本機 session 認證與資料集／上傳切片，完整研究 API 尚未完成。設計／驗收界線見 [T04 技術文件](<../docs/技術文件/M0/T04-產品工程骨架.md>)。Compose 提供 PostgreSQL、Redis、一次性 migration、web、worker、relay、Vue；T05 已提供版本化本機物件與租戶 ACL；MinIO／S3 尚未實作。

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

ready 另確認 foundation、runtime、catalog與session及新INGEST guards migrations已套用。T04 控制函式仍是可信服務介面，不公開成 Run API；T05 資料集／上傳 API 已另接真實 session 與固定租戶 ACL。控制 worker 與未來實際 INGEST handler 分開，本輪 DB 約束禁止將 control_only 直接關閉。

## 帳號與上傳操作（T05）

於本機開發環境預先建立帳號，互動輸入至少12字元密碼，不把密碼放命令參數或 shell history：

```sh
docker compose exec web python manage.py provision_account dino local --role ADMIN
```

每帳號固定一租戶；不要用請求 header 選租戶。命令輸出 actor／tenant UUID，不輸出密碼。後續同租戶帳號使用相同 tenant 名稱；需要不同行政租戶時使用不同名稱。帳號管理是本機受信任管理操作，沒有遠端邀請／註冊／公開分享。

開啟 <http://127.0.0.1:15173/auth/login> 或後端18000的同一路徑。GET表單取得 axiom_csrf，POST帳密成功回status=ok並輪替 axiom_session；cookie名與其他 localhost 專案分開。/auth/logout只可POST＋X-CSRFToken。後續請求需目前session及CSRF header；Idempotency-Key為研究資源POST的必填header。

| 入口 | 目前行為 |
|---|---|
| GET／POST /api/v2/datasets | 授權分頁清單／建立資料集；POST body={name} |
| POST /api/v2/datasets/{id}/uploads | body={filename,format,size_bytes,sha256}；CSV／JSON／PARQUET、最高50MiB |
| UploadSession.put_url | 只可PUT原bytes，攜帶required_headers及session／CSRF；簽章不放URL query |
| POST /api/v2/uploads/{id}/complete | 驗目前ACL、checksum與固定版本；預設503，明確啟用後依下節建立真正Run |

Dataset／Upload建立回應可依相同key與payload重讀；不同payload回409，撤權後不回放舊回應。逾期簽章需新session，不能藉重播延長。列表cursor綁actor／租戶並重新查ACL。管理員需明確grant才能讀他人的資料集，可用受控命令：

```sh
docker compose exec web python manage.py grant_dataset ADMIN_ACTOR_UUID TARGET_ACTOR_UUID DATASET_UUID READER
# permission 亦可 EDITOR、OWNER、REVOKE；VIEWER 全域角色不因editor grant取得寫入權。
```

只有web掛載object-data；worker、frontend沒有原始物件volume。原始filename只作metadata，實際檔名由UUID產生。檔案固定版本且每次驗SHA／大小；沒有匿名下載、目錄列表、靜態原檔或Artifact API。一般down保留DB和物件volume，down --volumes同時刪除，勿用於有保留需求的環境。這是local-versioned-v1，不是S3／MinIO驗收。

以下smoke會建立隔離的隨機合成帳號、資料集及小檔，只能在可丟棄的本機／CI環境執行，不對正式資料庫使用：

```sh
docker compose exec -T web python manage.py catalog_smoke
docker compose exec -T web python manage.py catalog_smoke --frontend
```

兩者均經真實HTTP登入、建資料集、PUT、查固定版本、測另一租戶與撤權，最後 business_ingest_status=NOT_RUN。--frontend另外走Vite同源代理（僅額外允許Compose內部frontend hostname，不使用萬用Host allowlist）。parser／DatasetVersion及真正Run提交已由下節的明確啟用流程接入；掃描、總配額、GC／備份及公網政策仍待後續，不以檔案傳輸通過宣稱全部安全政策已驗收。


## 有界結構預覽（T07前置切片）

Linux容器可針對已授權且未過期的原始upload執行預覽，五項limits必填：

```sh
docker compose exec -T web python manage.py ingest_preview ACTOR_UUID UPLOAD_UUID --max-rows 10000 --max-columns 32 --max-cell-utf8-bytes 65536 --max-decoded-bytes 8388608 --max-parse-seconds 10
```

重新查現行actor／tenant／Dataset寫入ACL，核對固定版本SHA後，清除繼承環境並交獨立Python程序解析。CSV／JSON／Parquet皆只回欄名、格式型別及列數，沒有樣本或標籤統計。程式不猜單位／特徵／時間語意。原始row序不改、空值不補、問題列不靜默丟棄。這是受信任本機CLI，不可把actor UUID當遠端登入憑證。

子程序有1GiB address-space、CPU、wall deadline及輸出限制；同UID並非檔案系統／網路沙箱，不能用來跑插件。只有Linux實測，宿主macOS會拒絕此入口。原檔不可變，temporary copy在正常／解析失敗時清除；父程序crash遺留、總配額與GC仍待後續。詳細限制見[技術設計](<../docs/技術文件/M0/T07-有界匯入解析設計.md>)。

可丟棄環境另執行 `docker compose exec -T web python manage.py ingest_preview_smoke`，會經真實HTTP建立三格式合成上傳再預覽。這個前置工具本身不呼叫complete或建立版本；真正Run／Artifact依下一節明確啟用，研究版本仍待後續。


## 真正 INGEST 與版本／Artifact（T07第二切片）

預設gate關閉，complete仍503。以下僅用於有權使用的本機公開／合成資料；五項limits全部必填，沒有正式D-01容量或D-05接收核准聲明：

```sh
AXIOM_INGEST_ENABLED=1 AXIOM_IMPORT_LIMITS='{"max_rows":10000,"max_columns":32,"max_cell_utf8_bytes":65536,"max_decoded_bytes":8388608,"max_parse_seconds":10}' docker compose --profile ingest up --build -d --wait --wait-timeout 120
```

要持續使用同一設定可放入既有未追蹤.env；不要將秘密或個人資料提交。後續重建需沿用啟用設定。新增ingest worker只聽ingest queue、concurrency=1、每個task重啟pool child，raw volume唯讀；foundation worker／frontend仍無原始volume。relay持久重送，lease拒絕重複／晚到提交；每Run只一個business attempt，失聯不自動重跑未知用量。

啟用後complete回202 Run；同一upload永久指同一Run，已COMPLETED即使過期也回同一ID，但重查目前ACL及checksum。成功才提交DatasetVersion與StructureAssessment metadata Artifact；同dataset／SHA去重。失敗要檢查診斷並另開upload／Run，不重置原Run。新增讀取入口：

- GET /api/v2/datasets/{id}/versions：同Dataset ACL的游標清單。
- GET /api/v2/runs/{id}：公開Run、X-Control-Revision及X-Usage-Status。
- GET /api/v2/artifacts/{id}、/content：現行ACL及class檢查、JSON attachment／no-store／nosniff。

原始與TaskInput Artifact當期一律SEALED_DETAIL且HTTP回404；只有純結構預覽與不含原值的錯誤碼診斷為PROJECT。UNKNOWN用量不能當零成本；CPU／wall向上取整，memory為process high-water保守和，非精確同時RSS。這不是cgroup／quota／公網／正式blind驗收。

可丟棄環境可執行 `docker compose exec -T web python manage.py business_ingest_smoke`，會建立三格式合成資料，實際等待relay／worker並讀metadata、測去重／非法資料與撤權。停止新匯入時先停ingest worker，設定AXIOM_INGEST_ENABLED=0並重建web／relay；既有queued Run依期限裁決，不刪除或改成control probe。

metadata中的source_metadata只含欄名／格式型別／row_count，不猜語意、不取labels統計；人工語意、ResearchVersion與PROFILE仍未開放。執行環境／hash、遷移與限制見[技術設計](<../docs/技術文件/M0/T07-INGEST與Artifact提交設計.md>)。
