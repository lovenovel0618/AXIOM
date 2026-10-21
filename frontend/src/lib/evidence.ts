/**
 * 品質報告（遮罩產物）的唯讀解析：後端只暴露遮罩後欄位，前端不得推測被遮住的內容。
 * 形狀不符一律回 null，避免用半解讀的資料誤導使用者。
 */
export type QualityOutcome = 'PASS' | 'BLOCKED'
export type Readiness = 'READY' | 'BLOCKED'

export interface FitSummary {
  selectedCount: number
  uniqueX: number
  targetMin: string
  targetMax: string
  targetMean: string
  targetIqr: string
}

export interface QualityReport {
  quality: QualityOutcome
  readiness: Readiness
  blockingCode: string | null
  remaining: string[]
  precisionBits: number | null
  fitSummary: FitSummary | null
}

const REMAINING_LABELS: Record<string, string> = {
  SEALED_TEST_NOT_REGISTERED: '尚未完成正式封存測試登記',
}

export type EvidenceStatus = 'ACTIVE' | 'REVOKED' | 'QUARANTINED'

/** READY 版本才有的證據包；只引用既有產物，不生成新的科學主張。 */
export interface EvidenceBundle {
  id: string
  researchVersionId: string
  status: EvidenceStatus
  revision: number
  validationIds: string[]
  proofArtifactIds: string[]
}

export const QUALITY_LABELS: Record<QualityOutcome, string> = {
  PASS: '通過',
  BLOCKED: '未通過',
}

export const EVIDENCE_STATUS_LABELS: Record<EvidenceStatus, string> = {
  ACTIVE: '有效',
  REVOKED: '已撤銷',
  QUARANTINED: '已隔離',
}

export const READINESS_LABELS: Record<Readiness, string> = {
  READY: '就緒',
  BLOCKED: '未就緒',
}

/** 未知代碼保留原始碼，方便對照後端契約與錯誤碼表。 */
export function describeRemaining(code: string): string {
  return REMAINING_LABELS[code] ?? code
}

function parseFitSummary(value: unknown): FitSummary | null {
  if (typeof value !== 'object' || value === null) return null
  if (!('selected_count' in value) || !('unique_x' in value)) return null
  if (!('target_min' in value) || !('target_max' in value) || !('target_mean' in value) || !('target_iqr' in value)) return null
  const selectedCount: unknown = value.selected_count
  const uniqueX: unknown = value.unique_x
  const targetMin: unknown = value.target_min
  const targetMax: unknown = value.target_max
  const targetMean: unknown = value.target_mean
  const targetIqr: unknown = value.target_iqr
  if (typeof selectedCount !== 'number' || !Number.isSafeInteger(selectedCount) || selectedCount < 0) return null
  if (typeof uniqueX !== 'number' || !Number.isSafeInteger(uniqueX) || uniqueX < 0) return null
  if (typeof targetMin !== 'string' || targetMin === '') return null
  if (typeof targetMax !== 'string' || targetMax === '') return null
  if (typeof targetMean !== 'string' || targetMean === '') return null
  if (typeof targetIqr !== 'string' || targetIqr === '') return null
  return { selectedCount, uniqueX, targetMin, targetMax, targetMean, targetIqr }
}

export function parseQualityReport(value: unknown): QualityReport | null {
  if (typeof value !== 'object' || value === null) return null
  if (!('kind' in value) || value.kind !== 'QualityReport') return null
  if (!('quality' in value) || (value.quality !== 'PASS' && value.quality !== 'BLOCKED')) return null
  if (!('readiness' in value) || (value.readiness !== 'READY' && value.readiness !== 'BLOCKED')) return null
  if (!('remaining' in value) || !Array.isArray(value.remaining)) return null
  const remaining: string[] = []
  for (const item of value.remaining) {
    if (typeof item !== 'string' || item === '') return null
    remaining.push(item)
  }
  const blocking: unknown = 'blocking_code' in value ? value.blocking_code : null
  const precision: unknown = 'precision_bits' in value ? value.precision_bits : null
  const summary: unknown = 'fit_summary' in value ? value.fit_summary : null
  // fit 摘要若存在卻不完整，代表後端契約不符；整份報告不採用，避免顯示半解讀內容。
  let fitSummary: FitSummary | null = null
  if (summary !== null) {
    fitSummary = parseFitSummary(summary)
    if (fitSummary === null) return null
  }
  return {
    quality: value.quality,
    readiness: value.readiness,
    blockingCode: typeof blocking === 'string' && blocking !== '' ? blocking : null,
    remaining,
    precisionBits: typeof precision === 'number' && Number.isSafeInteger(precision) ? precision : null,
    fitSummary,
  }
}

function parseUuidList(value: unknown): string[] | null {
  if (!Array.isArray(value)) return null
  const result: string[] = []
  for (const item of value) {
    if (typeof item !== 'string' || item === '') return null
    result.push(item)
  }
  return result
}

/** 契約要求兩個引用集合至少一項非空；兩者皆空代表沒有證據，一律不採用。 */
export function parseEvidenceBundle(value: unknown): EvidenceBundle | null {
  if (typeof value !== 'object' || value === null) return null
  if (!('kind' in value) || value.kind !== 'EvidenceBundle') return null
  if (!('id' in value) || typeof value.id !== 'string' || value.id === '') return null
  if (!('research_version_id' in value) || typeof value.research_version_id !== 'string' || value.research_version_id === '') return null
  if (!('status' in value) || (value.status !== 'ACTIVE' && value.status !== 'REVOKED' && value.status !== 'QUARANTINED')) return null
  if (!('revision' in value) || typeof value.revision !== 'number' || !Number.isSafeInteger(value.revision) || value.revision < 0) return null
  const validationIds = parseUuidList('validation_ids' in value ? value.validation_ids : null)
  const proofArtifactIds = parseUuidList('proof_artifact_ids' in value ? value.proof_artifact_ids : null)
  if (validationIds === null || proofArtifactIds === null) return null
  if (validationIds.length === 0 && proofArtifactIds.length === 0) return null
  return {
    id: value.id,
    researchVersionId: value.research_version_id,
    status: value.status,
    revision: value.revision,
    validationIds,
    proofArtifactIds,
  }
}
