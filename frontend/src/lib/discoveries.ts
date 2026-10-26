import type { Candidate, CandidatePage, EquationVersion, FitRun, ValidationStatus } from '../api/candidates'
import type {
  Baseline,
  ComparisonMethod,
  ErrorModel,
  Research,
  ResearchPage,
  ResearchVersion,
  ResearchVersionPage,
  RunPage,
} from '../api/research'
import type { Run } from '../api/runs'
import { formulaComplexity, renderDomain, renderFormula } from './formula'

/** 後端未回報的欄位一律顯示這個字串，不以 0 或推測值代替。 */
export const DISCOVERY_UNKNOWN = '未取得'

export const VALIDATION_STATUS_LABELS: Record<ValidationStatus, string> = {
  NOT_RUN: '尚未執行',
  PENDING: '進行中',
  FINISHED: '已完成',
  INVALID: '無效',
}

export const DISCOVERY_CANDIDATE_LIMIT = 50
export const RESEARCHES_READ = 12
export const VERSIONS_PER_RESEARCH = 5
export const RECENT_VERSIONS_READ = 10
export const RUNS_PER_VERSION = 10

export interface DiscoverySearchRun {
  run: Run
  research: Research | null
  version: ResearchVersion | null
  candidates: Candidate[]
}

export interface DiscoveriesMetric {
  label: string
  value: string
  tone: 'good' | 'warn' | 'bad' | 'neutral'
  detail: string
}

/** 後端沒有全域候選端點，所有統計都只涵蓋實際讀取到的頁面；`truncated` 為真時必須在畫面明示。 */
export interface DiscoveryScope {
  researchesRead: number
  versionsRead: number
  versionIds: string[]
  searchRunsRead: number
  candidatesRead: number
  truncated: boolean
}

export interface DiscoveriesCenter {
  metrics: DiscoveriesMetric[]
  searchRuns: DiscoverySearchRun[]
  recentVersions: ResearchVersion[]
  scope: DiscoveryScope
}

export interface DiscoveriesDeps {
  listResearches: (limit: number) => Promise<ResearchPage>
  listResearchVersions: (researchId: string, limit: number) => Promise<ResearchVersionPage>
  listResearchVersionRuns: (versionId: string, limit: number) => Promise<RunPage>
  listRunCandidates: (runId: string, limit: number) => Promise<CandidatePage>
  getEquationVersion: (id: string) => Promise<EquationVersion>
  getFitRun: (id: string) => Promise<FitRun>
}

export interface CandidateDetailBundle {
  equations: Record<string, EquationVersion>
  fits: Record<string, FitRun>
}

function desc(left: string, right: string): number {
  if (left === right) return 0
  return left < right ? 1 : -1
}

export function takeRecent<T extends { created_at: string }>(rows: T[], limit: number): T[] {
  return [...rows].sort((left, right) => desc(left.created_at, right.created_at)).slice(0, limit)
}

async function safe<T>(task: Promise<T>, fallback: T): Promise<T> {
  try {
    return await task
  } catch {
    return fallback
  }
}

const EMPTY_RESEARCH_PAGE: ResearchPage = { items: [], next_cursor: null }
const EMPTY_VERSION_PAGE: ResearchVersionPage = { items: [], next_cursor: null }
const EMPTY_RUN_PAGE: RunPage = { items: [], next_cursor: null }
const EMPTY_CANDIDATE_PAGE: CandidatePage = { items: [], next_cursor: null }

