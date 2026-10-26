/**
 * 資料集工作區的純推導邏輯：只依後端已揭露的版本欄位與結構預覽產物計算。
 * 缺資料一律回報「未取得」，不以推測補值，符合 Fail-Closed 原則。
 */
import type { DatasetVersion, UploadFormat } from '../api/datasets'
import { sequentialSplit, type ColumnMetadata, type SourceMetadata } from './semantics'

const SHA256 = /^[0-9a-f]{64}$/i

export interface DatasetDigest {
  versionCount: number
  availableCount: number
  unavailableCount: number
  totalRows: number
  previewCount: number
  formats: UploadFormat[]
  latestVersion: DatasetVersion | null
}

export function buildDatasetDigest(versions: DatasetVersion[]): DatasetDigest {
  const sorted = [...versions].sort((left, right) => (left.created_at < right.created_at ? 1 : -1))
  return {
    versionCount: versions.length,
    availableCount: versions.filter((row) => row.status === 'AVAILABLE').length,
    unavailableCount: versions.filter((row) => row.status === 'UNAVAILABLE').length,
    totalRows: versions.reduce((sum, row) => sum + row.row_count, 0),
    previewCount: versions.filter((row) => row.structure_preview_artifact_id !== null).length,
    formats: [...new Set(versions.map((row) => row.format))],
    latestVersion: sorted[0] ?? null,
  }
}

export interface StructureSummary {
  rowCount: number
  columns: ColumnMetadata[]
  duplicateNames: string[]
  missingTypeNames: string[]
}

/** 結構預覽產物不可信：無法解析就回 null，讓呼叫端標示為未取得。 */
export function summarizeStructure(metadata: SourceMetadata | null): StructureSummary | null {
  if (metadata === null) return null
  const seen = new Set<string>()
  const duplicateNames: string[] = []
  const missingTypeNames: string[] = []
  for (const column of metadata.columns) {
    if (seen.has(column.name)) duplicateNames.push(column.name)
    seen.add(column.name)
    if (column.physical_type.trim() === '') missingTypeNames.push(column.name)
  }
  return {
    rowCount: metadata.row_count,
    columns: metadata.columns,
    duplicateNames: [...new Set(duplicateNames)],
    missingTypeNames,
  }
}

export type QualityStatus = 'PASS' | 'FAIL' | 'UNKNOWN'

export interface QualityCheck {
  label: string
  status: QualityStatus
  detail: string
}

/**
 * 依文件化的可判定規則檢核單一版本；規則本身無法判定時一律回報 UNKNOWN。
 */
export function buildQualityChecks(version: DatasetVersion, metadata: SourceMetadata | null): QualityCheck[] {
  const structure = summarizeStructure(metadata)
  const previewReady = version.structure_preview_artifact_id !== null
  const checks: QualityCheck[] = [
    {
      label: '版本狀態可用',
      status: version.status === 'AVAILABLE' ? 'PASS' : 'FAIL',
      detail: `後端回報狀態 ${version.status}。`,
    },
    {
      label: '檔案指紋齊備',
      status: SHA256.test(version.sha256) ? 'PASS' : 'FAIL',
      detail: SHA256.test(version.sha256) ? 'SHA-256 為 64 位十六進位。' : `指紋格式不符：${version.sha256 || '未提供'}`,
    },
    {
      label: '列數足夠三段切分',
      status: sequentialSplit(version.row_count) === null ? 'FAIL' : 'PASS',
      detail:
        sequentialSplit(version.row_count) === null
          ? `列數 ${String(version.row_count)} 未達固定三段切分下限（至少 3 列）。`
          : `列數 ${String(version.row_count)} 可依 60/20/20 固定切分。`,
    },
    {
      label: '結構預覽齊備',
      status: previewReady ? 'PASS' : 'UNKNOWN',
      detail: previewReady ? '版本具備結構預覽產物。' : '此版本未提供結構預覽產物，無法判定欄位。',
    },
  ]

  if (structure === null) {
    checks.push({
      label: '結構預覽可解析',
      status: 'UNKNOWN',
      detail: '未取得可解析的結構預覽內容。',
    })
    checks.push({
      label: '欄位齊備且不重複',
      status: 'UNKNOWN',
      detail: '未取得欄位清單，無法判定。',
    })
    return checks
  }

  checks.push({
    label: '結構預覽可解析',
    status: structure.rowCount === version.row_count ? 'PASS' : 'FAIL',
    detail:
      structure.rowCount === version.row_count
        ? `結構預覽列數與版本一致（${String(structure.rowCount)}）。`
        : `結構預覽列數 ${String(structure.rowCount)} 與版本列數 ${String(version.row_count)} 不一致。`,
  })
  const columnIssue = structure.columns.length === 0 || structure.duplicateNames.length > 0
  checks.push({
    label: '欄位齊備且不重複',
    status: columnIssue ? 'FAIL' : 'PASS',
    detail: columnIssue
      ? structure.columns.length === 0
        ? '結構預覽未揭露任何欄位。'
        : `欄位名稱重複：${structure.duplicateNames.join('、')}`
      : `共 ${String(structure.columns.length)} 個欄位且名稱皆不重複。`,
  })
  return checks
}

export interface VersionDiff {
  sameFile: boolean
  formatChanged: boolean
  statusChanged: boolean
  rowDelta: number
  columnsAdded: string[] | null
  columnsRemoved: string[] | null
}

function columnNames(metadata: SourceMetadata | null): string[] | null {
  if (metadata === null) return null
  return [...new Set(metadata.columns.map((column) => column.name))]
}

/** 比較兩個版本；欄位差異只有在兩邊結構預覽都可解析時才回報，否則為 null（未取得）。 */
export function compareVersions(
  left: DatasetVersion,
  right: DatasetVersion,
  leftMetadata: SourceMetadata | null,
  rightMetadata: SourceMetadata | null,
): VersionDiff {
  const leftNames = columnNames(leftMetadata)
  const rightNames = columnNames(rightMetadata)
  let columnsAdded: string[] | null = null
  let columnsRemoved: string[] | null = null
  if (leftNames !== null && rightNames !== null) {
    const leftSet = new Set(leftNames)
    const rightSet = new Set(rightNames)
    columnsAdded = [...rightSet].filter((name) => !leftSet.has(name))
    columnsRemoved = [...leftSet].filter((name) => !rightSet.has(name))
  }
  return {
    sameFile: left.sha256 === right.sha256,
    formatChanged: left.format !== right.format,
    statusChanged: left.status !== right.status,
    rowDelta: right.row_count - left.row_count,
    columnsAdded,
    columnsRemoved,
  }
}

/** 版本清單可能很長，只保留最近 N 筆做比較選單，避免選單無限膨脹。 */
export function recentVersions(versions: DatasetVersion[], limit = 20): DatasetVersion[] {
  return [...versions].sort((left, right) => (left.created_at < right.created_at ? 1 : -1)).slice(0, limit)
}
