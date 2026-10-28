# Coverage 報告與 Sonar 接線

2026-10-28：承接完成度清單的 coverage 缺口。本切片交付可重現的前後端覆蓋率報告、CI artifact 保存、合併後的路徑檢查，以及可選的 Sonar 匯入；正式 new_coverage 門檻與產品 Gate 仍待驗收。

本機驗證：後端 455、前端 398、工程工具 85 項測試通過；後端行覆蓋率 82.97%、分支 75.59%，前端行覆蓋率 40.35%、分支 33.36%。報告已核對 93 個後端與全部 122 個前端來源檔。Node 24 容器的型別檢查與建置、Pyright、型別政策與文件檢查均通過。詳見 [機器驗證紀錄](validation-2026-10-28.json)；GitHub Actions 與 Sonar 伺服器端執行仍為 NOT_RUN。

## 本機執行

從儲存庫根目錄執行。`axiom-coverage` 是獨立測試專案，只使用合成資料及 Django 的 `test_axiom` 資料庫。請勿把清理指令改為 `axiom-dev`。

```sh
mkdir -p reports
docker compose -p axiom-coverage up -d --wait postgres redis
docker compose -p axiom-coverage -f compose.yaml -f tools/coverage/compose.yaml run --build --rm --no-deps --user "$(id -u):$(id -g)" coverage
cd frontend
npm ci --ignore-scripts
npm run typecheck
npm run test:coverage
npm run build
cd ..
python3 tools/check_coverage_reports.py
docker compose -p axiom-coverage down --volumes --remove-orphans
```

後端使用與正式 image 相同的依賴及 Linux 環境，另由明確的 `coverage` build target 安裝鎖定且經 hash 驗證的 coverage.py。預設最後一個 `production` target 不含 coverage。測試以主機 UID 寫入報告，並在容器 `/tmp/axiom-coverage-objects` 建立可寫的測試物件目錄，避免 GitHub runner 的 bind mount 權限及健康檢查問題。

後端報告位於 `reports/backend-coverage.xml`，包含 branch coverage；前端位於 `frontend/coverage/lcov.info`、`coverage-summary.json` 及 `lcov-report/`。這些產物不提交 Git。後端排除測試及自動產生的 migrations；其餘正式 Python 程式納入計算。前端明確包含全部 `src/**/*.ts` 與 `src/**/*.vue`，未匯入的畫面會以零覆蓋率呈現。

隔離 parser／搜尋 child 以 `python -I` 執行，不注入 coverage hook，這些 worker 檔案仍納入分母並保留未量測的行。數據代表此測試命令的程序內覆蓋率，不能當成瀏覽器 E2E 或隔離子程序全鏈覆蓋率。

## CI 與 Sonar

`product-check` 後端與前端 job 各自產出 artifact；`coverage` job 下載兩份報告，先驗證相對路徑、來源存在、報告非空與前端檔案範圍完整。來源錯誤或漏列 Vue 檔案會讓 CI 失敗。

`sonar-project.properties` 已指定 Python XML 與 JS/TS LCOV 路徑，並把測試程式分類為 test scope。XML 的 source 為 `backend`，LCOV 路徑由 repo root 開始，因此下載到另一台 runner 仍能對應原始碼。

若要啟用主分支 push 後的 Sonar 掃描，在 repository 設定 variable `SONAR_ENABLED=true` 與 secret `SONAR_TOKEN`。掃描使用既有 `sonar.host.url`，等待伺服器既有 Quality Gate；不變更伺服器門檻。PR 仍產出及驗證報告，Sonar 掃描只在主分支 push 執行。

正式 new_coverage 的比較基準、門檻與伺服器匯入結果仍需另行驗收；本機沒有 `SONAR_TOKEN` 時不宣稱 Sonar Gate 通過。

設定依據：[coverage.py 相對路徑](https://coverage.readthedocs.io/en/7.16.2/config.html)、[Vitest coverage](https://vitest.dev/guide/coverage.html)、[Sonar coverage 參數](https://docs.sonarsource.com/sonarqube-server/2026.1/analyzing-source-code/test-coverage/test-coverage-parameters)、[Sonar 官方 action](https://github.com/SonarSource/sonarqube-scan-action)。
