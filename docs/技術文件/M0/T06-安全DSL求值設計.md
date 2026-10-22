# T06｜安全 DSL 求值設計

日期：2026-10-20；owner／SELF_REVIEW：project-owner。承接 dcc367c，依 AX-10／12／26／28，先設計再實作。

## 介面與信任邊界

新增純 Python mathematics 套件，不需 DB migration。compile_dsl(bytes) 是唯一編譯入口，接受權威 dsl-v1 schema 的 JSON envelope，產生不可變 Plan（canonical bytes、SHA-256、輸出 SI 維度、節點數）。evaluate(plan, rows, parameters) 產生每列 value／valid_mask／reason，precision_bits=53；參數採十進位字串，資料列採有限 float／安全整數。不得使用 eval、exec、動態 import、SymPy 字串解析、網路或檔案操作。此輪無公開 HTTP 求值入口，後續接入仍須租戶分區與 access_class、Run 與 manifest。

先檢查傳輸 256KiB、JSON 容器深度32、重複 key、UTF-8／非有限／浮點常數，再檢查 AST 深度10（root=1）、節點1024、運算白名單，最後執行離線 schema 及語意檢查。宣告最多128項；十進位界限及 binding 最多128字元；有理數分子／分母最多128位。限制是本機安全預設，非效能或正式產品政策。

## 正規化與語意

變數／參數／domain 按名稱排序，名稱唯一且互不重疊，domain 必須完整覆蓋變數；有限上下界及開閉端點必須非空。參數上下界有序且包含實際 binding。七個 SI 維度依 AX-10 運算；pow 只接受常數整數 [-8,8]，分段條件只引用變數。

常數／域約分，十進位零與尾零正規化；add／mul 展平、排序並精確合併常數，其餘安全純有理運算折疊。中間有理數受位數上限限制，超限拒絕；非法常數運算保留原節點，求值時回 DOMAIN_VIOLATION。不消去 x/x、0*x、x^0 或未選分支，不產生整域等價宣稱。hash 包含完整 envelope，與參數擬合值分離。

分段保持原順序，只執行首個符合分支；即使未選分支也要先通過名稱／量綱／結構檢查。變數及參數先以精確有理比較界限，再轉 binary64。非有限、除零、log 非正、零的非正冪及可偵測下溢回 DOMAIN_VIOLATION，值留空，保留全部列。輸出量綱由編譯器推導。

## 資源、精度與測試

每批最多4096列、262144個保守節點訪問額度、1秒單調時鐘 deadline；超限不回部分成功。逐節點檢查 deadline，這是 cooperative 限制，不是 OS 強制沙箱。AST 和純固定運算均有界；正式 worker 的強制 CPU／RSS／取消 supervisor 仍待後續，不能因本輪通過就接受任意插件。float64 記53 bits，尚不自動升級精度；相消、非零的精度損失仍需後續 AX-12 診斷，不冒稱任意精度或量測準確度。

測試以 Fraction 的線性／有理值、Decimal 高精度 exp／log 及獨立 sine Taylor oracle 對照；另測所有 op、單位、域孔洞、未知符號、惡意 JSON、超深／超量 AST、符號／參數重名、越界、分段短路、hash 固定向量與不同域。測試 oracle 不被求值器匯入。CI 加入本套件測試，保留後端交易及 HTTP 回歸；strict Pyright、實際 Sonar 分析與文件檢查後才提交。

## 交付界線

T06 提供已知公式的本機受限求值器與獨立驗證，沒有搜尋、最佳化、符號證明、正式盲測或業務 SUCCEEDED 寫入。T07 接真實 INGEST、語意確認與研究版本。產品 gate 維持 NOT_RUN；回退可還原本提交，無資料表變更。
