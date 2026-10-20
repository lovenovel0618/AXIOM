# 文件整合紀錄

> 2026-10-20｜整合紀錄：原始基線 v2.1，現行 v2.9｜文件整合完成；產品仍處於設計階段

## 來源與結果

| 項目 | 處理方式 |
|---|---|
| `docs` 原有 42 篇編號章節 | 保留原領域細節、REQ／RISK／ADR 編號、架構圖及部署決策 |
| `AXIOM_Project` 的 41 篇同路徑章節 | 合併 v2 決策摘要、能力規格、異常處理、驗收與交付條件 |
| `AXIOM_Project/13-專題深化` 的 6 篇 | 整合至同名目錄，補充具體欄位、流程、操作與測試證據 |
| README／閱讀導航 | 重新整理完整索引、角色路徑與共用契約的權威位置 |
| MANIFEST | 依最終內容重建大小與 SHA-256，排除自身與 .DS_Store |
| 原始 `AXIOM_Project` | 整合後確認來源檔案皆有對應文件且校驗值正確，依使用者指示於 2026-10-19 刪除 |

## 編號與內容衝突處理

| 衝突 | 整合決策 |
|---|---|
| 原 AX-41 為 Docker，新來源 41 為研究物件契約 | Docker 保留 AX-41；研究物件契約改為 AX-47；42～46 不變 |
| macOS 開發與 Windows WSL2 架設決策在新來源未完整保留 | 沿用 ADR-006；正式叢集與 GPU 規格仍待確認 |
| 研究狀態有兩套列舉 | AX-04 採 v2 研究狀態；原細部處理階段移至 run.phase，停止原因另列 |
| E0～E3／P1～P2 與 v2 文字證據代碼並存 | AX-34 補相容規則，保留實證、證明雙軸及結果診斷 |
| 工作池名稱與排程等級不同 | AX-08 補等級到 light／search／precision／gpu／proof 的對應 |
| proof 禁止網路卻在原圖直連資料庫 | AX-41 改由可信 worker 以受限檔案輸入輸出交付，不提供 DB 憑證 |
| 原 ERD 的模型／訓練關係方向不符來源語意 | AX-43 改為 TrainingRun 產生 ModelVersion，並補版本與外鍵約束 |
| v2 每小節重複相同輸入輸出文字、表格間有空行 | 移除重複模板段落，保留實質限制；修復表格連續性 |

## 深化範圍

研究物件契約補上型別、版本與驗證產物；搜尋決策樹補上策略輸入及停止原因；ERD 補上唯一性、外鍵與跨儲存交易恢復；工作台補上頁面狀態和前端驗收；SLO 補上統計口徑與壓測步驟；發布矩陣補上逐 gate 案例、追溯欄位與回退要求。

新增細則是待實作的設計提案，不代表系統已經具備此能力。具體人員、期限、硬體、模型版本、容量門檻與正式部署方案依 AX-37 決策，不能用文件數量或篇幅代替產品驗收。

## 維護與校驗

原始 v2.1 整合有 48 篇編號章節，以及 README 和本紀錄，原始合併時共 50 份 Markdown。原始清單僅含 Markdown，因此 documents 當時等於 files 筆數；每筆 bytes 與 sha256 以對應檔案的原始位元組計算。後續變更應檢查連結存在、章節編號唯一、所有文件可由 README 到達、JSON 範例可解析及程式區塊成對，再重建 MANIFEST。

## v2.2 嚴謹性修訂（2026-10-19）

本輪重新審查原整合留下的語意衝突，取代不夠具體的模板，不宣稱產品已實作。

| 審查問題 | 已完成的規格修訂／驗證入口 | 尚待實作或決策 |
|---|---|---|
| 真值流入求解器 | AX-05／28 改三角色與雙資料流，補拒絕存取案例 | 實際 bucket／帳號與隔離測試 |
| 搜尋適應驗證集 | 固定 fit/development/final_test、一次凍結評估與污染退役規則 | 真實 evaluator／blind generator；D-03 |
| DSL 只有描述 | AX-10 語法／arity／域／單位／hash、schema 正反例 | parser、求值器、資源隔離與容差測試 |
| 數學判定模糊 | AX-28／13 指標公式、coverage、等效與拒答方法、公開 fixture | 領域量測模型與正式盲測門檻 |
| API／事件不完整 | AX-21 逐端點、冪等／ETag、錯誤碼、SSE 與離線 OpenAPI | 服務實作與產品契約測試 |
| 租約／取消競態 | AX-38 generation／row-lock／預算與 checkpoint 協定 | crash、重領、競態與成本測試 |
| 範圍與階段衝突 | AX-02／30 統一 M0～M7；M3 是互動 MVP | 具名人力、工期與 D-08 |
| 物件／ERD 不一致 | AX-47 逐物件必要欄位與 schema；AX-43 版本、複合 FK 與約束 | DB migrations 與跨租戶測試 |
| 驗收只有模板 | AX-46 全部 REQ 連到 AC；各章補專屬判定 | 案例皆 NOT_RUN；產品執行證據 |
| 部署／恢復不可照做 | AX-41 init/live/ready；AX-27 BackupSet、還原順序與撤銷重播 | Compose／管理命令與實際演練；D-06 |
| 權限／外送／撤銷模糊 | AX-26 身分、操作矩陣、分級、快取與模型隔離 | 真實政策批准與 D-04／05 |
| 重複模板掩蓋細節 | 共用規則集中 AX-48，移除重複泛用能力／流程／驗收段 | 後續變更依權威表持續維護 |

