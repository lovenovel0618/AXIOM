import { describe, expect, it } from 'vitest'
import { describeRemaining, parseEvidenceBundle, parseQualityReport } from '../src/lib/evidence'

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

const BUNDLE = {
  kind: 'EvidenceBundle',
  id: '11111111-1111-4111-8111-111111111111',
  tenant_id: '22222222-2222-4222-8222-222222222222',
  schema_version: '2.0',
  created_at: '2026-10-21T00:00:00Z',
  research_version_id: '33333333-3333-4333-8333-333333333333',
  validation_ids: [],
  proof_artifact_ids: ['44444444-4444-4444-8444-444444444444'],
  status: 'ACTIVE',
  revision: 0,
}

describe('parseEvidenceBundle', () => {
  it('accepts the PROFILE READY shape with artifact-only references', () => {
    expect(parseEvidenceBundle(BUNDLE)).toEqual({
      id: '11111111-1111-4111-8111-111111111111',
      researchVersionId: '33333333-3333-4333-8333-333333333333',
      status: 'ACTIVE',
      revision: 0,
      validationIds: [],
      proofArtifactIds: ['44444444-4444-4444-8444-444444444444'],
    })
  })

  it('accepts a quarantined bundle that only references validations', () => {
    const parsed = parseEvidenceBundle({
      ...BUNDLE,
      status: 'QUARANTINED',
      revision: 1,
      validation_ids: ['55555555-5555-4555-8555-555555555555'],
      proof_artifact_ids: [],
    })
    expect(parsed?.status).toBe('QUARANTINED')
    expect(parsed?.revision).toBe(1)
    expect(parsed?.validationIds).toEqual(['55555555-5555-4555-8555-555555555555'])
    expect(parsed?.proofArtifactIds).toEqual([])
  })

  it('rejects other kinds and unknown statuses', () => {
    expect(parseEvidenceBundle({ ...BUNDLE, kind: 'Artifact' })).toBeNull()
    expect(parseEvidenceBundle({ ...BUNDLE, status: 'PENDING' })).toBeNull()
    expect(parseEvidenceBundle(null)).toBeNull()
    expect(parseEvidenceBundle('EvidenceBundle')).toBeNull()
  })

  it('rejects empty evidence or malformed references instead of guessing', () => {
    expect(parseEvidenceBundle({ ...BUNDLE, proof_artifact_ids: [] })).toBeNull()
    expect(parseEvidenceBundle({ ...BUNDLE, proof_artifact_ids: [''] })).toBeNull()
    expect(parseEvidenceBundle({ ...BUNDLE, validation_ids: 'x' })).toBeNull()
    expect(parseEvidenceBundle({ ...BUNDLE, revision: -1 })).toBeNull()
  })
})
