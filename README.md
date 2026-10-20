# AXIOM

AXIOM（Adaptive eXploration, Inference, and Objective Mathematics，公理探索）是數據驅動的公式發現、獨立驗證、推演與經驗學習平台。

目前僅有設計規格與機器可讀契約，尚無可執行產品或 Docker Compose 實作；所有驗收案例狀態為 NOT_RUN，文件檢查通過不等同產品測試通過。

## 企劃案

企劃與設計規格位於 [docs/企劃案](docs/企劃案/README.md)：54 篇編號章節（AX-00～53）、整合紀錄、來源採納／全量審查清單、contracts與文件檢查工具。新增自主表徵、錯誤重審、正逆向驗證與AI紀錄／經驗演化規格，按里程碑分段交付。閱讀順序與角色路徑見 [docs/企劃案/README.md](docs/企劃案/README.md)。

## 文件檢查

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r docs/企劃案/tools/requirements-dev.txt
.venv/bin/pyright
.venv/bin/python docs/企劃案/tools/check_docs.py
```

工具檢查本地連結、章節編號、標頭版本、AC 追溯、schema 與 OpenAPI 一致、跨契約參考情境、公開 oracle 與 MANIFEST 校驗；不執行搜尋引擎、安全隔離、備份恢復或瀏覽器驗收。編輯文件後以 `--write-manifest` 重建清單。細節見 [docs/企劃案/README.md](docs/企劃案/README.md)。

## 本地架設

macOS（開發）與 Windows 11 + WSL2（架設）共用同一份 Docker Compose 定義；服務清單、環境變數、健康檢查與平台注意事項見 [AX-41 Docker本地架設指南](docs/企劃案/03-架構/41-Docker本地架設指南.md)。目前尚無 `compose.yaml` 或 `Dockerfile`，文件中的指令為目標操作介面。

## 未決事項

GPU（D-02）、正式對外架設（D-09）等阻擋條件見 [AX-37 決策待確認清單](docs/企劃案/12-附錄/37-決策待確認清單.md)。
