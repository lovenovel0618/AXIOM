# 本機開發環境（T04）

目前只供本人在 loopback 使用，尚無認證與正式研究 API。設計／驗收界線見 [T04 技術文件](<../docs/技術文件/M0/T04-產品工程骨架.md>)。Compose 提供 PostgreSQL、Redis、一次性 migration、web、worker、relay、Vue；物件儲存與租戶授權於 T05 接續。

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
```

開啟 <http://127.0.0.1:15173>；前端 ready 經 Vite 代理回 web。ready 檢查資料表及 Redis；probe_smoke 必須由常駐 relay 首次派送、worker 完成後再故意重播兩次訊息，完成計數仍為一。沒有 worker／relay 時 smoke 會逾時失敗。

## 測試與代碼檢測

```sh
docker compose run --rm web python manage.py test foundation.tests -v 2
docker compose run --rm web python manage.py makemigrations --check --dry-run
docker compose run --rm frontend sh -c 'npm run typecheck && npm test && npm run build'
```

Python 測試使用實際 PostgreSQL 的 `test_axiom`，需要開發帳號有建立測試資料庫權限；只在這組本機專用資料庫執行。不要把 Compose 指向正式資料庫。依賴版本、hash 與映像 digest 由 T02 沿用；backend 的 dev lock 引用 T02 runtime lock 及文件 dev requirements，再加入 Django／Celery／Redis 型別套件，CI 安裝時校驗 hash。

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
