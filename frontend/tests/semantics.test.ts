import { describe, expect, it } from 'vitest'
import {
  buildDraftRequest,
  compareFractions,
  DEFAULT_VERSION_FORM,
  parseDimension,
  parseSourceMetadata,
  sequentialSplit,
  type VersionFormModel,
} from '../src/lib/semantics'

function model(overrides: Partial<VersionFormModel> = {}): VersionFormModel {
  return {
    ...DEFAULT_VERSION_FORM,
    datasetVersionId: '11111111-1111-1111-1111-111111111111',
    rowCount: 10,
    inputColumn: 'x_col',
    targetColumn: 'y_col',
    resolutionReason: '欄位以 0.001 為最小刻度。',
    ...overrides,
  }
}

describe('parseSourceMetadata', () => {
  it('accepts the documented structure preview shape', () => {
    const parsed = parseSourceMetadata({
      source_metadata: { row_count: 3, columns: [{ name: 'a', physical_type: 'int' }] },
      analysis_scope: 'METADATA_ONLY',
    })
    expect(parsed).toEqual({ row_count: 3, columns: [{ name: 'a', physical_type: 'int' }] })
  })

  it('rejects values without a source_metadata object', () => {
    expect(parseSourceMetadata({ row_count: 3, columns: [] })).toBeNull()
    expect(parseSourceMetadata(null)).toBeNull()
    expect(parseSourceMetadata({ source_metadata: { row_count: -1, columns: [] } })).toBeNull()
  })
})

describe('parseDimension', () => {
  it('parses exactly seven bounded integers', () => {
    expect(parseDimension('0, 0, 0, 0, 0, 0, 0')).toEqual([0, 0, 0, 0, 0, 0, 0])
    expect(parseDimension('-32,32,0,0,0,0,0')).toEqual([-32, 32, 0, 0, 0, 0, 0])
  })

  it('rejects wrong arity, non integers and out-of-range axes', () => {
    expect(parseDimension('0,0,0')).toBeNull()
    expect(parseDimension('0,0,0,0,0,0,1.5')).toBeNull()
    expect(parseDimension('0,0,0,0,0,0,33')).toBeNull()
  })
})

describe('sequentialSplit', () => {
  it('covers every row exactly once in three contiguous blocks', () => {
    const split = sequentialSplit(10)
    expect(split).toEqual({
      fit: [0, 1, 2, 3, 4, 5],
      development: [6, 7],
      final_test: [8, 9],
    })
  })

  it('refuses row counts too small to keep three non-empty blocks', () => {
    expect(sequentialSplit(2)).toBeNull()
    expect(sequentialSplit(3)).not.toBeNull()
  })
})

describe('compareFractions', () => {
  it('compares by integer cross multiplication', () => {
    expect(compareFractions({ numerator: '1', denominator: '2' }, { numerator: '1', denominator: '3' })).toBe(1)
    expect(compareFractions({ numerator: '1', denominator: '3' }, { numerator: '1', denominator: '2' })).toBe(-1)
    expect(compareFractions({ numerator: '2', denominator: '4' }, { numerator: '1', denominator: '2' })).toBe(0)
  })

  it('returns null when a side breaks the documented rational shape', () => {
    expect(compareFractions({ numerator: '01', denominator: '2' }, { numerator: '1', denominator: '2' })).toBeNull()
    expect(compareFractions({ numerator: '1', denominator: '0' }, { numerator: '1', denominator: '2' })).toBeNull()
  })
})

describe('buildDraftRequest', () => {
  it('assembles an explicitly split, sequential draft request', () => {
    const outcome = buildDraftRequest(model())
    expect(outcome.problems).toEqual([])
    const request = outcome.request
    expect(request).not.toBeNull()
    expect(request?.semantic_profile.time_ordered).toBe(false)
    expect(request?.semantic_profile.group_column).toBeNull()
    expect(request?.observation_split.kind).toBe('EXPLICIT')
    expect(request?.observation_split.sealed_final_test).toBe(true)
    expect(request?.observation_split.fit).toEqual([0, 1, 2, 3, 4, 5])
    expect(request?.evaluation_policy.comparison_method).toBe('NONE')
    expect(request?.evaluation_policy.bootstrap_replicates).toBe(2000)
    expect(request?.domain[0]?.lower_closed).toBe(true)
  })

  it('blocks submission and lists reasons when fields violate the contract', () => {
    const outcome = buildDraftRequest(
      model({ targetColumn: 'x_col', resolutionReason: '', domainLowerNumerator: '2', domainUpperNumerator: '1' }),
    )
    expect(outcome.request).toBeNull()
    expect(outcome.problems.join('\n')).toContain('不可使用同一個來源欄位')
    expect(outcome.problems.join('\n')).toContain('解析度判定的理由')
    expect(outcome.problems.join('\n')).toContain('下界必須小於上界')
  })

  it('keeps equal endpoints when both sides are closed', () => {
    const outcome = buildDraftRequest(model({ domainLowerNumerator: '1', domainUpperNumerator: '1' }))
    expect(outcome.problems).toEqual([])
    expect(outcome.request).not.toBeNull()
  })
})
