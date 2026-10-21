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

export const QUALITY_LABELS: Record<QualityOutcome, string> = {
  PASS: '通過',
  BLOCKED: '未通過',
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
