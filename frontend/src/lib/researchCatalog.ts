/**
 * 研究清單的推導：只用後端已揭露的研究、版本與任務欄位彙整列摘要。
 *
 * 沒有全域任務端點，任務統計只涵蓋已讀取的版本；讀不到的欄位一律留 null 或標示「未取得」，
 * 不以 0 或推測值代替「後端沒有回報」。
 */
import type { Research, ResearchVersion, ResearchVersionStatus } from '../api/research'
import type { Run } from '../api/runs'

export const UNKNOWN = '未取得'
export const RESEARCH_LIMIT = 50
export const VERSIONS_PER_RESEARCH = 20

const ACTIVE_RUN_STATUSES = new Set(['QUEUED', 'RUNNING', 'CANCEL_REQUESTED'])

export type CatalogStatus = ResearchVersionStatus | 'NONE'

export const STATUS_OPTIONS: CatalogStatus[] = [
  'NONE',
  'DRAFT',
  'VALIDATING',
  'READY',
  'QUEUED',
  'RUNNING',
  'FAILED',
  'CANCELLED',
]

export type CatalogSort = 'CREATED_DESC' | 'CREATED_ASC' | 'NAME_ASC' | 'VERSION_DESC' | 'ACTIVITY_DESC'

export const SORT_OPTIONS: Array<{ value: CatalogSort; label: string }> = [
  { value: 'CREATED_DESC', label: '建立時間（新→舊）' },
  { value: 'CREATED_ASC', label: '建立時間（舊→新）' },
  { value: 'NAME_ASC', label: '名稱（A→Z）' },
  { value: 'VERSION_DESC', label: '版本數（多→少）' },
  { value: 'ACTIVITY_DESC', label: '最近任務時間（新→舊）' },
]

export interface CatalogRow {
  id: string
  name: string
  createdAt: string
  /** 已讀取到的版本數；`hasMoreVersions` 為真時代表後端仍有未讀取頁面。 */
  versionCount: number
  hasMoreVersions: boolean
  latestVersionId: string | null
  latestStatus: CatalogStatus
  latestPurpose: string | null
  /** 任務統計只涵蓋已讀取任務的版本，範圍以版本 ID 明示。 */
  runScopedVersionIds: string[]
  runCount: number
  activeRunCount: number
  failedRunCount: number
  searchRunCount: number
  lastActivityAt: string | null
  frozenSubmissionCount: number
}

export interface CatalogSnapshot {
  researches: Research[]
  versionsByResearch: Record<string, ResearchVersion[]>
  /** 鍵不存在代表該版本任務尚未讀取，不能解讀成沒有任務。 */
  runsByVersion: Record<string, Run[]>
  moreVersionsByResearch: Record<string, boolean>
}

export interface SelectionSummary {
  selected: number
  missing: number
  versionCount: number
  runCount: number
  activeRunCount: number
  failedRunCount: number
  researchIds: string[]
}

function desc(left: string, right: string): number {
  if (left === right) return 0
  return left < right ? 1 : -1
}

function newest<T extends { created_at: string }>(rows: T[]): T | null {
  return [...rows].sort((left, right) => desc(left.created_at, right.created_at))[0] ?? null
}

export function isActiveRunStatus(status: string): boolean {
  return ACTIVE_RUN_STATUSES.has(status)
}

/** 最新版本以 `created_at` 反序決定；讀不到時回 null。 */
export function latestVersionOf(versions: ResearchVersion[]): ResearchVersion | null {
  return newest(versions)
}

/** 版本以 created_at 反序視為「最新」；沒有任何版本時狀態回報 NONE。 */
export function buildCatalogRows(snapshot: CatalogSnapshot): CatalogRow[] {
  return snapshot.researches.map((research) => {
    const versionRows = snapshot.versionsByResearch[research.id] ?? []
    const latest = newest(versionRows)
    const scopedVersions = versionRows.filter((version) => version.id in snapshot.runsByVersion)
    const runs = scopedVersions.flatMap((version) => snapshot.runsByVersion[version.id] ?? [])
    const latestRun = newest(runs)

    return {
      id: research.id,
      name: research.name,
      createdAt: research.created_at,
      versionCount: versionRows.length,
      hasMoreVersions: snapshot.moreVersionsByResearch[research.id] === true,
      latestVersionId: latest === null ? null : latest.id,
      latestStatus: latest === null ? 'NONE' : latest.status,
      latestPurpose: latest === null ? null : latest.purpose,
      runScopedVersionIds: scopedVersions.map((version) => version.id),
      runCount: runs.length,
      activeRunCount: runs.filter((run) => isActiveRunStatus(run.status)).length,
      failedRunCount: runs.filter((run) => run.status === 'FAILED').length,
      searchRunCount: runs.filter((run) => run.type === 'SEARCH').length,
      lastActivityAt: latestRun === null ? null : latestRun.created_at,
      frozenSubmissionCount: versionRows.reduce((total, version) => total + version.frozen_submission_ids.length, 0),
    }
  })
}

