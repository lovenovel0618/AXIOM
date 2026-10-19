# Docker 本地架設指南

> AXIOM | 規劃基線 v1.0 | 2026-10-19 | 文件：`03-架構/41-Docker本地架設指南.md`

## 文件目的
規範以 Docker Compose 在 macOS 建立可重現的本地開發與基準環境，作為 P0 基準測試與各模組開發的統一入口。

## 適用範圍

- 目標平台：macOS（Apple Silicon 與 Intel）搭配 Docker Desktop。
- 僅涵蓋開發與基準環境；正式環境分層、憑證與雲端受管服務見 `03-架構/08-部署與運算資源規劃.md`。
- 無 NVIDIA GPU 直通，容器一律以 CPU 執行；AI 推理另見「Mac 本地注意事項」。
- 本環境為**可重建**：狀態可由 Compose 定義與遷移流程還原，不作為唯一永久資料來源。

## 容器拓樸

```mermaid
flowchart TB
 subgraph EDGE["邊緣"]
  NG["Nginx :8080"]
 end
 subgraph APP["應用層"]
  VUE["frontend Vue3+Vite :5173"]
  WEB["web Django+DRF :8000"]
  CW["worker Celery light/search/precision"]
  CB["beat 排程"]
 end
 subgraph DATA["資料層"]
  PG[("PostgreSQL+pgvector :5432")]
  RD[("Redis :6379")]
  MO[("MinIO :9000/:9001")]
 end
 subgraph ISO["隔離層 無外網/唯讀"]
  PW["proof/sandbox worker"]
 end
 OLL["宿主 Ollama :11434（Metal）"]
 NG-->VUE
 NG-->WEB
 WEB-->PG
 WEB-->RD
 WEB-->MO
 CW-->RD
 CW-->PG
 CW-->MO
 PW-->PG
 CW-.host.docker.internal.->OLL
```

## 服務清單

| 服務 | 映像 | 容器埠 | 宿主埠 | 用途 |
|---|---|---|---|---|
| nginx | nginx:1.27-alpine | 80 | 8080 | 反向代理與靜態檔 |
| web | 自建 python:3.12-slim | 8000 | 8000 | Django + DRF API |
| frontend | node:20-alpine | 5173 | 5173 | Vue 3 + Vite 開發伺服器 |
| worker | 同 web 映像 | — | 無 | Celery 佇列：light／search／precision |
| beat | 同 web 映像 | — | 無 | 週期性排程（清理、TTL、基準回歸） |
| proof | 同 web 映像（選配） | — | 無 | 受限符號／形式化驗證，預設不啟用 |
| postgres | pgvector/pgvector:pg16 | 5432 | 5432 | 交易資料與向量索引 |
| redis | redis:7-alpine | 6379 | 6379 | 佇列、快取、分散鎖 |
| minio | minio/minio | 9000／9001 | 9000／9001 | 物件儲存與 Console |
| minio-init | minio/mc | — | 無 | 一次性建立 bucket 與存取政策 |

佇列隔離依 `03-架構/08` 的工作池分層；gpu 佇列在 Mac 本地不啟用，相關任務降級為本地 CPU 或明確標示為未執行，不得假裝已使用外部推理。

## 資料卷與持久化

- 具名卷：`pgdata`、`redisdata`、`miniodata`、`static`、`media`、`ollama-models`（若容器化 Ollama）。
- 原始資料與已發布研究證據不得覆寫；`media`（上傳原始檔）與 `miniodata`（產出物件）分離，避免清理時誤刪證據。
- 僅原始碼以 bind mount 掛載以支援熱重載，並排除 `.DS_Store` 等平台干擾檔。
- `redisdata` 不作為唯一永久來源，允許重建。

## 環境變數與秘密

`.env` 為本地組態的單一真實來源，落實配置與代碼分離，且不得提交版本庫。容器以唯讀方式注入。

