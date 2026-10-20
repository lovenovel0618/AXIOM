# T06｜安全 DSL 求值驗證紀錄

日期：2026-10-20；owner／SELF_REVIEW：project-owner；承接 dcc367c。技術設計見 [安全 DSL 求值](<T06-安全DSL求值設計.md>)。

## 交付與驗證

mathematics 提供 compile_dsl／evaluate、不可變 Plan、canonical 身分、SI 單位與固定域檢查。schema 直接使用企劃案權威來源；容器攜帶 schema 與公開 examples，CI 不跳過 fixture。沒有增加依賴或 DB migration。

| 檢查 | 結果 |
|---|---|
| 新數學測試 | 40／40；包含固定 canonical bytes、Fraction、70位 Decimal 與獨立 sine Taylor oracle |
| 完整後端 | PostgreSQL 容器131／131；原有91項交易、HTTP、版本化儲存與控制核心回歸通過 |
| 工程工具 | 74／74；baseline 有效，但 m0_ready=false |
| 前端 | typecheck、8／8測試及build通過 |
| strict Pyright | 根目錄與 backend 設定均0 errors／0 warnings |
| Sonar | Python 74檔、IaC 3檔 diagnostics=[]；保留 S3776 的15門檻，沒有忽略規則 |
| 真實服務 | probe、Run／Attempt、catalog直連與frontend代理 smoke通過；complete仍503 |
| schema／DB | 空庫遷移及makemigrations --check通過；無新增migration |
| 文件 | 契約／連結／manifest檢查通過；產品gate維持NOT_RUN |

後端測試及機器證據見 [測試紀錄](<t06-backend-tests.txt>)、[公開 oracle smoke](<t06-math-smoke.json>)、[來源與檢測](<t06-validation.json>)。本機Python3.13.15；Compose為Linux arm64／Python3.13.16。遠端amd64以對應提交的Actions結果為準，不推論WSL2已驗收。

## 自我檢查與反例

- 先限制bytes／JSON容器／AST深度及節點，再遞迴驗schema；重複及escaped同名key、surrogate、NaN、1e400、浮點JSON、未知／宿主運算、額外欄位與錯arity均拒絕。
- 上限同時適用原始AST及正規化後的計畫；Plan每次使用重新驗證canonical bytes，不接受偽造hash或metadata。不同宣告排列及可安全折疊的有理常數有穩定身分，域或開閉旗標改變會改hash。
- 量綱不相容、重名、缺domain、非法單點域、非整數／越界冪與未選分支的未知符號皆先拒絕。單位由編譯器推導，不採信輸入自填。
- x/x、0*(x/x)及0^0不被消去；除零／log非法／overflow／可偵測underflow均留空並保留列。分段只執行首個符合分支，未選log負值不污染結果。
- 域界以精確有理數比較binary64輸入，測到0.1及其前一個float對1/10的差異；沒有偷偷放寬域或丟棄無效樣本。binding須完整、在參數界內，不能以NaN或指數文字繞過。
- 每批列數、保守總節點額度及單調deadline實測拒絕；超限不回部分成功。canonical rational增長超128位即拒絕，不做無界大整數展開。
- 初輪Sonar指出regex可簡化，已採ASCII模式的\\d維持原識別範圍並重新分析。型別補齊而未關閉strict規則。

## 限制與下一步

此輪是本機float64純量求值基線，不是任意精度、符號等價證明或完整AX-12最佳化。precision_bits記53；可偵測下溢拒絕，但非零捨入、對消與條件數診斷仍待後續；不把測試容差解讀為量測精度。

1秒為求值迴圈的cooperative deadline；編譯受固定結構與位數限制，尚無OS強制CPU／RSS supervisor，也無正式負載SLO。沒有HTTP數學endpoint、搜尋插件或正式封存資料入口。下一步T07接真正INGEST、語意確認、研究版本與已知公式整合。M0及全部產品Gate仍未關閉。

回退還原本輪程式與CI／文件即可；沒有資料遷移。測試使用獨立axiom-t06-check並清除其volume，未操作其他專案容器。
