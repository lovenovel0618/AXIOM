# AXIOM

AXIOM（Adaptive eXploration, Inference, and Objective Mathematics，公理探索）是數據驅動的公式發現、獨立驗證、推演與經驗學習平台。

目前已有設計規格、工程工具與 T04 本機 Django／Vue／Compose 基礎切片，可測健康檢查及合成任務派送。T05 已提供 session／CSRF、租戶隔離的資料集與上傳 API，以及私有不可變本機物件；已加入持久 Run／Attempt 的 INGEST 根控制流程；T06 已加入有界純量 DSL 編譯與求值、量綱／域檢查及獨立 oracle；T07 已提供 Linux 有界解析及明確啟用的真正 INGEST／DatasetVersion／Artifact 提交，及人工語意確認／不可變研究草稿 API、本機有界品質與已知公式預檢，以及明確啟用的 PROFILE 任務、兩層預算帳本與私有品質／fit 結構報告；完整研究 API／Run 任務樹尚未完成；企劃驗收案例維持 NOT_RUN，工程測試通過不等同產品整體驗收。

## 企劃案

企劃與設計規格位於 [docs/企劃案](docs/企劃案/README.md)：54 篇編號章節（AX-00～53）、整合紀錄、來源採納／全量審查清單、contracts與文件檢查工具。新增自主表徵、錯誤重審、正逆向驗證與AI紀錄／經驗演化規格，按里程碑分段交付。閱讀順序與角色路徑見 [docs/企劃案/README.md](docs/企劃案/README.md)。

