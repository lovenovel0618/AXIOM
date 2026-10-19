# 10｜公式DSL與等價正規化

> AXIOM v2.6 設計規格｜文件 ID AX-10｜狀態：待實作、待驗收｜2026-10-20

## DSL v1 範圍

v1 僅支援實數純量顯式函數；常數、變數、參數、add/sub/mul/div/pow/sin/cos/exp/log/abs/piecewise。AST 是權威，LaTeX 只作顯示。求和、遞迴、導數、積分、分布、ODE 皆屬後續 DSL 擴充，v1 輸入必須回 UNSUPPORTED_OPERATOR；M5/M6/M7 的能力不可偷偷用任意 Python 執行。

結構 schema 見 [dsl-v1.schema.json](<../contracts/dsl-v1.schema.json>)；合法範例與反例見 [dsl-v1.examples.json](<../contracts/dsl-v1.examples.json>)。schema 與以下語意驗證都通過才可生成求值計畫。

## 結構及序列化

Envelope 必填 dsl_version="1.0"、variables、parameters、domain、root。variables 是 name、unit 清單；parameters 另列 name、unit、lower、upper，有界值用十進位字串。名稱符合 ASCII 識別字，唯一且變數、參數名稱不得重疊。空 parameters 合法。domain 是每個輸入變數的上下界及開閉旗標；v1 要求有限上下界。

| 節點 op | 必填欄位 | arity／語意 |
|---|---|---|
| const | value | 有理數 {numerator,denominator}，分母為正整數，約分，零表示 0/1 |
| var / param | name | 必須引用已宣告名稱 |
| add / mul | args | 至少 2 個 child；正規化時展平同 op 與依 canonical bytes 排序 |
| sub / div / pow | args | 恰 2 個 child；pow 的指數只准常數整數，範圍 [-8,8] |
| sin / cos / exp / log / abs | args | 恰 1 個 child |
| piecewise | branches、otherwise | 1～8 個分支，按原順序首次符合者生效；otherwise 必填 |

piecewise condition 僅允許 {var, comparator, value}，comparator 為 lt/lte/gt/gte，value 是有理數且與該變數同單位。條件不能呼叫函數或存取宿主。const 本身是無量綱有理數；帶量綱係數以有單位的 param 宣告。unit 是七個 SI 基礎維度的整數指數，順序 [kg,m,s,A,K,mol,cd]，無量綱為全零；v1 不接受攝氏等帶位移單位，匯入時必須顯式轉換。未知單位先阻擋量綱驗證，使用者明確宣告無量綱才能繼續。

dtype、推導 unit、有效域及 cost 是驗證器輸出，不能信任輸入自填。canonical AST 不包含快取 cost 或顯示資訊。參數界限的十進位字串正規化為無冗餘前導／尾端零，零為 "0"（禁止 -0），域與常數有理數先約分。名稱排序按 UTF-8 bytes；JSON key 排序、無空白、UTF-8 序列化，禁止浮點 JSON 常數、NaN、Infinity。AST 深度上限 10、節點上限 1024、名稱長度 64、有理數各整數最多 128 位；超限回 AST_LIMIT_EXCEEDED。這些是可修訂的 v1 安全預設，不是效能測得值。

## 單位與定義域

add/sub 與所有 piecewise 分支的輸出量綱必須一致；mul/div 加減維度指數；pow 乘整數指數；sin/cos/exp/log 的輸入必須無量綱。abs 保留單位。domain 覆蓋 variables 的全部名稱；下界不得大於上界，單點域兩端都必須閉合。

div 分母為零、log 非正值、零的非正冪與非有限結果都回 DOMAIN_VIOLATION，不填 0 或靜默丟點。參數／變數界限可能使公式部分位置無定義時保留限制；求值逐點回 valid_mask 與錯誤原因。驗證集合只要有必評點無定義，該候選不得通過該集合，除非研究預註冊了該排除域且計入 coverage。piecewise 只對選中的分支求值，不能先求值所有分支而觸發不適用的非法運算。

## 正規化、身分與等價

1. 驗證結構、名稱、型別、單位、域與限制；常數按有理數精確運算折疊。
2. 展平及排序 add/mul；不做重新命名參數、不做會改變域的約分；其他代數等價交由 verifier 產生獨立關係。
3. identity_hash = SHA-256(canonical envelope bytes)。包含 DSL 版本、變數／參數宣告、完整 domain 與 root，不包含參數擬合值。不同域不得碰撞。
4. 符號等價狀態為 PROVEN_EQUIVALENT／DISPROVEN／UNKNOWN；只有保存前提與推導證據後才標前者。UNKNOWN 不等於近似等價。
5. 數值近似另存測試點集 hash、atol、rtol、精度與 max error。每點要求 |a-b| <= atol+rtol*max(|a|,|b|)，任何不合法點算失敗；只描述該點集上的數值一致，不推論整域等價。

x/x 與 1 在包含 0 的原始域不能合併；sqrt(x²) 等擴充式不得直接當作 x。超時回 UNKNOWN，不當成反證。前端 AST JSON round-trip 才要求身分 hash 不變；LaTeX 不保證可無損還原，不能當匯入權威。

## 驗收

| ID | 輸入 | 預期結果 |
|---|---|---|
| AC-10-01 | add(x,1) 與 add(1,x)，x 無量綱同域 | 同 canonical bytes/hash，x=2 結果精確 3 |
| AC-10-02 | div(1,0)、log(-1)、pow(x,9)、未知 op | 前兩者 DOMAIN_VIOLATION；後兩者分別 AST_LIMIT_EXCEEDED、UNSUPPORTED_OPERATOR |
| AC-10-03 | div(x,x)，域 [-1,1]，對比 const 1 | 不合併；x=0 的 valid_mask=false；無整域等價證據 |
| AC-10-04 | add(var_length,var_time)、超深 AST、未知變數 | 分別 UNIT_MISMATCH、AST_LIMIT_EXCEEDED、UNKNOWN_SYMBOL |

M1 必須逐條執行；fixture 檢查不能取代安全執行器與數值測試。證據語義見 AX-34，租戶內身分與版本關係見 AX-43／47。

## 固定研究域、公式域與外插

ResearchVersion.domain／CreateResearchVersion.domain使用ResearchDomain，形狀與DSL domain一致；MVP唯一輸入名必與semantic_profile相同，有限有理界、上下界順序與開閉旗標經語意驗證。使用者須在啟動前顯式確認。UI可由fit資料提出[min,max]建議，但不讀development／final來擴大預設域，也不自動接受建議；固定域須容納研究宣告的觀測。PROFILE可信服務檢查三區輸入值均在域內，正式封存資料不向Solver透露越界點、極值或labels，只提供經遮罩的阻擋原因。

MVP每個EquationVersion.dsl.domain必等於所屬研究的canonical domain，不能由插件縮到容易通過的子域；運算造成的孔洞另以DOMAIN_VIOLATION／valid_mask與coverage處理，不透過改域排除失敗點。domain參與EquationVersion identity_hash，研究域不可原地變更；所有FIT／VALIDATE／FrozenCandidate沿研究及公式引用核對域。單點域只有兩端閉合才非空；非法域在計算前拒絕。

觀測域是允許求值及聲明的固定範圍；訓練支撐範圍是fit觀測的覆蓋；兩者之間可顯示為外插且不能提高證據。超出固定domain不執行DSL求值，UI標示域外並留空，不能因拖曳圖表暗中擴域。需要新範圍必另建研究版本，並重新審查資料與驗證資格。
