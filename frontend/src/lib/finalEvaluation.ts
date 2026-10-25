/**
 * 槽位最終評估投影（FinalEvaluationView）的唯讀解析：後端只回契約白名單欄位，前端不得推測被遮住的內容。
 *
 * 曝光帳本的權威狀態留在隔離 Evaluator 的私有域，這裡只呈現由公開槽位狀態推導的計數；形狀不符一律回 null。
 */
export type SlotStatus = 'PENDING' | 'COMPLETED' | 'FAILED'
export type SubmissionStatus = 'FROZEN' | 'EVALUATING' | 'EVALUATED' | 'FAILED'

export interface FinalEvaluationSlot {
  frozenCandidateId: string
  slotId: string
  runId: string
  validationRunId: string | null
  status: SlotStatus
}

export interface ExposureBudget {
  budget: number
  reserved: number
  consumed: number
  retired: number
}

export interface FinalEvaluation {
  submissionId: string
  metricVersion: string
  status: SubmissionStatus
  slots: FinalEvaluationSlot[]
  exposure: ExposureBudget
}

const SLOT_STATUSES: readonly SlotStatus[] = ['PENDING', 'COMPLETED', 'FAILED']
const SUBMISSION_STATUSES: readonly SubmissionStatus[] = ['FROZEN', 'EVALUATING', 'EVALUATED', 'FAILED']
const UUID = /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/

export const SLOT_STATUS_LABELS: Record<SlotStatus, string> = {
  PENDING: '待評估',
  COMPLETED: '已完成',
  FAILED: '失敗',
}

export const SUBMISSION_STATUS_LABELS: Record<SubmissionStatus, string> = {
  FROZEN: '已凍結',
  EVALUATING: '評估中',
  EVALUATED: '已評估',
  FAILED: '失敗',
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

function uuid(source: object, key: string): string | null {
  const value = text(source, key)
  return value !== null && UUID.test(value) ? value : null
}

function oneOf<T extends string>(source: object, key: string, allowed: readonly T[]): T | null {
  const value = text(source, key)
  return value !== null && (allowed as readonly string[]).includes(value) ? (value as T) : null
}

function count(source: object, key: string): number | null {
  const candidate = has(source, key) ? field(source, key) : undefined
  return typeof candidate === 'number' && Number.isSafeInteger(candidate) && candidate >= 0 ? candidate : null
}

function parseExposure(source: object): ExposureBudget | null {
  if (!has(source, 'exposure')) return null
  const candidate = field(source, 'exposure')
  if (typeof candidate !== 'object' || candidate === null || Array.isArray(candidate)) return null
  const budget = count(candidate, 'budget')
  const reserved = count(candidate, 'reserved')
  const consumed = count(candidate, 'consumed')
  const retired = count(candidate, 'retired')
  if (budget === null || reserved === null || consumed === null || retired === null) return null
  return { budget, reserved, consumed, retired }
}

function parseSlot(value: unknown): FinalEvaluationSlot | null {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return null
  const frozenCandidateId = uuid(value, 'frozen_candidate_id')
  const slotId = uuid(value, 'slot_id')
  const runId = uuid(value, 'run_id')
  if (frozenCandidateId === null || slotId === null || runId === null) return null
  if (!has(value, 'validation_run_id')) return null
  const raw = field(value, 'validation_run_id')
  let validationRunId: string | null = null
  if (raw !== null) {
    if (typeof raw !== 'string' || !UUID.test(raw)) return null
    validationRunId = raw
  }
  const status = oneOf(value, 'status', SLOT_STATUSES)
  if (status === null) return null
  return { frozenCandidateId, slotId, runId, validationRunId, status }
}

function parseSlots(source: object): FinalEvaluationSlot[] | null {
  if (!has(source, 'slots')) return null
  const candidate = field(source, 'slots')
  if (!Array.isArray(candidate)) return null
  const slots: FinalEvaluationSlot[] = []
  for (const entry of candidate) {
    const slot = parseSlot(entry)
    if (slot === null) return null
    slots.push(slot)
  }
  return slots
}

/** 契約要求身分、狀態、槽位與曝光計數全部可讀才接受整份投影。 */
export function parseFinalEvaluation(value: unknown): FinalEvaluation | null {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return null
  const source: object = value
  const submissionId = uuid(source, 'submission_id')
  if (submissionId === null) return null
  const metricVersion = text(source, 'metric_version')
  if (metricVersion === null) return null
  const status = oneOf(source, 'status', SUBMISSION_STATUSES)
  if (status === null) return null
  const exposure = parseExposure(source)
  if (exposure === null) return null
  const slots = parseSlots(source)
  if (slots === null) return null
  return { submissionId, metricVersion, status, slots, exposure }
}
