/**
 * 反例搜尋（SSOT 23）的閱讀模型：只把後端已揭露的「失效跡象」整理成失效案例。
 *
 * 後端目前沒有反例空間、邊界條件或反例預算的端點，因此這些欄位一律標示「未取得」。
 * 這裡不做任何反例空間推測，只列出 validation run 已回報的否證、失敗列數與拒答理由。
 */
import { describeMetricReason, OUTCOME_LABELS, refusalReasons, type OutcomeStatus, type SplitRole, type ValidationRun } from './evaluation'
import type { VerificationCenter, VerificationSubmissionRow } from './verificationCenter'
import { VERIFICATION_UNKNOWN } from './verificationCenter'

/** 後端未提供反例空間與邊界條件端點；畫面必須固定顯示此狀態。 */
export const COUNTEREXAMPLE_SPACE_UNKNOWN = `反例空間尚無後端端點（${VERIFICATION_UNKNOWN}）`
export const BOUNDARY_CONDITION_UNKNOWN = `邊界條件尚無後端端點（${VERIFICATION_UNKNOWN}）`
export const COUNTEREXAMPLE_BUDGET_UNKNOWN = `反例搜尋預算尚無後端端點（${VERIFICATION_UNKNOWN}）`

export interface CounterexampleRow {
  validationId: string
  submissionId: string
  researchId: string
  researchName: string
  versionId: string
  splitRole: SplitRole
  outcome: OutcomeStatus
  outcomeLabel: string
  /** 後端回報的失敗列數；沒有這個欄位的驗證不會進到失效案例。 */
  failedCount: number
  validCount: number
  selectedCount: number
  reasons: string[]
  createdAt: string
}

export interface FalsifySummary {
  /** outcome 為 FALSIFIED 的驗證數。 */
  falsified: number
  /** 有失敗列或拒答理由的驗證數。 */
  failed: number
  /** 明確拒答、不下結論的驗證數。 */
  insufficient: number
  /** 失效案例總數。 */
  total: number
}

function isFailure(validation: ValidationRun): boolean {
  return validation.outcome === 'FALSIFIED' || validation.failedCount > 0 || Object.keys(validation.metricReasons).length > 0
}

/** 失效案例只由 validation run 的已揭露欄位推導：否證、失敗列數、拒答理由，任一成立即列入。 */
export function buildCounterexampleRows(center: VerificationCenter): CounterexampleRow[] {
  const rows: CounterexampleRow[] = []
  for (const submission of center.submissionRows) {
    for (const validation of submission.validations) {
      if (!isFailure(validation)) continue
      rows.push(counterexampleRow(submission, validation))
    }
  }
  return rows.sort((left, right) => (left.createdAt < right.createdAt ? 1 : left.createdAt > right.createdAt ? -1 : 0))
}

function counterexampleRow(submission: VerificationSubmissionRow, validation: ValidationRun): CounterexampleRow {
  const reasons = refusalReasons(validation)
  if (validation.failedCount > 0) reasons.unshift(`後端回報 ${String(validation.failedCount)} 列無法通過評估。`)
  for (const [name, code] of Object.entries(validation.metricReasons)) {
    const text = `${name}：${describeMetricReason(code)}`
    if (!reasons.includes(text)) reasons.push(text)
  }
  return {
    validationId: validation.id,
    submissionId: submission.submissionId,
    researchId: submission.version.research_id,
    researchName: submission.research?.name ?? '未命名研究',
    versionId: submission.version.id,
    splitRole: validation.splitRole,
    outcome: validation.outcome,
    outcomeLabel: OUTCOME_LABELS[validation.outcome],
    failedCount: validation.failedCount,
    validCount: validation.validCount,
    selectedCount: validation.selectedCount,
    reasons,
    createdAt: validation.createdAt,
  }
}

export function summarizeFalsify(rows: CounterexampleRow[]): FalsifySummary {
  return {
    falsified: rows.filter((row) => row.outcome === 'FALSIFIED').length,
    failed: rows.filter((row) => row.failedCount > 0).length,
    insufficient: rows.filter((row) => row.outcome === 'INSUFFICIENT_EVIDENCE').length,
    total: rows.length,
  }
}
