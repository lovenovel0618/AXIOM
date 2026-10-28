/**
 * SSOT 頁面註冊表：把 docs/AXIOM_UIUX_重製版/assets/pages.json 的 40 頁對到前台路由。
 *
 * 左側導覽高亮與頂部麵包屑都由此表推導，不再各自維護一份 if 串；逐頁驗收測試
 * （tests/ssotPages.test.ts）以 pages.json 為權威比對 `ssotTitle`，任何一邊改動都會失敗。
 * `title` 是前台顯示標題：SSOT 原標題含英文專有名詞時只在此處中文化，維持介面全繁中。
 */
export interface SsotPage {
  /** SSOT 頁碼 01–40；前台專屬支援頁為 0。 */
  id: number
  routeName: string
  /** 左側導覽高亮所屬的模組，對應 App.vue 的 primaryNav 標籤。 */
  navLabel: string
  /** 麵包屑模組層級，沿用 pages.json 的 category（支援頁沿用所在模組）。 */
  category: string
  /** 前台顯示標題。 */
  title: string
  /** pages.json 的原始標題，須逐字相同。 */
  ssotTitle: string
}

export const SSOT_PAGES: readonly SsotPage[] = [
  { id: 1, routeName: 'overview', navLabel: '總覽', category: '總覽', title: '系統總覽', ssotTitle: '系統總覽' },
  { id: 2, routeName: 'activity', navLabel: '活動中心', category: '總覽', title: '研究活動中心', ssotTitle: '研究活動中心' },
  { id: 3, routeName: 'pending', navLabel: '待處理事件', category: '總覽', title: '待處理事件', ssotTitle: '待處理事件' },
  { id: 4, routeName: 'resources', navLabel: '資源監控', category: '總覽', title: '資源監控', ssotTitle: '資源監控' },
  { id: 5, routeName: 'research-list', navLabel: '研究', category: '研究', title: '研究清單', ssotTitle: '研究清單' },
  { id: 6, routeName: 'research-create', navLabel: '研究', category: '研究', title: '新建研究', ssotTitle: '新建研究' },
  { id: 7, routeName: 'research-workbench', navLabel: '研究', category: '研究', title: '研究工作台', ssotTitle: '研究工作台' },
  { id: 8, routeName: 'research-detail', navLabel: '研究', category: '研究', title: '研究詳情', ssotTitle: '研究詳情' },
  { id: 9, routeName: 'research-graph', navLabel: '研究', category: '研究', title: '研究分支圖', ssotTitle: '研究分支圖' },
  { id: 10, routeName: 'research-timeline', navLabel: '研究', category: '研究', title: '研究任務紀錄', ssotTitle: '研究任務紀錄' },
  { id: 11, routeName: 'datasets', navLabel: '數據', category: '數據', title: '資料集清單', ssotTitle: '資料集清單' },
  { id: 12, routeName: 'data-upload', navLabel: '數據', category: '數據', title: '資料上傳精靈', ssotTitle: '資料上傳精靈' },
  { id: 13, routeName: 'data-preview', navLabel: '數據', category: '數據', title: '資料預覽', ssotTitle: '資料預覽' },
  { id: 14, routeName: 'data-quality', navLabel: '數據', category: '數據', title: '資料品質', ssotTitle: '資料品質' },
  { id: 15, routeName: 'data-pipeline', navLabel: '數據', category: '數據', title: '前處理管線', ssotTitle: '前處理管線' },
  { id: 16, routeName: 'data-explore', navLabel: '數據', category: '數據', title: '多維探索', ssotTitle: '多維探索' },
  { id: 17, routeName: 'data-diff', navLabel: '數據', category: '數據', title: '資料版本比較', ssotTitle: '資料版本比較' },
  { id: 18, routeName: 'discoveries', navLabel: '發現', category: '發現', title: '候選公式庫', ssotTitle: '候選公式庫' },
  { id: 19, routeName: 'discovery-compare', navLabel: '發現', category: '發現', title: '公式比較', ssotTitle: '公式比較' },
  { id: 20, routeName: 'discovery-latent', navLabel: '發現', category: '發現', title: '隱藏變數探索', ssotTitle: '隱藏變數探索' },
  { id: 21, routeName: 'discovery-derivation', navLabel: '發現', category: '發現', title: '研究推演', ssotTitle: '研究推演' },
  { id: 22, routeName: 'verification', navLabel: '驗證', category: '驗證', title: '驗證中心', ssotTitle: '驗證中心' },
  { id: 23, routeName: 'verification-falsify', navLabel: '驗證', category: '驗證', title: '反例搜尋', ssotTitle: '反例搜尋' },
  { id: 24, routeName: 'verification-inverse', navLabel: '驗證', category: '驗證', title: '逆向推導', ssotTitle: '逆向推導' },
  { id: 25, routeName: 'verification-proof', navLabel: '驗證', category: '驗證', title: '形式化證明', ssotTitle: '形式化證明' },
  { id: 26, routeName: 'verification-graph', navLabel: '驗證', category: '驗證', title: '證據關聯圖', ssotTitle: '證據關聯圖' },
  { id: 27, routeName: 'memory', navLabel: '記憶', category: '記憶', title: '知識庫', ssotTitle: '知識庫' },
  { id: 28, routeName: 'memory-experience', navLabel: '記憶', category: '記憶', title: '研究經驗', ssotTitle: '研究經驗' },
  { id: 29, routeName: 'memory-failure', navLabel: '記憶', category: '記憶', title: '失敗案例', ssotTitle: '失敗案例' },
  { id: 30, routeName: 'memory-recovery', navLabel: '記憶', category: '記憶', title: '假設恢復', ssotTitle: '假設恢復' },
  { id: 31, routeName: 'memory-evolution', navLabel: '記憶', category: '記憶', title: '知識演化', ssotTitle: '知識演化' },
  { id: 32, routeName: 'model', navLabel: '模型', category: '模型', title: '模型管理', ssotTitle: 'Ollama 模型管理' },
  { id: 33, routeName: 'model-routing', navLabel: '模型', category: '模型', title: '模型路由', ssotTitle: '模型路由' },
  { id: 34, routeName: 'model-evaluation', navLabel: '模型', category: '模型', title: '模型能力評估', ssotTitle: '模型能力評估' },
  { id: 35, routeName: 'model-storage', navLabel: '模型', category: '模型', title: '用量與儲存', ssotTitle: 'Token 與儲存' },
  { id: 36, routeName: 'training', navLabel: '訓練', category: '訓練', title: '訓練資料集', ssotTitle: '訓練資料集' },
  { id: 37, routeName: 'training-finetune', navLabel: '訓練', category: '訓練', title: '微調任務', ssotTitle: '微調任務' },
  { id: 38, routeName: 'training-release', navLabel: '訓練', category: '訓練', title: '模型版本發布', ssotTitle: '模型版本發布' },
  { id: 39, routeName: 'settings', navLabel: '設定', category: '設定', title: '系統與安全設定', ssotTitle: '系統與安全設定' },
  { id: 40, routeName: 'settings-research', navLabel: '設定', category: '設定', title: '研究策略設定', ssotTitle: '研究策略設定' },
]

/** 前台專屬支援頁：SSOT 40 頁之外的細節頁，沿用所在模組。 */
export const SUPPORT_PAGES: readonly SsotPage[] = [
  { id: 0, routeName: 'candidate', navLabel: '發現', category: '發現', title: '候選公式', ssotTitle: '候選公式' },
  { id: 0, routeName: 'run', navLabel: '驗證', category: '驗證', title: '任務詳情', ssotTitle: '任務詳情' },
  { id: 0, routeName: 'artifact', navLabel: '驗證', category: '驗證', title: '產物詳情', ssotTitle: '產物詳情' },
  { id: 0, routeName: 'login', navLabel: '登入', category: '登入', title: '登入', ssotTitle: '登入' },
]

const BY_ROUTE = new Map<string, SsotPage>(
  [...SSOT_PAGES, ...SUPPORT_PAGES].map((page) => [page.routeName, page]),
)

/** 依路由名稱取頁面註冊資料；未知路由回 undefined，呼叫端自行決定回退。 */
export function pageForRoute(name: unknown): SsotPage | undefined {
  return typeof name === 'string' ? BY_ROUTE.get(name) : undefined
}