export async function loadDiscoveriesCenter(deps: DiscoveriesDeps): Promise<DiscoveriesCenter> {
  const researchPage = await safe(deps.listResearches(RESEARCHES_READ), EMPTY_RESEARCH_PAGE)
  const researches = researchPage.items

  const researchEntries = await Promise.all(
    researches.map(async (research) => {
      const page = await safe(deps.listResearchVersions(research.id, VERSIONS_PER_RESEARCH), EMPTY_VERSION_PAGE)
      return [research.id, page] as const
    }),
  )
  const versionsByResearch = Object.fromEntries(researchEntries.map(([id, page]) => [id, page.items]))
  const allVersions = Object.values(versionsByResearch).flat()
  const recentVersions = takeRecent(allVersions, RECENT_VERSIONS_READ)

  const searchRuns: DiscoverySearchRun[] = []
  let truncated = researchPage.next_cursor !== null || researchEntries.some(([, page]) => page.next_cursor !== null)

  for (const version of recentVersions) {
    const research = researches.find((row) => row.id === version.research_id) ?? null
    const runPage = await safe(deps.listResearchVersionRuns(version.id, RUNS_PER_VERSION), EMPTY_RUN_PAGE)
    if (runPage.next_cursor !== null) truncated = true
    const rows = runPage.items
      .filter((run) => run.type === 'SEARCH')
      .sort((left, right) => desc(left.created_at, right.created_at))

    for (const run of rows) {
      const candidatePage = await safe(deps.listRunCandidates(run.id, DISCOVERY_CANDIDATE_LIMIT), EMPTY_CANDIDATE_PAGE)
      if (candidatePage.next_cursor !== null) truncated = true
      searchRuns.push({
        run,
        research,
        version,
        candidates: candidatePage.items,
      })
    }
  }

  const loadedCandidates = searchRuns.reduce((total, row) => total + row.candidates.length, 0)
  const runsWithCandidates = searchRuns.filter((row) => row.candidates.length > 0).length
  const versionsWithFrozen = recentVersions.filter((row) => row.frozen_submission_ids.length > 0).length

  return {
    metrics: [
      {
        label: 'SEARCH 任務',
        value: String(searchRuns.length),
        tone: searchRuns.length > 0 ? 'good' : 'warn',
        detail: '最近研究版本中可讀取的 SEARCH 任務數量。',
      },
      {
        label: '已載入候選',
        value: String(loadedCandidates),
        tone: loadedCandidates > 0 ? 'good' : 'warn',
        detail: '目前已實際抓到的候選頁面總和，不推測未載入頁面。',
      },
      {
        label: '有分支任務',
        value: String(runsWithCandidates),
        tone: runsWithCandidates > 0 ? 'good' : 'warn',
        detail: '至少有一條候選的 SEARCH 任務數量。',
      },
      {
        label: '已凍結版本',
        value: String(versionsWithFrozen),
        tone: versionsWithFrozen > 0 ? 'good' : 'warn',
        detail: '最近研究版本中已進入 frozen submission 的數量。',
      },
    ],
    searchRuns: searchRuns.sort((left, right) => desc(left.run.created_at, right.run.created_at)),
    recentVersions,
    scope: {
      researchesRead: researches.length,
      versionsRead: allVersions.length,
      versionIds: recentVersions.map((version) => version.id),
      searchRunsRead: searchRuns.length,
      candidatesRead: loadedCandidates,
      truncated,
    },
  }
}

export async function loadCandidateDetails(
  deps: DiscoveriesDeps,
  candidates: Candidate[],
  existing: CandidateDetailBundle,
): Promise<CandidateDetailBundle> {
  const next: CandidateDetailBundle = {
    equations: { ...existing.equations },
    fits: { ...existing.fits },
  }

  const equationIds = [...new Set(candidates.map((row) => row.equation_version_id))]
  const fitIds = [...new Set(candidates.flatMap((row) => row.fit_run_ids))]

  await Promise.all(
    equationIds.map(async (id) => {
      if (next.equations[id] !== undefined) return
      try {
        next.equations[id] = await deps.getEquationVersion(id)
      } catch {
        // 單筆缺失保持空白，不用推測公式內容。
      }
    }),
  )

  await Promise.all(
    fitIds.map(async (id) => {
      if (next.fits[id] !== undefined) return
      try {
        next.fits[id] = await deps.getFitRun(id)
      } catch {
        // 單筆缺失保持空白，不用推測擬合參數。
      }
    }),
  )

  return next
}

