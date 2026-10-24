/**
 * 最終評估結果（ValidationRun）的唯讀解析：後端只回契約白名單欄位，前端不得推測被遮住的內容。
 * 形狀不符一律回 null，拒答理由只回文件明載的內容，未揭露的比較前提不補猜。
 */
export type OutcomeStatus = 'SUPPORTED' | 'AMBIGUOUS' | 'INSUFFICIENT_EVIDENCE' | 'FALSIFIED'
export type SplitRole = 'FIT' | 'DEVELOPMENT' | 'FINAL_TEST'
export type EmpiricalLevel = 'E0' | 'E1' | 'E2' | 'E3'
export type ProofLevel = 'P0' | 'P1' | 'P2'

export interface ValidationRun {
  id: string
  outcome: OutcomeStatus
  metricVersion: string
  splitRole: SplitRole
  empiricalLevel: EmpiricalLevel
  proofLevel: ProofLevel
  mae: number | null
  rmse: number | null
  metricReasons: Record<string, string>
  validCoverage: number
  selectedCount: number
  validCount: number
  failedCount: number
  sha256: string
  createdAt: string
}

const OUTCOMES: readonly OutcomeStatus[] = ['SUPPORTED', 'AMBIGUOUS', 'INSUFFICIENT_EVIDENCE', 'FALSIFIED']
const SPLIT_ROLES: readonly SplitRole[] = ['FIT', 'DEVELOPMENT', 'FINAL_TEST']
const EMPIRICAL_LEVELS: readonly EmpiricalLevel[] = ['E0', 'E1', 'E2', 'E3']
const PROOF_LEVELS: readonly ProofLevel[] = ['P0', 'P1', 'P2']
const SHA256 = /^[0-9a-f]{64}$/

export const OUTCOME_LABELS: Record<OutcomeStatus, string> = {
  SUPPORTED: '支持',
  AMBIGUOUS: '無法區辨',
  INSUFFICIENT_EVIDENCE: '證據不足（拒答）',
  FALSIFIED: '被否證',
}

export const OUTCOME_DETAILS: Record<OutcomeStatus, string> = {
  SUPPORTED: '配對區間完全落在實務邊界內，凍結政策判為支持。',
  AMBIGUOUS: '配對區間與實務邊界重疊，資料不足以區辨優劣。',
  INSUFFICIENT_EVIDENCE: '比較前提未全部成立，後端拒答而非給出結論。',
  FALSIFIED: '配對區間完全落在實務邊界外，凍結政策判為否證。',
}

const METRIC_REASON_LABELS: Record<string, string> = {
  NO_EVALUABLE_ROWS: '沒有任何可評分的 final_test 列，該誤差量不可得。',
}

/** 未知代碼保留原始碼，方便對照後端契約與錯誤碼表。 */
export function describeMetricReason(code: string): string {
  return METRIC_REASON_LABELS[code] ?? code
}

/**
 * 拒答理由：只整理後端文件明載的內容。
 *
 * 後端不下結論時只回 `INSUFFICIENT_EVIDENCE`，未揭露是哪一項前提（誤差模型、比較方法、可評分列數、
 * baseline 或實務尺度）未成立，因此此處明示不推測，交由使用者對照凍結政策與 fit 統計。
 */
export function refusalReasons(run: ValidationRun): string[] {
  const reasons: string[] = []
  for (const [name, code] of Object.entries(run.metricReasons)) {
    reasons.push(`${name}：${describeMetricReason(code)}`)
  }
  if (run.outcome === 'INSUFFICIENT_EVIDENCE' && Object.keys(run.metricReasons).length === 0) {
    reasons.push('後端只回 INSUFFICIENT_EVIDENCE，未揭露是哪一項比較前提未成立；本畫面不推測原因。')
  }
  return reasons
}

/** 後端回應視為不可信輸入，一律以鍵存在與否取值，不假設欄位一定在。 */
function field(source: object, key: string): unknown {
  return (source as Record<string, unknown>)[key]
}

function has(source: object, key: string): boolean {
  return key in source
}

function text(source: object, key: string): string | null {
  const value = has(source, key) ? field(source, key) : undefined
  return typeof value === 'string' && value !== '' ? value : null
}

function oneOf<T extends string>(source: object, key: string, allowed: readonly T[]): T | null {
  const value = text(source, key)
  return value !== null && (allowed as readonly string[]).includes(value) ? (value as T) : null
}

function metric(value: object, key: string): number | null | undefined {
  if (!has(value, key)) return undefined
  const candidate = field(value, key)
  if (candidate === null) return null
  return typeof candidate === 'number' && Number.isFinite(candidate) ? candidate : undefined
}

function count(source: object, key: string): number | null {
  const candidate = has(source, key) ? field(source, key) : undefined
  return typeof candidate === 'number' && Number.isSafeInteger(candidate) && candidate >= 0 ? candidate : null
}

function parseMetricReasons(source: object): Record<string, string> | null {
  if (!has(source, 'metric_reasons')) return null
  const candidate = field(source, 'metric_reasons')
  if (typeof candidate !== 'object' || candidate === null || Array.isArray(candidate)) return null
  const result: Record<string, string> = {}
  for (const [name, code] of Object.entries(candidate)) {
    if (typeof code !== 'string' || code === '') return null
    result[name] = code
  }
  return result
}

/** 契約要求 outcome、誤差量、覆蓋率與計數全部可讀才接受整份結果。 */
export function parseValidationRun(value: unknown): ValidationRun | null {
  if (typeof value !== 'object' || value === null) return null
  const source: object = value
  if (text(source, 'kind') !== 'ValidationRun') return null
  const id = text(source, 'id')
  if (id === null) return null
  const outcome = oneOf(source, 'outcome_status', OUTCOMES)
  if (outcome === null) return null
  const metricVersion = text(source, 'metric_version')
  if (metricVersion === null) return null
  const splitRole = oneOf(source, 'split_role', SPLIT_ROLES)
  if (splitRole === null) return null
  const empiricalLevel = oneOf(source, 'empirical_level', EMPIRICAL_LEVELS)
  if (empiricalLevel === null) return null
  const proofLevel = oneOf(source, 'proof_level', PROOF_LEVELS)
  if (proofLevel === null) return null
  if (!has(source, 'metrics')) return null
  const metrics = field(source, 'metrics')
  if (typeof metrics !== 'object' || metrics === null) return null
  const mae = metric(metrics, 'mae')
  const rmse = metric(metrics, 'rmse')
  if (mae === undefined || rmse === undefined) return null
  const metricReasons = parseMetricReasons(source)
  if (metricReasons === null) return null
  const coverage = has(source, 'valid_coverage') ? field(source, 'valid_coverage') : undefined
  if (typeof coverage !== 'number' || !Number.isFinite(coverage) || coverage < 0 || coverage > 1) return null
  const selected = count(source, 'selected_count')
  const valid = count(source, 'valid_count')
  const failed = count(source, 'failed_count')
  if (selected === null || valid === null || failed === null) return null
  const sha = text(source, 'sha256')
  if (sha === null || !SHA256.test(sha)) return null
  const createdAt = text(source, 'created_at')
  if (createdAt === null) return null
  return {
    id,
    outcome,
    metricVersion,
    splitRole,
    empiricalLevel,
    proofLevel,
    mae,
    rmse,
    metricReasons,
    validCoverage: coverage,
    selectedCount: selected,
    validCount: valid,
    failedCount: failed,
    sha256: sha,
    createdAt,
  }
}
