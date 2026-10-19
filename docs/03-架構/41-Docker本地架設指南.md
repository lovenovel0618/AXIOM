# Docker 本地架設指南

> AXIOM | 整合基線 v2.2 | 2026-10-19 | 文件 ID AX-41｜文件：`03-架構/41-Docker本地架設指南.md`

## 文件目的

規範以同一份 Docker Compose 定義，在 macOS（開發）與 Windows WSL2（架設）建立可重現環境，作為 P0 基準測試與各模組開發的統一入口。

## 適用範圍與環境矩陣

| 角色 | 平台 | Docker 執行方式 | 映像架構 | GPU |
|---|---|---|---|---|
| 開發 | macOS（Apple Silicon／Intel）+ Docker Desktop | Linux 虛擬機 | arm64（必要時 amd64） | 無直通 |
| 架設 | Windows 11 + WSL2（Linux 發行版）+ Docker | Linux 原生核心 | amd64 | 依宿主是否具 NVIDIA GPU，待確認 |

- 兩環境共用同一份 Compose 定義與 `.env` 契約，平台差異僅以覆寫檔表達（見「跨環境一致性」）。
- 僅涵蓋開發與架設環境；正式對外部署、憑證與雲端受管服務見 [08-部署與運算資源規劃](<08-部署與運算資源規劃.md>)。
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
 OLL["Ollama :11434（macOS 宿主原生／WSL2 視 GPU）"]
 NG-->VUE
 NG-->WEB
 WEB-->PG
 WEB-->RD
 WEB-->MO
 CW-->RD
 CW-->PG
 CW-->MO
 CW-->PW
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

佇列隔離依 `03-架構/08` 的工作池分層；macOS 開發環境不啟用 gpu 佇列，相關任務降級為本地 CPU 或明確標示為未執行，不得假裝已使用外部推理。WSL2 架設環境是否啟用 gpu 佇列，取決於宿主 GPU 直通能力（待確認，見「Windows WSL2 架設環境注意事項」）。

## 資料卷與持久化

- 具名卷：`pgdata`、`redisdata`、`miniodata`、`static`、`media`、`ollama-models`（若容器化 Ollama）。
- 原始資料與已發布研究證據不得覆寫；`media`（上傳原始檔）與 `miniodata`（產出物件）分離，避免清理時誤刪證據。
- 僅原始碼以 bind mount 掛載以支援熱重載，並排除 `.DS_Store` 等平台干擾檔。
- WSL2 架設時，專案目錄與具名卷必須位於 WSL2 的 Linux 檔案系統（如 `/home/<user>/...`），不得使用 `/mnt/c/...`；跨檔案系統 I/O 效能顯著下降。
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
- 健康檢查端點：postgres `pg_isready`、redis `redis-cli ping`、minio `/minio/health/live`、web `/livez`（程序存活、不查 schema）及 `/readyz`（DB schema、必要服務與 init version 已就緒）、nginx 反向探測 `/readyz`。
- 首次啟動先啟動 PostgreSQL／Redis／MinIO 並等待基礎服務健康，再執行一次性 init job（遷移、bucket／最小權限帳號、管理員與公開 fixture），最後啟動 web／worker／nginx。init 失敗即停止，不先等待依賴 schema 的 web 就緒。
- 任一必要服務不健康時，web 不得對外提供服務；此為 Pre-flight 閘門，避免半啟動狀態產生不可信結果。

## macOS 開發環境注意事項

- Docker Desktop 需將專案路徑加入檔案共享；未設定會導致 bind mount 掛載失敗。
- Apple Silicon 上若遇僅提供 amd64 的映像，於該服務明確指定 `platform: linux/amd64`，並記錄效能折損，不預設全域套用。
- Ollama 建議以宿主原生安裝並使用 Metal 加速；Docker Desktop 無法直通 GPU，容器化 CPU 推理明顯較慢。容器僅透過 `host.docker.internal` 連線，若必須容器化需配置足量記憶體並標示為慢速回退。
- I/O：優先使用具名卷；避免對大量小檔做 bind mount（macOS 檔案系統穿越成本高），資料集以物件儲存或具名卷承載。
- 資源：Docker Desktop 建議配置 CPU ≥ 4 核、記憶體 ≥ 8 GB；實際門檻依 P0 基準實測設定，不預先宣稱足夠。
- 休眠喚醒後容器時鐘漂移可能影響排程與任務租約，需依 `03-架構/38` 的租約過期回收機制處理，不得依賴單次心跳。

## Windows WSL2 架設環境注意事項