/**
 * 候選公式庫只需要公式 AST 就能呈現排序、複雜度與適用條件；擬合內容留到單列展開或比較頁再抓，
 * 避免一次替每條候選發出擬合請求。單筆讀取失敗保持未載入，不用推測公式內容。
 */
export async function loadCandidateEquations(
  getEquationVersion: (id: string) => Promise<EquationVersion>,
  candidates: Candidate[],
  existing: Record<string, EquationVersion>,
): Promise<Record<string, EquationVersion>> {
  const next: Record<string, EquationVersion> = { ...existing }
  const ids = [...new Set(candidates.map((row) => row.equation_version_id))]

  await Promise.all(
    ids.map(async (id) => {
      if (next[id] !== undefined) return
      try {
        next[id] = await getEquationVersion(id)
      } catch {
        // 單筆缺失保持未載入。
      }
    }),
  )

  return next
}

/** 候選公式庫的一列；公式相關欄位在 AST 未載入時一律為 null，由畫面顯示「未取得」。 */
export interface DiscoveryCatalogRow {
  candidateId: string
  equationVersionId: string
  source: string
  developmentRank: number | null
  validationStatus: ValidationStatus
  runId: string
  researchId: string | null
  researchName: string
  versionId: string | null
  createdAt: string
  formula: string | null
  complexity: number | null
  variableCount: number | null
  parameterCount: number | null
  domain: string | null
  fitRunCount: number
  validationRunCount: number
}

/** 每條候選只由 SEARCH 任務的既有欄位與其公式版本組出，不引入未揭露的分數。 */
export function buildDiscoveryCatalogRows(
  center: DiscoveriesCenter,
  equations: Record<string, EquationVersion>,
): DiscoveryCatalogRow[] {
  const rows: DiscoveryCatalogRow[] = []

  for (const entry of center.searchRuns) {
    for (const candidate of entry.candidates) {
      const equation = equations[candidate.equation_version_id]
      rows.push({
        candidateId: candidate.id,
        equationVersionId: candidate.equation_version_id,
        source: candidate.source,
        developmentRank: candidate.development_rank,
        validationStatus: candidate.validation_status,
        runId: entry.run.id,
        researchId: entry.research?.id ?? null,
        researchName: entry.research?.name ?? '未命名研究',
        versionId: entry.version?.id ?? null,
        createdAt: candidate.created_at,
        formula: equation === undefined ? null : renderFormula(equation.dsl.root),
        complexity: equation === undefined ? null : formulaComplexity(equation.dsl.root),
        variableCount: equation === undefined ? null : equation.dsl.variables.length,
        parameterCount: equation === undefined ? null : equation.dsl.parameters.length,
        domain: equation === undefined ? null : renderDomain(equation.dsl.domain),
        fitRunCount: candidate.fit_run_ids.length,
        validationRunCount: candidate.validation_run_ids.length,
      })
    }
  }

  return sortDiscoveryCatalogRows(rows, 'RANK_ASC')
}

export type DiscoverySort =
  | 'RANK_ASC'
  | 'RANK_DESC'
  | 'COMPLEXITY_ASC'
  | 'COMPLEXITY_DESC'
  | 'STATUS'
  | 'CREATED_DESC'

export const DISCOVERY_SORT_OPTIONS: Array<{ value: DiscoverySort; label: string }> = [
  { value: 'RANK_ASC', label: '發展排名（前→後）' },
  { value: 'RANK_DESC', label: '發展排名（後→前）' },
  { value: 'COMPLEXITY_ASC', label: '模型複雜度（低→高）' },
  { value: 'COMPLEXITY_DESC', label: '模型複雜度（高→低）' },
  { value: 'STATUS', label: '驗證狀態（已完成優先）' },
  { value: 'CREATED_DESC', label: '建立時間（新→舊）' },
]

