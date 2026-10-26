import type { DatasetVersion } from '../api/datasets'
import { DEFAULT_VERSION_FORM, buildDraftRequest, type DraftOutcome, type SourceMetadata, type VersionFormModel } from './semantics'

const NAME = /^[A-Za-z_]\w{0,63}$/

function sanitizeSymbol(name: string, fallback: string): string {
  const trimmed = name.trim()
  return NAME.test(trimmed) ? trimmed : fallback
}

export function quickResearchName(datasetName: string, createdAt = new Date()): string {
  const stamp = createdAt.toISOString().replace('T', ' ').slice(0, 19)
  return `${datasetName} 分析 ${stamp}`
}

export function buildQuickResearchDraft(
  version: DatasetVersion,
  metadata: SourceMetadata,
): DraftOutcome {
  const columns = metadata.columns.map((column) => column.name)
  const inputColumn = columns[0] ?? ''
  const targetColumn = columns[1] ?? ''
  const inputName = sanitizeSymbol(inputColumn, 'x')
  let targetName = sanitizeSymbol(targetColumn, 'y')
  if (targetName === inputName) targetName = targetName === 'y' ? 'target' : 'y'

  const model: VersionFormModel = {
    ...DEFAULT_VERSION_FORM,
    datasetVersionId: version.id,
    rowCount: metadata.row_count,
    inputName,
    inputColumn,
    targetName,
    targetColumn,
    resolutionReason: '快速分析：以資料集結構預覽自動建立研究草稿，解析度待後續人工確認。',
  }
  return buildDraftRequest(model)
}
