# T07 SEARCH 切片3驗證紀錄

日期：2026-10-26；基線：50140e8；審查方式：SELF_REVIEW。設計見 [SEARCH 執行器](<T07-SEARCH執行器設計.md>)，實測摘要見 [機器循證](<t07-search-dispatch-validation.json>)。

本輪交付獨立 SEARCH 設定、fit/development 隔離投影、真實 TaskInput／projection recipe artifact、SEARCH root 派送、逐策略 checkpoint、候選綁定原 run、CPU／wall／RSS 與候選計數、狀態與帳本收斂、專用 relay／worker、工作台啟動與候選進度。既有離線 persist 與最小 FIT root 保留相容；FIT 不進 SEARCH relay 或執行入口。

SEARCH 只接受真正 PROFILE／封存後的 READY；enqueue 與預留原子推進 QUEUED，claim 後轉 RUNNING，run 相位 SEARCHING。超時轉 FAILED，取消轉 CANCELLED。成功只表示搜尋操作完成，不代表候選通過 final_test。四項定案均實作：projection 模式、狀態／帳本遷移、persist_under、逐策略續跑。

catalog 0026～0028 新增 SEARCH 活躍狀態與原生跨表防線，擴充 root 帳本允許 SEARCH，保存不可改刪的 SearchAttemptStop。研究帳本在成功 SEARCH 結束後為 CLOSING，僅允許固定 FrozenSubmission 的最終評估繼續，全部提交／槽位收斂且預留釋放後才 CLOSED；失敗／取消且全部已停止時可直接 CLOSED。原 attempt 失聯時保留未知成本，後續 attempt 完成不能假稱原程序已停止。原帳本仍接受授權的遲到用量，舊 lease 無法提交結果。

投影觀測以有限的 float64 十進位字串傳輸並在數學介面還原 float，避免 canonical checkpoint 身分雜湊排斥浮點。嚴格白名單拒絕 final 欄位、錯誤列數、bool 與非有限值。SEARCH task 引用的投影 artifact 是來源與映射固定的 recipe；HTTP 不提前執行未入帳的原始資料解析。一般 artifact API 無法讀取 SEALED_DETAIL。

測試使用真 PostgreSQL 與 Linux child：enqueue／冪等／並發 revision、三族結果與完整 search 等價、單一 SEARCH root、checkpoint 崩潰續跑跳過已完成族、未知成本保留、用量與兩層帳本、超支拒收、取消及取消途中候選計費、逾時版本失敗、owner 隔離、relay／FIT 排除、原生守衛、結果交易回滾。前端另驗證 SEARCH HTTP 請求攜帶 revision、seed 與冪等鍵。

基線 50140e8 的 OpenAPI 實際已有 30 個 operations；本輪未修改 OpenAPI，也沒有新增 operation。盤點中的 29 是舊計數，以 `check_docs.py` 與基線契約實測 30 為準。

完整命令、測試數、服務與 HTTP 冒煙結果記錄於機器循證。Sonar 使用本機既有 AXIOM_SONAR_TOKEN 安全注入環境執行，完整結果與 Quality Gate 條件以機器循證為準；沒有修改規則或隱藏診斷。型別政策維持既有額度，不新增 Any／JsonObject 額度；同時收斂基線在 control fixture／validation 等處超額的標註。既有 JSON／ORM 動態邊界仍存在，strict 零診斷不代表全庫已消除動態型別。

T07 整體仍 IN_PROGRESS，產品 Gate NOT_RUN。FIT 執行管線、正式容量 SLO、時間／群組切分、外送與既有政策決策不屬本輪完成宣告。


關帳整合另以真實 PROFILE／封存→SEARCH→凍結→隔離最終評估驗證。CLOSING 僅對已成功 SEARCH 的固定最終評估開放剩額檢查；一般探索仍要求 OPEN，CLOSED 仍禁止新工作。凍結建立與最終結案共用研究帳本鎖，防止結案後再插入新待評估提交。提交聚合依完整 frozen_candidate_ids 計數，未建立的成員槽位仍視為未完成。

Sonar 清理只做保持行為的抽函式、移除未使用參數、共用字面常數及原生可及性標記；QR 主元交換、Householder 反射的迭代與算術順序不變，三策略排序與精度政策不變。


Sonar 最終診斷為 0，保留原規則與分析範圍。Quality Gate 的 coverage 條件未通過：專案尚未提供 coverage 報告，伺服器 new_coverage 為 0，門檻為 80；不把測試全綠或零診斷冒充 coverage gate 已通過。此既有驗證管線缺口另列於 T08／缺口清單。