開發流程與第一輪開工清單見 [AX-31](docs/企劃案/11-交付/31-工作拆解WBS與依賴.md#依企劃案落地的開發流程)。

## 技術實作與檢查

目前由你一人開發，各技術角色由本人兼任；開發採「技術文件→代碼→測試→代碼檢測→自我檢查→commit／push」，不等待第二位程式 reviewer。目前已實作 T01 的離線開工基線檢查與 T02 的隔離相容性驗證（含測試專用 Compose），以及 T03 公開 oracle／分區／投影與真實 UID canary 驗證；技術設計與執行方式見 [技術文件](docs/技術文件/README.md)，T04 已加入本機服務骨架，啟動及診斷見 [infra/README.md](infra/README.md)。T02 的重現指令、鎖定依賴與平台實測見 [相容性驗證](docs/技術文件/M0/T02-技術選型與相容性驗證.md)。

```sh
.venv-backend/bin/python tools/typing_policy.py
.venv-backend/bin/python tools/development_baseline.py
.venv-backend/bin/python -m unittest discover -s tests -v
```

基線有效與 M0 就緒分開回報；單人責任已設定；未決政策及其他交付不自動核准。環境安裝及型別檢查方式如下。

T03 的固定公開案例與隔離測試見 [技術文件](docs/技術文件/M0/T03-公開基準與盲測隔離基線.md)，可先執行 `.venv-backend/bin/python -m tools.benchmark.public_oracle`。

T06 的設計與限制見 [安全 DSL 求值](docs/技術文件/M0/T06-安全DSL求值設計.md)。未啟動容器時，可執行 `PYTHONPATH=backend .venv-backend/bin/python -m unittest mathematics.tests -v` 及 `PYTHONPATH=backend .venv-backend/bin/python -m mathematics.smoke`。

## 文件檢查

```sh
uv venv --python 3.13 .venv-backend
uv pip sync --python .venv-backend/bin/python --require-hashes backend/requirements-dev.lock
.venv-backend/bin/pyright
.venv-backend/bin/python docs/企劃案/tools/check_docs.py
```

工具檢查本地連結、章節編號、標頭版本、AC 追溯、schema 與 OpenAPI 一致、跨契約參考情境、公開 oracle 與 MANIFEST 校驗；不執行搜尋引擎、安全隔離、備份恢復或瀏覽器驗收。編輯文件後以 `--write-manifest` 重建清單。細節見 [docs/企劃案/README.md](docs/企劃案/README.md)。

## 本地架設

macOS（開發）與 Windows 11 + WSL2（架設）共用同一份 Docker Compose 定義；服務清單、環境變數、健康檢查與平台注意事項見 [AX-41 Docker本地架設指南](docs/企劃案/03-架構/41-Docker本地架設指南.md)。T04 已實作本機切片；WSL2 與完整目標拓樸尚未驗收。

依 [設定說明](infra/README.md) 建立未追蹤的 `.env` 並填入獨立亂數密鑰後：

```sh
docker compose up --build -d --wait --wait-timeout 120
docker compose run --rm web python manage.py probe_smoke
docker compose run --rm web python manage.py runtime_smoke
docker compose run --rm web python -m mathematics.smoke
docker compose exec -T web python manage.py catalog_smoke
docker compose exec -T web python manage.py catalog_smoke --frontend
docker compose exec -T web python manage.py ingest_preview_smoke
```

開啟 <http://127.0.0.1:15173>。產品交易測試與前端檢查：

```sh
docker compose run --rm web python manage.py test foundation.tests runtime.tests catalog.tests mathematics.tests mathematics.test_linalg mathematics.test_search ingestion.tests -v 2
docker compose run --rm frontend sh -c 'npm run typecheck && npm test && npm run build'
```

## 本機帳號與上傳

沒有預設帳密或公開註冊。依 [帳號與上傳操作說明](infra/README.md#帳號與上傳操作t05) 預先建立帳號，從 <http://127.0.0.1:15173/auth/login> 登入。在 `.env` 設好 `AXIOM_BOOTSTRAP_ACCOUNTS`（JSON 陣列，每項含 `user`／`password`：預設 `admin` 給 AI 助理、`dino` 給使用者本人，兩者共用同一租戶）後，資料庫重建（含 `down --volumes`）不需再手動建帳號：

```sh
docker compose up --build -d --wait --wait-timeout 120   # migrate 依 .env 自動建立本機帳號
docker compose logs migrate                              # status=CREATED／REPAIRED／EXISTS／SKIPPED
docker compose exec web python manage.py changepassword dino
```

若 macOS 的 Docker TTY 仍回 `UnicodeDecodeError`，改用不經 `getpass` 的穩定寫法：

```sh
read -s AXIOM_NEW_PASSWORD && echo
docker compose exec -T -e AXIOM_NEW_PASSWORD="$AXIOM_NEW_PASSWORD" web \
  python manage.py shell -c "import os; from django.contrib.auth.models import User; u=User.objects.get(username='dino'); u.set_password(os.environ['AXIOM_NEW_PASSWORD']); u.save(update_fields=['password']); print('password-updated')"
unset AXIOM_NEW_PASSWORD
```

前台已有可用 MVP：登入後可建立資料集、以檔案選擇器上傳（前端自行計算 SHA-256）、查看版本列表，並進入任務詳情追蹤事件與檢視 PROJECT 產物；亦可在研究頁建立研究容器、以引導式表單完成語意確認與不可變 ResearchVersion 草稿，並以控制 revision 觸發 PROFILE。候選比較、證據檢視、最終評估槽位與 SEARCH 進度已有工作台呈現。同源 /api/v2/datasets 與上傳 API 也可直接測試。上傳僅保存私有原始 bytes，complete 預設回503；依 infra/README.md 明確啟用 ingest profile 及完整限制後，回202並由專用worker產生版本與純結構預覽。已支援人工語意確認與不可變 ResearchVersion 草稿；已有本機品質與已知公式預檢，另可明確啟用 PROFILE 任務／研究帳本，依 [操作說明](infra/README.md#研究帳本與profile任務t07第五切片) 取得品質及 fit-only 報告。正式封存與隔離 Evaluator 已有實作；PROFILE／封存完成後版本為 READY，SEARCH 派送需使用最新控制 revision。

## 未決事項

GPU（D-02）、正式對外架設（D-09）等阻擋條件見 [AX-37 決策待確認清單](docs/企劃案/12-附錄/37-決策待確認清單.md)。

開發服務完成驗證後保留運行，測試環境清理不得連帶停止 `axiom-dev`。服務／型別／中文註解規範見 [工程規範](docs/技術文件/M0/T07-服務常駐與型別註解規範.md)。Python 的既有動態 JSON 邊界由 `tools/typing-boundaries.json` 逐檔列管；strict 零診斷不代表這些邊界已全部消除。


SEARCH 切片3：[執行鏈與驗證紀錄](<docs/技術文件/M0/T07-SEARCH派送驗證紀錄.md>)、[機器循證](<docs/技術文件/M0/t07-search-dispatch-validation.json>)。支援 READY 版本派送、逐策略 checkpoint 續跑、研究帳本收斂與工作台 SEARCHING／候選進度；FIT 執行管線與正式產品 Gate 仍未開放。