export function filterCatalogRows(
  rows: CatalogRow[],
  keyword: string,
  status: 'ALL' | CatalogStatus,
): CatalogRow[] {
  const query = keyword.trim().toLowerCase()
  return rows.filter((row) => {
    if (status !== 'ALL' && row.latestStatus !== status) return false
    if (query === '') return true
    return row.name.toLowerCase().includes(query) || row.id.toLowerCase().includes(query)
  })
}

/** 缺少時間的列在時間排序時一律排到最後，不以現在時間代替。 */
export function sortCatalogRows(rows: CatalogRow[], sort: CatalogSort): CatalogRow[] {
  const sorted = [...rows]
  switch (sort) {
    case 'CREATED_ASC':
      return sorted.sort((left, right) => -desc(left.createdAt, right.createdAt))
    case 'NAME_ASC':
      return sorted.sort((left, right) => left.name.localeCompare(right.name))
    case 'VERSION_DESC':
      return sorted.sort(
        (left, right) =>
          right.versionCount - left.versionCount || desc(left.createdAt, right.createdAt),
      )
    case 'ACTIVITY_DESC':
      return sorted.sort((left, right) => {
        if (left.lastActivityAt === null && right.lastActivityAt === null) {
          return desc(left.createdAt, right.createdAt)
        }
        if (left.lastActivityAt === null) return 1
        if (right.lastActivityAt === null) return -1
        return desc(left.lastActivityAt, right.lastActivityAt)
      })
    default:
      return sorted.sort((left, right) => desc(left.createdAt, right.createdAt))
  }
}

export function summarizeSelection(rows: CatalogRow[], selectedIds: string[]): SelectionSummary {
  const byId = new Map(rows.map((row) => [row.id, row]))
  const selected = selectedIds.map((id) => byId.get(id)).filter((row): row is CatalogRow => row !== undefined)

  return {
    selected: selected.length,
    missing: selectedIds.length - selected.length,
    versionCount: selected.reduce((total, row) => total + row.versionCount, 0),
    runCount: selected.reduce((total, row) => total + row.runCount, 0),
    activeRunCount: selected.reduce((total, row) => total + row.activeRunCount, 0),
    failedRunCount: selected.reduce((total, row) => total + row.failedRunCount, 0),
    researchIds: selected.map((row) => row.id),
  }
}

export function describeStatus(status: CatalogStatus): string {
  if (status === 'NONE') return '尚無版本'
  return status
}

const CSV_HEADER = [
  'research_id',
  'name',
  'created_at',
  'version_count',
  'more_versions',
  'latest_version_id',
  'latest_status',
  'latest_purpose',
  'run_scope_versions',
  'run_count',
  'active_run_count',
  'failed_run_count',
  'search_run_count',
  'last_activity_at',
  'frozen_submission_count',
]

function csvCell(value: string | number | null): string {
  if (value === null) return UNKNOWN
  const text = typeof value === 'number' ? String(value) : value
  return `"${text.replaceAll('"', '""')}"`
}

/** 匯出目前視圖；欄位就是表格看到的欄位，未讀取範圍以版本 ID 明示。 */
export function buildCatalogCsv(rows: CatalogRow[]): string {
  const lines = [CSV_HEADER.join(',')]
  for (const row of rows) {
    lines.push(
      [
        csvCell(row.id),
        csvCell(row.name),
        csvCell(row.createdAt),
        csvCell(row.versionCount),
        csvCell(row.hasMoreVersions ? 'true' : 'false'),
        csvCell(row.latestVersionId),
        csvCell(row.latestStatus),
        csvCell(row.latestPurpose),
        csvCell(row.runScopedVersionIds.join(' ')),
        csvCell(row.runScopedVersionIds.length === 0 ? null : row.runCount),
        csvCell(row.runScopedVersionIds.length === 0 ? null : row.activeRunCount),
        csvCell(row.runScopedVersionIds.length === 0 ? null : row.failedRunCount),
        csvCell(row.runScopedVersionIds.length === 0 ? null : row.searchRunCount),
        csvCell(row.lastActivityAt),
        csvCell(row.frozenSubmissionCount),
      ].join(','),
    )
  }
  return `${lines.join('\r\n')}\r\n`
}
