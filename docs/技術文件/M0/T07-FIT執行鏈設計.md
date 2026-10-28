# T07｜FIT 執行鏈

2026-10-28；承接 SEARCH 產生的不可變候選及 FitRun。M1／M2 的正式階段驗收仍須各項證據及決策齊備。

## 執行與權威

三策略已在隔離 SEARCH 內以 fit 列求得係數；輸出 DSL 的參數界限相等。因此 FIT worker 的工作是固定該 binding 的獨立重放與 fit／development 評分，不能再改係數或讀 final labels。既有 FitRun 保存搜尋所得參數；新增 ValidationRun 保存真正執行結果，不把占位 Run 當成已執行。

只對具有成功 SEARCH 快照的候選附加 FIT 快照，離線 fixture 不自動派送。保留既有根任務、輸入、manifest、帳本 UUID；附加輸入、私有 projection recipe、真實 root 帳本與 RunQueued outbox 在同交易提交。FIT 預留逐項准入；研究 CLOSING 只允許已成功 SEARCH 的固定候選收尾，CLOSED 不接受新工作，不重開研究帳本。容量不足保持待派送，不丟候選或假造零用量。

專用 FIT relay／queue／worker 明確啟用；worker 重新驗來源、owner、租戶、環境、快照及固定 binding，使用既有 Linux 有界解析與求值子程序。失敗、取消、重送與租約過期仍採 runtime fencing 和研究帳本；未證明停止的用量保留。結果在 finish 回呼內同交易建立 FIT／DEVELOPMENT 的不可變 ValidationRun 與私有報告，完整保存分母與無法評分理由，只有 E1／P0 描述性證據，不推導正式支持結論。

## 驗證

真實 PostgreSQL 與 Linux 子程序驗成功執行、雙 split 結果、分母、重送、跨租戶、disabled、容量不足、取消、來源失效與終態不可重開。全量回歸後再更新 MD／HTML 清單；不以本文件取代正式產品驗收。
