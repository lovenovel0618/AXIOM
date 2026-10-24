import { describe, expect, it } from 'vitest'
import {
  OUTCOME_LABELS,
  describeMetricReason,
  parseValidationRun,
  refusalReasons,
  type ValidationRun,
} from '../src/lib/evaluation'

/** 測試夾具必須能被契約解析；若否即為夾具或解析器壞掉，直接失敗而非在後續斷言埋錯。 */
function accepted(value: unknown): ValidationRun {
  const parsed = parseValidationRun(value)
  if (parsed === null) throw new Error('fixture 應符合 ValidationRun 契約')
  return parsed
}

const SHA = 'a'.repeat(64)

const SUPPORTED = {
  kind: 'ValidationRun',
  id: '11111111-1111-4111-8111-111111111111',
  tenant_id: '22222222-2222-4222-8222-222222222222',
  schema_version: '2.0',
  created_at: '2026-10-24T00:00:00Z',
  run_id: '33333333-3333-4333-8333-333333333333',
  fit_run_id: '44444444-4444-4444-8444-444444444444',
  metric_version: '2.0',
  metrics: { mae: 0.5, rmse: 0.75 },
  valid_coverage: 1.0,
  empirical_level: 'E2',
  proof_level: 'P1',
  outcome_status: 'SUPPORTED',
  artifact_uri: 'artifact://x',
  sha256: SHA,
  metric_reasons: {},
  artifact_id: '55555555-5555-4555-8555-555555555555',
  observation_split_id: '66666666-6666-4666-8666-666666666666',
  split_role: 'FINAL_TEST',
  frozen_candidate_id: '77777777-7777-4777-8777-777777777777',
  submission_id: '88888888-8888-4888-8888-888888888888',
  evaluation_policy_hash: SHA,
  selected_count: 10,
  valid_count: 9,
  failed_count: 1,
  verification_plan_artifact_id: '99999999-9999-4999-8999-999999999999',
  verification_plan_hash: SHA,
}

const REFUSED = {
  ...SUPPORTED,
  metrics: { mae: null, rmse: null },
  valid_coverage: 0.0,
  outcome_status: 'INSUFFICIENT_EVIDENCE',
  metric_reasons: { mae: 'NO_EVALUABLE_ROWS', rmse: 'NO_EVALUABLE_ROWS' },
  valid_count: 0,
}

describe('parseValidationRun', () => {
  it('accepts a FINAL_TEST result and keeps the frozen fields', () => {
    expect(parseValidationRun(SUPPORTED)).toEqual({
      id: '11111111-1111-4111-8111-111111111111',
      outcome: 'SUPPORTED',
      metricVersion: '2.0',
      splitRole: 'FINAL_TEST',
      empiricalLevel: 'E2',
      proofLevel: 'P1',
      mae: 0.5,
      rmse: 0.75,
      metricReasons: {},
      validCoverage: 1.0,
      selectedCount: 10,
      validCount: 9,
      failedCount: 1,
      sha256: SHA,
      createdAt: '2026-10-24T00:00:00Z',
    })
  })

  it('accepts the refusal shape where error metrics are null', () => {
    const parsed = parseValidationRun(REFUSED)
    expect(parsed?.outcome).toBe('INSUFFICIENT_EVIDENCE')
    expect(parsed?.mae).toBeNull()
    expect(parsed?.rmse).toBeNull()
    expect(parsed?.validCoverage).toBe(0)
    expect(parsed?.metricReasons).toEqual({ mae: 'NO_EVALUABLE_ROWS', rmse: 'NO_EVALUABLE_ROWS' })
  })

  it('rejects other kinds, unknown enums and malformed hashes', () => {
    expect(parseValidationRun({ ...SUPPORTED, kind: 'EvidenceBundle' })).toBeNull()
    expect(parseValidationRun({ ...SUPPORTED, outcome_status: 'PASSED' })).toBeNull()
    expect(parseValidationRun({ ...SUPPORTED, split_role: 'TRAIN' })).toBeNull()
    expect(parseValidationRun({ ...SUPPORTED, empirical_level: 'E9' })).toBeNull()
    expect(parseValidationRun({ ...SUPPORTED, proof_level: 'P9' })).toBeNull()
    expect(parseValidationRun({ ...SUPPORTED, sha256: 'not-a-hash' })).toBeNull()
    expect(parseValidationRun(null)).toBeNull()
    expect(parseValidationRun('ValidationRun')).toBeNull()
  })

  it('rejects unreadable metrics, coverage or counts instead of guessing', () => {
    expect(parseValidationRun({ ...SUPPORTED, metrics: { mae: 'x', rmse: 1 } })).toBeNull()
    expect(parseValidationRun({ ...SUPPORTED, metrics: { mae: 1 } })).toBeNull()
    expect(parseValidationRun({ ...SUPPORTED, valid_coverage: 1.5 })).toBeNull()
    expect(parseValidationRun({ ...SUPPORTED, valid_coverage: -0.1 })).toBeNull()
    expect(parseValidationRun({ ...SUPPORTED, selected_count: -1 })).toBeNull()
    expect(parseValidationRun({ ...SUPPORTED, failed_count: 1.5 })).toBeNull()
    expect(parseValidationRun({ ...SUPPORTED, metric_reasons: { mae: '' } })).toBeNull()
    expect(parseValidationRun({ ...SUPPORTED, metric_reasons: null })).toBeNull()
    expect(parseValidationRun({ ...SUPPORTED, created_at: '' })).toBeNull()
  })
})

describe('refusalReasons', () => {
  it('translates documented metric reason codes', () => {
    expect(describeMetricReason('NO_EVALUABLE_ROWS')).toBe('沒有任何可評分的 final_test 列，該誤差量不可得。')
    expect(describeMetricReason('SOMETHING_ELSE')).toBe('SOMETHING_ELSE')
    const reasons = refusalReasons(accepted(REFUSED))
    expect(reasons).toContain('mae：沒有任何可評分的 final_test 列，該誤差量不可得。')
    expect(reasons).toContain('rmse：沒有任何可評分的 final_test 列，該誤差量不可得。')
  })

  it('states that a bare refusal does not disclose the failed premise', () => {
    const reasons = refusalReasons(accepted({ ...REFUSED, metric_reasons: {} }))
    expect(reasons).toHaveLength(1)
    expect(reasons[0]).toContain('未揭露是哪一項比較前提未成立')
    expect(reasons[0]).toContain('不推測')
  })

  it('does not invent reasons for a decided outcome', () => {
    expect(refusalReasons(accepted(SUPPORTED))).toEqual([])
  })
})

describe('OUTCOME_LABELS', () => {
  it('labels all four frozen outcome states', () => {
    expect(OUTCOME_LABELS.SUPPORTED).toBe('支持')
    expect(OUTCOME_LABELS.AMBIGUOUS).toBe('無法區辨')
    expect(OUTCOME_LABELS.INSUFFICIENT_EVIDENCE).toBe('證據不足（拒答）')
    expect(OUTCOME_LABELS.FALSIFIED).toBe('被否證')
  })
})