新增 contracts 與 docs/企劃案/tools/check_docs.py，供 schema、OpenAPI、範例、公開 oracle、追溯及檔案校驗。v2.2 為 49 篇編號章節、51 份 Markdown；manifest 現涵蓋 contracts 與工具，documents 不再等於 files 筆數，全部檔案數使用 file_count。文件通過不代表產品通過，G2／G7 的正式門檻未核准時保持 BLOCKED。

## v2.3 跨契約一致性修訂（2026-10-19）

| 本輪審查缺口 | 規格修正 | 可重現檢查 |
|---|---|---|
| AX-06仍畫proof直連DB | 區分可信supervisor與無網路sandbox；移除直接儲存邊 | 拓樸邊檢查＋AC-06-04 |
| Run／Attempt schema拒絕內部欄位 | public DTO與runtime Record分檔，明確allowlist投影 | 內外部正反例、共享欄位比對 |
| 父取消後子租約仍可提交 | root epoch、固定鎖順序、提交祖先檢查、遠端停止確認 | CF-05～08、CF-23～24與AC-38-05～10 |
| 家族與擬合公式評分混淆 | FrozenCandidate固定唯一FitRun/binding；FrozenSubmission hash | CF-01～04、CF-15～16／25 |
| 題目／觀測切分混用 | BenchmarkPartition、ObservationSplit、SealedTest獨立物件 | CF-09～12／21～22／26 |
| limit與usage混用且不允許零記憶體 | Limit、Reservation、Usage分型；累計／峰值及遲到計量定義 | 零Usage範例、CF-13～14／19 |
| 重新登入找不到研究 | 研究→版本→run導覽與凍結物件唯讀API | 文檔／OpenAPI雙向端點覆蓋，AC-21-05 |
| run關閉後收不到審核 | RUN與RESEARCH分scope/cursor，終態後只研究流續寫 | CF-17～18／20，AC-21-06～07 |

研究／內部schema及事件採2.0，HTTP為/api/v2，metric與觀測政策為2.0；DSL仍1.0。未部署v1草案以Git保留，本次沒有宣稱相容服務或資料遷移已執行。控制版本改用X-Control-Revision／If-Control-Revision，不把業務revision當整份動態回應的ETag；可變snapshot不作HTTP快取。冪等回放先重新授權，原操作結果與目前資源狀態分開讀取。

共49篇章節／51份Markdown，新增runtime契約與27組conformance參考情境，原AC編號保留並補充跨契約驗收。manifest涵蓋全部現行文件、契約與工具。參考情境通過不代表真實交易、worker、符號引擎、瀏覽器或正式發布已通過，產品狀態仍NOT_RUN，未決D-03／D-06等發布阻擋不變。

## v2.4 生命週期與還原缺口修訂（2026-10-20）

本輪完成六項跨契約修正：PROFILE取消／永久失敗回DRAFT；SEARCH_OPEN／FINAL_ONLY／CLOSED區分凍結與結束；封存測試先消耗後讀取、同提交故障恢復與不可逆退役；預註冊fit+development重擬合列與hash；研究快照證據／品質報告引用及審核唯讀API；Run結果與略過階段欄位、APPROVE／REJECT統一。同步修改公開／runtime／TaskInput／OpenAPI及fixture，擴充文件參考情境。契約仍是未部署2.0草案，產品與故障注入驗收仍NOT_RUN。

## v2.5 權限與觀測身分修訂（2026-10-20）