| 類別 | 關鍵鍵 |
|---|---|
| 資料層 | `POSTGRES_DB`、`POSTGRES_USER`、`POSTGRES_PASSWORD`、`REDIS_URL`、`MINIO_ROOT_USER`、`MINIO_ROOT_PASSWORD`、`MINIO_BUCKET` |
| 應用 | `DJANGO_SECRET_KEY`、`DJANGO_DEBUG`、`DJANGO_ALLOWED_HOSTS`、`DATABASE_URL` |
| AI 路由 | `CHATGPT_API_KEY`、`OLLAMA_BASE_URL`（預設 `http://host.docker.internal:11434`）、`MODEL_ROUTING_POLICY` |
| 預算與精度 | `RUN_BUDGET_CPU_SECONDS`、`RUN_BUDGET_TOKEN`、`DEFAULT_PRECISION` |
| 隔離 | `PROOF_ENABLED`、`SANDBOX_MEM_LIMIT`、`SANDBOX_PIDS_LIMIT` |

啟動時校驗必填鍵，缺漏即 **Fail-Closed** 終止，不得以預設密碼或空白金鑰繼續啟動。

## 啟動順序與健康檢查

- 依賴以 `depends_on: condition: service_healthy` 表達，不以固定 `sleep` 取代。
- 健康檢查端點：postgres `pg_isready`、redis `redis-cli ping`、minio `/minio/health/live`、web `/healthz`、nginx 反向探測 `/healthz`。
- 首次啟動流程：`compose up -d` → 等待全數健康 → 資料庫遷移 → 建立 bucket → 建立管理員 → 載入基準種子資料。
- 任一必要服務不健康時，web 不得對外提供服務；此為 Pre-flight 閘門，避免半啟動狀態產生不可信結果。

## Mac 本地注意事項

- Docker Desktop 需將專案路徑加入檔案共享；未設定會導致 bind mount 掛載失敗。
- Apple Silicon 上若遇僅提供 amd64 的映像，於該服務明確指定 `platform: linux/amd64`，並記錄效能折損，不預設全域套用。
- Ollama 建議以宿主原生安裝並使用 Metal 加速；Docker Desktop 無法直通 GPU，容器化 CPU 推理明顯較慢。容器僅透過 `host.docker.internal` 連線，若必須容器化需配置足量記憶體並標示為慢速回退。
- I/O：優先使用具名卷；避免對大量小檔做 bind mount（macOS 檔案系統穿越成本高），資料集以物件儲存或具名卷承載。
- 資源：Docker Desktop 建議配置 CPU ≥ 4 核、記憶體 ≥ 8 GB；實際門檻依 P0 基準實測設定，不預先宣稱足夠。
- 休眠喚醒後容器時鐘漂移可能影響排程與任務租約，需依 `03-架構/38` 的租約過期回收機制處理，不得依賴單次心跳。

## 安全與隔離（本地亦適用）

- proof／sandbox worker：`network_mode: none`、`read_only: true`、非 root 使用者、`cap_drop: ALL`、限制 `pids`／`mem`／`cpus`。
- 不將 Docker socket 掛載進任何 worker 容器。
- PostgreSQL 與 MinIO 的宿主埠僅供本機除錯，不對外網段開放；Redis 不設密碼時僅限本機網路。
- 敏感資料是否可送往外部 API 依資料分級決定，本地開發預設走 Ollama 路由。
- 控制措施與威脅模型對應 `09-非功能/26-安全隱私與可信執行.md`。

## 操作速查

| 目的 | 操作 |
|---|---|
| 啟動全部服務 | `docker compose up -d` |
| 檢視狀態與健康 | `docker compose ps` |
| 追蹤日誌 | `docker compose logs -f web worker` |
| 執行資料庫遷移 | `docker compose exec web python manage.py migrate` |
| 建立管理員 | `docker compose exec web python manage.py createsuperuser` |
| 進容器除錯 | `docker compose exec web bash` |
| 停止並保留資料 | `docker compose down` |
| 完全重置（含資料卷） | `docker compose down -v` |

完全重置具破壞性，僅在確認不需保留任何研究證據時執行。

## 不在此文件範圍

- 正式 HTTPS 憑證、WAF 與對外網域。
- 雲端受管服務（RDS／S3／ElastiCache）替換方案。
- Kubernetes 或多節點編排。
- CI 執行環境與安全掃描管線（見 `03-架構/08`）。

## 驗收與交付準則
- 文件內所有決策均有負責角色、驗證方法及可追溯的需求編號。
- 未完成事項不得標示為已實作；未經獨立驗證的數學主張不得標示為已證明。
- 重大設計變更應同步更新索引、架構決策與相關測試計畫。
