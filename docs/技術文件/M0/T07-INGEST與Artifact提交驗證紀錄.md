# T07｜INGEST 與 Artifact 提交驗證紀錄

日期：2026-10-20；owner／SELF_REVIEW：project-owner；承接c8de96a。[設計](<T07-INGEST與Artifact提交設計.md>)先於代碼。這是T07的第二切片，人工語意／研究版本尚未接入。

## 交付及實測

新增真正INGEST Run、TaskInput Artifact及不可變執行／budget快照；專用ingest queue、唯讀raw volume、單attempt worker；完成後原子登記DatasetVersion／StructureAssessment／Artifact與Run結果。新增版本清單、Run讀取及受授權Artifact metadata／JSON content。預設關閉，未配置完整ImportLimits仍503；明確啟用才202。

| 檢查 | 實際結果 |
|---|---|
| 完整後端 | PostgreSQL／Linux容器196／196：既有175＋新增21業務測試，無skip |
| 工程工具 | 74／74；baseline有效，m0_ready=false |
| 前端 | strict typecheck、8／8與build通過；本輪無UI修改 |
| strict Pyright | 根及backend設定0 errors／0 warnings |
| Sonar Python／IaC | 97／3檔diagnostics=[]，S3776門檻15未關閉 |
| 真HTTP／broker／worker | CSV／JSON／Parquet complete202→relay→專用worker→SUCCEEDED→版本及metadata Artifact可讀 |
| 去重／失敗／撤權 | 另一同內容upload仍成功且只3份版本；非法CSV FAILED、有純code診斷；原始content404、撤權後404 |
| 預設gate回歸 | catalog直連及frontend代理保持complete503；probe與控制Run smoke通過 |
| 遷移／文件 | 空庫遷移、makemigrations --check、manifest／文件契約通過；產品Gate仍NOT_RUN |

原始記錄：[後端](<t07-ingest-backend-tests.txt>)、[真實服務](<t07-ingest-smoke.json>)、[檢測與來源hash](<t07-ingest-validation.json>)。Linux arm64／Python3.13.16、Polars1.44.2；工具Python3.13.15。遠端amd64以本提交Actions為準，不推論WSL2已驗收。

## SELF_REVIEW與拒絕案例

- 四個並行complete只建立一個Run／input Artifact，重送不因key／24h或upload期限另派生Run；completed仍重查ACL與checksum。原control_only不能改成business，真業務必有原子binding及對應TaskInput。
- DatasetVersion以dataset／SHA唯一，持dataset鎖提交。兩個相同內容Run重用同版本，不因unique exception卡死。版本、Artifact內容／metadata、provenance及已寫result不可SQL改寫；跨租戶FK和讀取拒絕。
- 交易callback失敗不留版本或成功audit。重複派送不增attempt／版本；舊generation、deadline、parser失敗、source掉包、Django User停用、撤權前／執行中撤權均不能提交。
- 取消案例測的是parser返回後的提交fence及擁有handler確認停止，不是假造即時取消壓力驗收。原parser supervisor的實程序timeout／kill／wait證據保留；失聯程序不假裝已停止，未開business cancel HTTP。
- metadata Artifact符合StructureAssessment，source_metadata僅shape／schema；無samples、labels統計、fit hash或自動語意。原檔與input Artifact封存，PROJECT管理員也不能走HTTP下載原檔；metadata與診斷每次重新授權，無裸URI redirect。
- manifest使用實際環境、鎖檔、代碼及契約SHA；新業務input_hash排除execution reference，明確區分canonical TaskInput Artifact完整內容SHA。舊T04合成snapshot只保留明示legacy相容，不修改歷史immutable內容。
- CPU／wall整秒上取整、memory為high-water保守和。queue未開始為NOT_STARTED；執行中尚未回報及已開始失聯為UNKNOWN，不把0欄位解讀為免費成本。沒有未知成本自動retry或budget reset。
- Run回應與X-Control-Revision改用同一份讀取快照，避免兩次查詢間狀態更新使header與body不一致；執行中尚未結算不標為已測得用量。
- Sonar曾指出smoke主函式複雜度超限，已抽出版本／Artifact驗證，重跑分析，沒有忽略規則。

## 遷移、保留與界線

runtime.0004移除全面control_only=true限制，另加mode不可改guard。catalog.0003建立三張表及唯一鍵；0004加複合tenant FK、immutable內容、native provenance／version引用與deferred business Run-result原子guard。ready要求新guard migrations，不能缺guard就ready。

已存在business Run時不可直接降版恢復control_only=true約束；需先停ingest／relay／web、備份DB／原始volume，再具名處理資料及逆向依賴，不作無損回退承諾。測試只清除axiom-t07b-check／live，未操作其他專案。

尚無正式惡意軟體掃描／來源核驗／D-05敏感接收、全域quota／cgroup RSS／正式SLO、Artifact撤銷與保留GC。原始byte先有界讀入父程序；child是固定parser資源限制，同UID／network仍非完整sandbox，對掛載唯讀不等於租戶FS隔離。只供當期有權處理的本機公開／合成來源，不啟用正式blind資料。

T07的人工語意確認、ResearchVersion、PROFILE、已知DSL整合與工作台仍未完成；M0／M1產品gate維持NOT_RUN。下一步接語意、單位／domain／split及研究版本，不以本輪SUCCEEDED代表已發現或驗證公式。
