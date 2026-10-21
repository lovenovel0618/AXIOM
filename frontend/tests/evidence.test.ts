import { describe, expect, it } from 'vitest'
import { describeRemaining, parseQualityReport } from '../src/lib/evidence'

const PASS = {
  kind: 'QualityReport',
  quality: 'PASS',
  blocking_code: null,
  readiness: 'READY',
  remaining: [],
  precision_bits: 53,
  fit_summary: {
    selected_count: 6,
    unique_x: 6,
    target_min: '1',
    target_max: '11',
    target_mean: '6',
    target_iqr: '5',
  },
}

const BLOCKED = {
  kind: 'QualityReport',
  quality: 'BLOCKED',
  blocking_code: 'DATA_QUALITY_BLOCKED',
  readiness: 'BLOCKED',
  remaining: ['SEALED_TEST_NOT_REGISTERED'],
  precision_bits: 53,
  fit_summary: null,
}

describe('parseQualityReport', () => {
  it('accepts the masked PASS shape', () => {
    expect(parseQualityReport(PASS)).toEqual({
      quality: 'PASS',
      readiness: 'READY',
      blockingCode: null,
      remaining: [],
      precisionBits: 53,
      fitSummary: {
        selectedCount: 6,
        uniqueX: 6,
        targetMin: '1',
        targetMax: '11',
        targetMean: '6',
        targetIqr: '5',
      },
    })
  })

  it('accepts the masked BLOCKED shape', () => {
    const parsed = parseQualityReport(BLOCKED)
    expect(parsed?.quality).toBe('BLOCKED')
    expect(parsed?.readiness).toBe('BLOCKED')
    expect(parsed?.blockingCode).toBe('DATA_QUALITY_BLOCKED')
    expect(parsed?.remaining).toEqual(['SEALED_TEST_NOT_REGISTERED'])
    expect(parsed?.fitSummary).toBeNull()
  })

  it('rejects other artifact kinds and unknown outcomes', () => {
    expect(parseQualityReport({ ...PASS, kind: 'StructureAssessment' })).toBeNull()
    expect(parseQualityReport({ ...PASS, quality: 'UNKNOWN' })).toBeNull()
    expect(parseQualityReport({ ...PASS, readiness: 'PENDING' })).toBeNull()
    expect(parseQualityReport(null)).toBeNull()
    expect(parseQualityReport('QualityReport')).toBeNull()
  })

  it('rejects incomplete readiness work or fit summary instead of guessing', () => {
    expect(parseQualityReport({ ...PASS, remaining: [''] })).toBeNull()
    expect(parseQualityReport({ ...PASS, remaining: 'SEALED_TEST_NOT_REGISTERED' })).toBeNull()
    expect(parseQualityReport({ ...PASS, fit_summary: { selected_count: 6 } })).toBeNull()
    expect(parseQualityReport({ ...PASS, fit_summary: { ...PASS.fit_summary, target_mean: '' } })).toBeNull()
  })
})

describe('describeRemaining', () => {
  it('translates documented codes and keeps unknown ones', () => {
    expect(describeRemaining('SEALED_TEST_NOT_REGISTERED')).toBe('尚未完成正式封存測試登記')
    expect(describeRemaining('SOMETHING_ELSE')).toBe('SOMETHING_ELSE')
  })
})
