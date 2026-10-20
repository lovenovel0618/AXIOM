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

ready 另確認 foundation 與 runtime 兩個 migration（含不可變 trigger）已套用。T04 控制函式仍是可信服務介面，不公開成 Run API；T05 資料集／上傳 API 已另接真實 session 與固定租戶 ACL。控制 worker 與未來實際 INGEST handler 分開，本輪 DB 約束禁止將 control_only 直接關閉。

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
| POST /api/v2/uploads/{id}/complete | 驗目前ACL、checksum與固定版本；依賴T07，目前回503，不建假Run |

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

兩者均經真實HTTP登入、建資料集、PUT、查固定版本、測另一租戶與撤權，最後 business_ingest_status=NOT_RUN。--frontend另外走Vite同源代理（僅額外允許Compose內部frontend hostname，不使用萬用Host allowlist）。parser／掃描、DatasetVersion、真正Run結果提交、總租戶配額、GC／備份及公網政策尚待後續工作；不以檔案傳輸通過宣稱資料已安全解析。