- WSL2 提供 Linux 執行環境；實際架構與資源需納入環境紀錄。Docker 可採 Docker Desktop 的 WSL2 整合，或於發行版內直接安裝 Docker Engine（需於 `wsl.conf` 啟用 `systemd` 以管理服務）。
- **路徑**：專案與具名卷必須置於 WSL2 的 Linux 檔案系統（`/home/<user>/...`），不得放在 `/mnt/c/...`；跨檔案系統 I/O 會使建置與資料讀取明顯變慢，且檔案變更通知常失效。
- **換行與權限**：由 Windows 側編輯的檔案可能帶入 CRLF，導致容器內 shell 腳本執行失敗；需以 `.gitattributes` 或 `core.autocrlf` 統一為 LF，並確認掛載檔案的執行權限。
- **資源上限**：WSL2 預設僅使用宿主部分記憶體與 CPU，需以 `%UserProfile%\.wslconfig` 調整 `memory`／`processors`／`swap` 後重啟 WSL；實際門檻依 P0 基準實測設定。
- **埠存取**：WSL2 支援 localhost 轉發，Windows 端以 `localhost:8080` 存取服務；若需對外網段開放，須另行設定防火牆與連接埠轉發，且不符「宿主埠僅供本機除錯」原則。
- **GPU**：若 Windows 宿主具備 NVIDIA GPU 並安裝對應 WSL 驅動，可直通供 Ollama 或訓練 worker 使用，此時可啟用 gpu 佇列；若無，則比照 macOS 走 CPU 並標示為慢速。**此項待確認**，未確認前不得宣稱 GPU 可用。
- **映像架構**：本案 WSL2 架設基線暫定 amd64；啟動前須檢查宿主與映像架構。與 macOS 的 arm64 並存時，映像需為多架構（以 buildx 建置）或以 amd64 為基準，避免兩環境行為不一致。
- **生命週期**：宿主休眠或 `wsl --shutdown` 會終止容器，重啟後須確認服務健康與任務租約回收；時間同步與租約過期回收需實測；租約判定以 DB 時間為準。
- **備份**：資料卷位於 WSL2 虛擬磁碟內，需定期匯出至 Windows 側或外部儲存，並演練還原。

## 跨環境一致性

- 以同一份 Compose 定義與 `.env` 鍵集合為契約；平台差異只能透過覆寫檔表達，不得各自維護分歧的服務清單。
- 兩環境的映像標籤、遷移版本與基準測試設定須一致，否則基準數據不可互相比較。
- 環境矩陣中的「待確認」項目在確認前，相關能力一律視為不可用（Fail-Closed），並同步更新 [37-決策待確認清單](<../12-附錄/37-決策待確認清單.md>)。

## 安全與隔離（兩環境皆適用）

- proof／sandbox worker：`network_mode: none`、`read_only: true`、非 root 使用者、`cap_drop: ALL`、限制 `pids`／`mem`／`cpus`。
- 不將 Docker socket 掛載進任何 worker 容器。
- PostgreSQL 與 MinIO 的宿主埠僅供本機除錯，不對外網段開放；Redis 不設密碼時僅限本機網路。
- 敏感資料是否可送往外部 API 依資料分級決定，本地開發預設走 Ollama 路由。
- 控制措施與威脅模型對應 [26-安全隱私與可信執行](<../09-非功能/26-安全隱私與可信執行.md>)。

proof／sandbox 採無網路模式時，不可直接連接 PostgreSQL、Redis 或 MinIO；由可信 worker 透過受限輸入／輸出目錄交付任務與讀回結果，再提交資料庫。proof 容器不得持有資料庫憑證。拓樸圖中的 worker → proof 表示此受控交付，不是容器網路連線。

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
| 關閉 WSL2 釋放資源（Windows） | `wsl --shutdown` |
| 調整 WSL2 資源上限 | 編輯 `%UserProfile%\.wslconfig` 後執行 `wsl --shutdown` |
| 確認 WSL2 內 GPU 可用性 | `nvidia-smi`（於 WSL2 內執行） |

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

## 延伸閱讀

[AX-08 部署與運算資源規劃](<08-部署與運算資源規劃.md>)；[AX-26 安全隱私與可信執行](<../09-非功能/26-安全隱私與可信執行.md>)；[AX-37 決策待確認清單](<../12-附錄/37-決策待確認清單.md>)。

## 共用規則

版本、錯誤、證據與審查規則見 [AX-48 共用契約與文件治理](<../00-總覽/48-共用契約與文件治理.md>)；本章的專屬限制及驗收條件仍須同時滿足。

## 初始化、秘密與契約驗收補充

minio-init 可用 root 憑證建 bucket／service policy，但 web、worker 只拿各自最小權限帳號，不能共用 MINIO_ROOT_USER／PASSWORD。平台差異以覆寫檔與 capabilities 檢查表表達；資料層宿主埠綁 127.0.0.1，不能因省略 host IP 而意外對外監聽。CHATGPT_API_KEY 僅在已核准外部路由啟用時必填；MVP 外部路由關閉，不因缺該 key 而阻止本地規則啟動。

目前沒有 compose.yaml、Dockerfile 或應用管理命令實作；前述命令為目標操作介面，不可宣稱能在空倉庫直接架設。實作交付時需提供相應檔案、.env.example（無秘密）、migration/init job、healthcheck、backup/restore 與 smoke 驗收記錄。

| ID | 情境 | 預期 |
|---|---|---|
| AC-41-01 | 空 DB、web ready 依賴 schema | init 完成前 ready=false；初始化不等待 web ready，無啟動死結 |
| AC-41-02 | migration 或 bucket policy 建立失敗 | init 非零退出，web 不就緒、worker 不領研究 |
| AC-41-03 | 關閉外部模型且無 API key | 本地規則可啟動；web/worker 不持有 MinIO root 憑證 |
| AC-41-04 | 同 fixture 在 macOS／WSL2 | 記錄實際 arch/digest，按同容差驗收，差異不暗中忽略 |