const STATUS_ORDER: Record<ValidationStatus, number> = {
  FINISHED: 0,
  PENDING: 1,
  NOT_RUN: 2,
  INVALID: 3,
}

/** 缺少排名的列一律排到最後，不用 0 或推測值頂替。 */
export function sortDiscoveryCatalogRows(rows: DiscoveryCatalogRow[], sort: DiscoverySort): DiscoveryCatalogRow[] {
  const sorted = [...rows]
  const byRank = (left: DiscoveryCatalogRow, right: DiscoveryCatalogRow): number => {
    if (left.developmentRank === null && right.developmentRank === null) return desc(left.createdAt, right.createdAt)
    if (left.developmentRank === null) return 1
    if (right.developmentRank === null) return -1
    return left.developmentRank - right.developmentRank || desc(left.createdAt, right.createdAt)
  }

  switch (sort) {
    case 'RANK_DESC':
      return sorted.sort((left, right) => -byRank(left, right))
    case 'COMPLEXITY_ASC':
      return sorted.sort((left, right) => {
        if (left.complexity === null && right.complexity === null) return byRank(left, right)
        if (left.complexity === null) return 1
        if (right.complexity === null) return -1
        return left.complexity - right.complexity || byRank(left, right)
      })
    case 'COMPLEXITY_DESC':
      return sorted.sort((left, right) => {
        if (left.complexity === null && right.complexity === null) return byRank(left, right)
        if (left.complexity === null) return 1
        if (right.complexity === null) return -1
        return right.complexity - left.complexity || byRank(left, right)
      })
    case 'STATUS':
      return sorted.sort((left, right) => STATUS_ORDER[left.validationStatus] - STATUS_ORDER[right.validationStatus] || byRank(left, right))
    case 'CREATED_DESC':
      return sorted.sort((left, right) => desc(left.createdAt, right.createdAt))
    default:
      return sorted.sort(byRank)
  }
}

export function filterDiscoveryCatalogRows(
  rows: DiscoveryCatalogRow[],
  keyword: string,
  status: 'ALL' | ValidationStatus,
): DiscoveryCatalogRow[] {
  const query = keyword.trim().toLowerCase()
  return rows.filter((row) => {
    if (status !== 'ALL' && row.validationStatus !== status) return false
    if (query === '') return true
    return (
      row.candidateId.toLowerCase().includes(query) ||
      row.source.toLowerCase().includes(query) ||
      row.researchName.toLowerCase().includes(query) ||
      (row.formula ?? '').toLowerCase().includes(query)
    )
  })
}

export function summarizeDiscoveryStatus(rows: DiscoveryCatalogRow[]): Record<ValidationStatus, number> {
  const counts: Record<ValidationStatus, number> = { NOT_RUN: 0, PENDING: 0, FINISHED: 0, INVALID: 0 }
  for (const row of rows) counts[row.validationStatus] += 1
  return counts
}

const DISCOVERY_CSV_HEADER = [
  'candidate_id',
  'research_id',
  'research_name',
  'version_id',
  'search_run_id',
  'source',
  'development_rank',
  'validation_status',
  'formula',
  'complexity',
  'variables',
  'parameters',
  'domain',
  'fit_run_count',
  'validation_run_count',
  'created_at',
]

function discoveryCsvCell(value: string | number | null): string {
  if (value === null) return DISCOVERY_UNKNOWN
  const text = typeof value === 'number' ? String(value) : value
  return `"${text.replaceAll('"', '""')}"`
}