完成五項審查缺口：逐資源SEALED_DETAIL與聚合報告授權；FinalEvaluationSlot及最終結果partial unique／提交成員FK；觀測內容與可信來源雙token曝光ledger；依chronological_rank檢查時間gap；CreateResearchVersion／PROFILE／DSL固定ResearchDomain。公開、runtime、TaskInput及OpenAPI／fixture同步更新，文件工具增加原缺陷的回歸情境。全部仍為設計與參考裁決，實際授權、HMAC密鑰管理、多交易競態及產品驗收保持NOT_RUN。

## 文件工具型別與開發環境修正（2026-10-20）

補上兩支Python工具的函式／容器型別、JSON載入物件檢查與schema資料邊界；Registry使用SchemaRegistry，動態jsonschema驗證器經其Validator protocol提供已知介面。加入專案.venv設定、strict Pyright設定與鎖定的requirements-dev.txt，避免只在/tmp安裝依賴導致編輯器無法解析匯入。執行結果與靜態型別檢查分開驗證，未停用診斷規則，產品驗收仍NOT_RUN。

## 文件工具SonarQube重構（2026-10-20）

將集中情境分派改為具型別的handler表，分離時間／群組切分、域界、計量與重試裁決；文件檢查按Markdown、schema、OpenAPI與投影責任拆函式。抽出共用字串常數，改以單次掃描解析程式區塊及表格欄位，避免回溯型正規表示式。使用本機SonarQube for VS Code分析器檢查兩支工具，保持原規則啟用；另以strict Pyright、95個參考情境及Markdown正反例確認重構未破壞驗證行為。

## v2.5 文件治理補強（2026-10-20）

本輪修正文件層級的可驗證缺口，不改動產品範圍：AX-41 標頭對齊 v2.5，兩份落後標頭統一為現行版本；AX-02 新增 NFR-001～007 非功能需求編號，AX-46 補非功能需求追溯表與章節驗收覆蓋表，使全部 AC 皆可由發布矩陣追溯；AX-08／41 補上 D-02／D-09 阻擋引用。check_docs.py 增列標頭版本、AC 覆蓋與決策引用的回歸檢查。以上仍為設計與參考裁決，產品驗收保持NOT_RUN。

## v2.6 復原與研究輸入補強（2026-10-20）

補齊五項缺口：獨立ExposureJournal與復原高水位閘門；零候選／final額度不足的正常終止及診斷引用；不可變EvaluationPolicy與凍結hash；UTF-8來源欄映射；ResearchBudgetAccount與root兩層原子預算。保留本輪前已有的工作區部署／需求／交付補充，不以本次修訂覆蓋。同步schema、OpenAPI、fixture、追溯及文件工具，產品驗收仍NOT_RUN。

## v2.7 整體一致性修訂

以49章及全部契約作一體審查，記錄見REVIEW.md；新增單位轉換、永久作者與執行manifest、發布claim及獨立摘要導航，並補上有界匯入／恢復、計數及安全交付條件。來源整合範圍不變，原始AXIOM_Project仍由Git追溯。規格閉合與產品完成分開，所有實作驗收仍NOT_RUN。

## v2.8 四份自主研究討論的完整整合

原文完整保存於14-自主研究/sources，sha256與逐項採納見contracts/attachment-requests-v1.json；新增AX-49～52與REQ-011～014，涵蓋表徵、錯誤重審、正逆多軸驗證、Token／記憶及本地模型選型。原對話的建議和硬體／百分比示例不當成決策；權威規格明列修正與階段gate。文件現有53篇編號章節、56份Markdown，產品仍NOT_RUN，未下載模型或執行訓練。

## v2.9 可執行一致性審查

補齊metadata預覽與fit評估的分工、分級trace鏈、recipe／plan凍結、證據充分性、解集／因果前提、原觀測訓練分區、有效回退及嚴格JSON／canonical profile；九組可重現缺口列入REVIEW與機器追溯。章節仍53篇，原始四份附件bytes不變；新欄位仍是未部署草案修訂，產品驗收NOT_RUN。

## v2.9 治理補強：錯誤碼、能力與政策登錄（2026-10-20）

承接 v2.9 缺口審查，新增 contracts/error-codes-v1.json、capability-registry-v1.json 與 policy-registry-v1.json 三份單一真實來源，並新增 AX-53 工程治理與開發者工作流，定義權威、能力閘門、政策 Fail-Closed、目錄結構與 DoD。工具雙向校驗錯誤碼與 OpenAPI Error.code enum、能力與保留端點、政策與預設 BLOCKED，並將 OpenAPI 各操作的錯誤回應宣告統一。同步補全 AX-01 文件地圖與 AX-48 權威順序。文件現有54篇編號章節、57份Markdown，產品仍NOT_RUN。
