# API 與任務契約

> AXIOM | 規劃基線 v1.0 | 2026-10-19 | 文件：`07-資料與API/21-API與任務契約.md`

## 文件目的
規劃前後端介面而不提供實作程式碼。

## API 資源

/projects、/datasets、/datasets/{id}/versions、/runs、/runs/{id}/events、/runs/{id}/candidates、/equations、/derivations、/proofs、/experiences/search、/benchmarks、/model-versions、/reports。

## 操作語意

建立研究回傳 run_id 與 202 Accepted；進度透過 SSE（首選）或 WebSocket；長任務可取消／恢復；候選列表支援分頁、排序與比較；公式輸出 AST、LaTeX、MathML（可選）與安全預覽值。

## 錯誤契約

統一 code、message、details、request_id、retryable；資料不足、超時、資源配額、非法 AST、數值不穩定、模型不可用與證明未完成需分別編碼。

## 版本治理

OpenAPI 規格、向後相容策略、schema_version、事件順序與冪等鍵；不可讓 AI 任意生成 API 動作。

## 驗收與交付準則
- 文件內所有決策均有負責角色、驗證方法及可追溯的需求編號。
- 未完成事項不得標示為已實作；未經獨立驗證的數學主張不得標示為已證明。
- 重大設計變更應同步更新索引、架構決策與相關測試計畫。