/** 匯出目前視圖；欄位與表格一致，未載入欄位一律寫成「未取得」。 */
export function buildDiscoveryCatalogCsv(rows: DiscoveryCatalogRow[]): string {
  const lines = [DISCOVERY_CSV_HEADER.join(',')]
  for (const row of rows) {
    lines.push(
      [
        discoveryCsvCell(row.candidateId),
        discoveryCsvCell(row.researchId),
        discoveryCsvCell(row.researchName),
        discoveryCsvCell(row.versionId),
        discoveryCsvCell(row.runId),
        discoveryCsvCell(row.source),
        discoveryCsvCell(row.developmentRank),
        discoveryCsvCell(row.validationStatus),
        discoveryCsvCell(row.formula),
        discoveryCsvCell(row.complexity),
        discoveryCsvCell(row.variableCount),
        discoveryCsvCell(row.parameterCount),
        discoveryCsvCell(row.domain),
        discoveryCsvCell(row.fitRunCount),
        discoveryCsvCell(row.validationRunCount),
        discoveryCsvCell(row.createdAt),
      ].join(','),
    )
  }
  return `${lines.join('\r\n')}\r\n`
}

export const COMPARISON_METHOD_LABELS: Record<ComparisonMethod, string> = {
  IID_PAIRED_BOOTSTRAP: '配對重抽樣（IID）',
  BLOCK_BOOTSTRAP: '區塊重抽樣',
  NONE: '未設定',
}

export const ERROR_MODEL_LABELS: Record<ErrorModel, string> = {
  EXACT: '精確',
  ABSOLUTE_BOUND: '絕對誤差界',
  UNSPECIFIED: '未指定',
}

export const BASELINE_LABELS: Record<Baseline, string> = {
  ZERO: '零基準',
  FIT_MEAN: '擬合平均基準',
}

export interface ComparisonFact {
  label: string
  value: string
}

/** 公平比較的前提：兩條候選是否在同一份切分上比較。缺版本時回空陣列。 */
export function buildComparisonContextRows(version: ResearchVersion | null): ComparisonFact[] {
  if (version === null) return []
  const split = version.observation_split
  return [
    { label: '資料集版本', value: version.dataset_version_id },
    { label: '切分方式', value: split.kind },
    { label: 'fit 列數', value: String(split.fit.length) },
    { label: 'development 列數', value: String(split.development.length) },
    { label: 'final_test 列數', value: String(split.final_test.length) },
    { label: '封存 final_test', value: split.sealed_final_test ? '已封存' : '未封存' },
    { label: '列集合雜湊', value: split.row_ids_hash },
    { label: '切分器版本', value: split.splitter_version },
  ]
}

/** 公平比較設定：全部取自研究版本的評估政策；缺值一律「未取得」，不套用預設。 */
export function buildFairComparisonRows(version: ResearchVersion | null): ComparisonFact[] {
  if (version === null) return []
  const policy = version.evaluation_policy
  return [
    { label: '指標版本', value: policy.metric_version },
    { label: '政策版本', value: policy.policy_version },
    { label: '比較方法', value: `${COMPARISON_METHOD_LABELS[policy.comparison_method]}（${policy.comparison_method}）` },
    { label: '誤差模型', value: `${ERROR_MODEL_LABELS[policy.error_model]}（${policy.error_model}）` },
    { label: '絕對誤差上界', value: policy.absolute_error_bound ?? DISCOVERY_UNKNOWN },
    { label: '重抽樣次數', value: String(policy.bootstrap_replicates) },
    { label: '重抽樣種子', value: String(policy.bootstrap_seed) },
    { label: '區塊方法', value: policy.block_method ?? '未使用' },
    { label: '區塊長度', value: policy.block_length === null ? '未使用' : String(policy.block_length) },
    { label: '實務邊界比例', value: policy.practical_margin_ratio },
    { label: '實務尺度覆寫', value: policy.practical_scale_override ?? DISCOVERY_UNKNOWN },
    { label: '實務尺度理由', value: policy.practical_scale_reason ?? DISCOVERY_UNKNOWN },
    { label: '基準', value: `${BASELINE_LABELS[policy.baseline]}（${policy.baseline}）` },
    { label: '評估政策雜湊', value: version.evaluation_policy_hash },
  ]
}

