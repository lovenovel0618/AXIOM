import { describe, expect, it } from 'vitest'
import {
  parseFinalEvaluation,
  SLOT_STATUS_LABELS,
  SUBMISSION_STATUS_LABELS,
  type FinalEvaluation,
} from '../src/lib/finalEvaluation'

/** 測試夾具必須能被契約解析；若否即為夾具或解析器壞掉，直接失敗而非在後續斷言埋錯。 */
function accepted(value: unknown): FinalEvaluation {
  const parsed = parseFinalEvaluation(value)
  if (parsed === null) throw new Error('fixture 應符合 FinalEvaluationView 契約')
  return parsed
}

const CANDIDATE = '77777777-7777-4777-8777-777777777777'
const RUN = '33333333-3333-4333-8333-333333333333'

const PENDING = {
  submission_id: '88888888-8888-4888-8888-888888888888',
  metric_version: '2.0',
  status: 'EVALUATING',
  slots: [
    {
      frozen_candidate_id: CANDIDATE,
      slot_id: '11111111-1111-4111-8111-111111111111',
      run_id: RUN,
      validation_run_id: null,
      status: 'PENDING',
    },
  ],
  exposure: { budget: 1, reserved: 1, consumed: 0, retired: 0 },
}

describe('parseFinalEvaluation', () => {
  it('accepts a projection and keeps the frozen whitelist fields', () => {
    expect(parseFinalEvaluation(PENDING)).toEqual({
      submissionId: '88888888-8888-4888-8888-888888888888',
      metricVersion: '2.0',
      status: 'EVALUATING',
      slots: [
        {
          frozenCandidateId: CANDIDATE,
          slotId: '11111111-1111-4111-8111-111111111111',
          runId: RUN,
          validationRunId: null,
          status: 'PENDING',
        },
      ],
      exposure: { budget: 1, reserved: 1, consumed: 0, retired: 0 },
    })
  })

  it('reads a settled slot with its validation run id', () => {
    const parsed = accepted({
      ...PENDING,
      status: 'FAILED',
      slots: [
        { ...PENDING.slots[0], validation_run_id: '99999999-9999-4999-8999-999999999999', status: 'FAILED' },
      ],
      exposure: { budget: 1, reserved: 0, consumed: 0, retired: 1 },
    })
    const slot = parsed.slots.at(0)
    expect(slot?.validationRunId).toBe('99999999-9999-4999-8999-999999999999')
    expect(slot?.status).toBe('FAILED')
    expect(parsed.exposure).toEqual({ budget: 1, reserved: 0, consumed: 0, retired: 1 })
  })

  it('rejects non-objects, unknown enums and malformed identifiers', () => {
    expect(parseFinalEvaluation(null)).toBeNull()
    expect(parseFinalEvaluation('FinalEvaluationView')).toBeNull()
    expect(parseFinalEvaluation([])).toBeNull()
    expect(parseFinalEvaluation({ ...PENDING, status: 'DONE' })).toBeNull()
    expect(parseFinalEvaluation({ ...PENDING, submission_id: 'not-a-uuid' })).toBeNull()
    expect(parseFinalEvaluation({ ...PENDING, metric_version: '' })).toBeNull()
  })

  it('rejects unreadable exposure, slots or slot fields instead of guessing', () => {
    expect(parseFinalEvaluation({ ...PENDING, exposure: { budget: 1, reserved: 1, consumed: 0 } })).toBeNull()
    expect(parseFinalEvaluation({ ...PENDING, exposure: { ...PENDING.exposure, retired: -1 } })).toBeNull()
    expect(parseFinalEvaluation({ ...PENDING, exposure: { ...PENDING.exposure, budget: 1.5 } })).toBeNull()
    expect(parseFinalEvaluation({ ...PENDING, slots: 'x' })).toBeNull()
    expect(parseFinalEvaluation({ ...PENDING, slots: [{ ...PENDING.slots[0], status: 'OPEN' }] })).toBeNull()
    expect(parseFinalEvaluation({ ...PENDING, slots: [{ ...PENDING.slots[0], slot_id: 'nope' }] })).toBeNull()
    expect(parseFinalEvaluation({ ...PENDING, slots: [{ ...PENDING.slots[0], run_id: null }] })).toBeNull()
    const missing = { ...PENDING.slots[0] } as Record<string, unknown>
    delete missing.validation_run_id
    expect(parseFinalEvaluation({ ...PENDING, slots: [missing] })).toBeNull()
  })

  it('accepts a projection with no slots yet', () => {
    const parsed = accepted({ ...PENDING, status: 'FROZEN', slots: [], exposure: { budget: 0, reserved: 0, consumed: 0, retired: 0 } })
    expect(parsed.slots).toEqual([])
    expect(parsed.status).toBe('FROZEN')
  })
})

describe('final evaluation labels', () => {
  it('labels every slot and submission state', () => {
    expect(SLOT_STATUS_LABELS.PENDING).toBe('待評估')
    expect(SLOT_STATUS_LABELS.COMPLETED).toBe('已完成')
    expect(SLOT_STATUS_LABELS.FAILED).toBe('失敗')
    expect(SUBMISSION_STATUS_LABELS.FROZEN).toBe('已凍結')
    expect(SUBMISSION_STATUS_LABELS.EVALUATING).toBe('評估中')
    expect(SUBMISSION_STATUS_LABELS.EVALUATED).toBe('已評估')
    expect(SUBMISSION_STATUS_LABELS.FAILED).toBe('失敗')
  })
})
