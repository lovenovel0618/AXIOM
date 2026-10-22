# T07 刪除傳播與 tombstone 設計

狀態：IMPLEMENTED（限本批權威側失效宣告與有效性回查）；T07 仍為 IN_PROGRESS。本批把「來源已失效」變成權威事實並擋住衍生讀取，不宣稱索引／快取已清除，也不開啟對外刪除 API。

## 交付邊界

新增 Tombstone／DeletionRequest／DeletionTarget 三張表與 `catalog/deletion.py`，不新增對外端點。AX-43 明訂 MVP 不提供資料硬刪除 API，且 D-05 未定保留與刪除政策前只允許受控的隔離／tombstone；失效宣告因此走服務層，經既有讀取路徑生效，不由客戶端指定要刪什麼。

AX-26 要求刪除先在權威 DB 同交易新增 tombstone、禁止推薦，且所有推薦與報告下載都回查權威有效性、不能只信快取 TTL。本批以單一交易寫入 tombstone、刪除工作與逐項受影響物件；`GET /api/v2/artifacts/{id}`、`GET /api/v2/artifacts/{id}/content` 與 `GET /api/v2/evidence-bundles/{id}` 沿用既有授權路徑，在授權時一併回查 tombstone，已失效者不再因 UUID、舊列表或快取而可讀。目前沒有推薦端點，故涵蓋範圍是下載與讀取，不宣稱推薦已實作。

請求以研究來源（DatasetVersion）為根，依 lineage 逐層列舉：DatasetVersion→其 raw／preview Artifact→引用該版本的 ResearchVersion→這些版本的 EvidenceBundle→掛在這些版本的其餘 Artifact。AX-26 所列記憶 embedding／快取、報告、訓練快照與模型版本目前不存在，不為它們偽造受影響物件列。

## 刪除工作與阻擋

狀態值域固定為 REQUESTED／BLOCKED／PROPAGATING／COMPLETED／FAILED，與 AX-26 逐字一致；受影響物件、動作、重試次數與錯誤逐項保存，供清理後查核，不把失敗收斂成單一分數。

Fail-Closed 由資料庫強制：政策的 `policy_status` 不是 ACTIVE 時，任何轉入 PROPAGATING 或 COMPLETED 的寫入一律拒絕，因此政策未決前刪除工作只能停在 BLOCKED 並帶 `FEATURE_DISABLED`，不悄悄選擇永久保留或全部刪光。COMPLETED 另要求該請求下不存在未完成的受影響物件，部分清理失敗不得顯示完成。

tombstone 於請求建立時立即生效，與政策是否放行無關；這是「立即停止推薦」的最小安全性質，即使後續傳播被阻擋也不回退，也不因來源退役而自動改變分類。

## 儲存不變條件與驗證

0015 建三表：Tombstone 以 (tenant, object_type, object_id) 唯一，DeletionTarget 以 (deletion_request, object_type, object_id, action) 唯一，DeletionRequest 以 (id, tenant) 唯一並限定狀態值域。0016 補 native 複合 FK（dataset_version 指向 (id, tenant)，DEFERRABLE INITIALLY DEFERRED，對齊既有慣例）、BEFORE INSERT／UPDATE guard（根目標與 tenant 不可改、revision 僅 +1、狀態只走白名單轉移、policy 未放行不得進 PROPAGATING／COMPLETED、COMPLETED 需無未完成項）與 tombstone 的 BEFORE UPDATE／DELETE 不可變觸發器。

測試以真正 PostgreSQL 與合成資料，涵蓋跨租戶根目標 FK 拒絕、tombstone 不可改與不可刪、非法狀態轉移、policy 未放行時不得進 PROPAGATING 或 COMPLETED、以及宣告後既有讀取與下載由 200 轉為 409／404。真 HTTP smoke 走上傳→INGEST→草案→PROFILE→READY→證據包→失效宣告→讀取被擋，直連與前端同源代理各一次。完整後端／工具檢查、嚴格型別、文件檢查後 commit／push，並核對該 commit 的 CI。

明確不在本批：對外刪除 API 與端點、outbox 事件、異步清除索引與快取、訓練快照移出與模型 QUARANTINED、備份的 tombstone 清單與還原重播、actor tombstone、validation 引用、SEARCH 與候選比較。
