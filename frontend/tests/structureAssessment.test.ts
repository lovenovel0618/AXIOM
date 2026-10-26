import { describe, expect, it } from 'vitest'
import type { Research, ResearchVersion } from '../src/api/research'
import {
  buildLatentRows,
  isStructureIdentified,
  parseStructureAssessment,
  summarizeLatent,
  type StructureAssessment,
} from '../src/lib/structureAssessment'

const VERSION_ID = '11111111-1111-1111-1111-111111111111'
const TENANT_ID = '22222222-2222-2222-2222-222222222222'
const RESEARCH_ID = '33333333-3333-3333-3333-333333333333'
const DATASET_VERSION_ID = '44444444-4444-4444-4444-444444444444'
const METHOD_MANIFEST_ID = '55555555-5555-5555-5555-555555555555'
const ARTIFACT_ID = '66666666-6666-6666-6666-666666666666'

/** 後端目前實際回傳的形狀：內在維度 null、結構候選只有 UNKNOWN。 */
function payload(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    kind: 'StructureAssessment',
    id: ARTIFACT_ID,
    tenant_id: TENANT_ID,
    research_version_id: VERSION_ID,
    dataset_version_id: DATASET_VERSION_ID,
    method_manifest_id: METHOD_MANIFEST_ID,
    schema_version: '1.0',
    created_at: '2026-10-26T00:00:00Z',
    artifact_access_class: 'PROJECT',
    observation_dimension: 1,
    coordinate_dimension: null,
    representation_dimension: 1,
    intrinsic_dimension_estimate: null,
    structure_candidates: ['UNKNOWN'],
    time_basis: 'INDEX_ONLY',
    periodicity: 'UNKNOWN',
    analysis_scope: 'METADATA_ONLY',
    fit_rows_hash: null,
    uncertainty_reason: '尚未完成可識別性判定',
    source_metadata: {
      row_count: 5000,
      columns: [{ name: 'x', physical_type: 'double' }],
    },
    ...overrides,
  }
}

function research(): Research {
  return {
    kind: 'Research',
    id: RESEARCH_ID,
    tenant_id: TENANT_ID,
    schema_version: '2.0',
    created_at: '2026-10-26T00:00:00Z',
    name: 'sin 週期研究',
    owner_id: 'owner-1',
  }
}

function version(overrides: Partial<ResearchVersion> = {}): ResearchVersion {
  return {
    kind: 'ResearchVersion',
    id: VERSION_ID,
    tenant_id: TENANT_ID,
    schema_version: '2.0',
    created_at: '2026-10-26T01:00:00Z',
    research_id: RESEARCH_ID,
    dataset_version_id: DATASET_VERSION_ID,
    semantic_profile: {
      inputs: [],
      target: { name: 'y', unit: [], source_column: 'y', conversion: { source_unit: '1', scale: '1', offset: '0' } },
      units_confirmed: true,
      time_ordered: false,
      measurement_resolution: null,
      resolution_reason: 'ok',
      group_column: null,
    },
    budget: { cpu_seconds: 1, gpu_seconds: 0, wall_seconds: 1, tokens: 0, candidate_limit: 1, memory_bytes: 1 },
    purpose: 'DESCRIPTION',
    status: 'READY',
    revision: 1,
    observation_split: {
      id: 'split-1',
      kind: 'EXPLICIT',
      dataset_version_id: DATASET_VERSION_ID,
      fit: [1],
      development: [2],
      final_test: [3],
      gap_rows: 0,
      lookback_rows: 0,
      horizon_rows: 0,
      seed: 0,
      time_column: null,
      group_column: null,
      group_assignment_digest: null,
      splitter_version: '1',
      policy_version: '1',
      sealed_final_test: true,
      row_ids_hash: 'a'.repeat(64),
      sealed_test_id: null,
    },
    current_event_cursor: 'RESEARCH:1:0',
    frozen_submission_ids: [],
    evidence_bundle_ids: [],
    quality_report_id: null,
    refit_policy_artifact_id: null,
    domain: [],
    evaluation_policy: {
      policy_version: '1',
      metric_version: '1',
      error_model: 'UNSPECIFIED',
      absolute_error_bound: null,
      comparison_method: 'NONE',
      bootstrap_replicates: 0,
      bootstrap_seed: 0,
      block_method: null,
      block_length: null,
      practical_scale_override: null,
      practical_margin_ratio: '0.01',
      baseline: 'ZERO',
      practical_scale_reason: null,
    },
    evaluation_policy_hash: 'b'.repeat(64),
    research_budget_usage: {
      cpu_seconds: 0,
      gpu_seconds: 0,
      tokens: 0,
      peak_memory_bytes: 0,
      elapsed_wall_seconds: 0,
      candidates_generated: 0,
      candidates_accepted: 0,
    },
    structure_assessment_artifact_id: null,
    ...overrides,
  }
}

describe('parseStructureAssessment', () => {
  it('accepts the payload the backend currently returns', () => {
    const parsed = parseStructureAssessment(payload())
    expect(parsed).not.toBeNull()
    expect(parsed?.intrinsicDimensionEstimate).toBeNull()
    expect(parsed?.structureCandidates).toEqual(['UNKNOWN'])
    expect(parsed?.sourceRowCount).toBe(5000)
    expect(parsed?.sourceColumns).toEqual([{ name: 'x', physicalType: 'double' }])
  })

  it('rejects a payload whose kind is not StructureAssessment', () => {
    expect(parseStructureAssessment(payload({ kind: 'RepresentationSpec' }))).toBeNull()
  })

  it('rejects identifiers that are not UUIDs', () => {
    expect(parseStructureAssessment(payload({ id: 'artifact-1' }))).toBeNull()
    expect(parseStructureAssessment(payload({ dataset_version_id: 'not-a-uuid' }))).toBeNull()
    expect(parseStructureAssessment(payload({ research_version_id: 'version-1' }))).toBeNull()
  })

  it('rejects enum values outside the contract', () => {
    expect(parseStructureAssessment(payload({ periodicity: 'PERIODIC' }))).toBeNull()
    expect(parseStructureAssessment(payload({ time_basis: 'WALL_CLOCK' }))).toBeNull()
    expect(parseStructureAssessment(payload({ analysis_scope: 'FULL' }))).toBeNull()
    expect(parseStructureAssessment(payload({ artifact_access_class: 'PUBLIC' }))).toBeNull()
  })

  it('rejects an empty structure candidate list', () => {
    expect(parseStructureAssessment(payload({ structure_candidates: [] }))).toBeNull()
    expect(parseStructureAssessment(payload({ structure_candidates: ['TIME_SERIES', 'GAUSSIAN_PROCESS'] }))).toBeNull()
  })

  it('rejects a fit rows hash that is not a SHA256 digest', () => {
    expect(parseStructureAssessment(payload({ fit_rows_hash: 'abc' }))).toBeNull()
    expect(parseStructureAssessment(payload({ fit_rows_hash: 'A'.repeat(64) }))).toBeNull()
    expect(parseStructureAssessment(payload({ fit_rows_hash: 'a'.repeat(64) }))).not.toBeNull()
  })

  it('rejects source metadata that is not shaped as documented', () => {
    expect(parseStructureAssessment(payload({ source_metadata: { columns: [{ name: 'x' }] } }))).toBeNull()
    expect(parseStructureAssessment(payload({ source_metadata: { columns: 'x' } }))).toBeNull()
  })
})

describe('isStructureIdentified', () => {
  it('stays closed when the intrinsic dimension is not disclosed', () => {
    const assessment = parseStructureAssessment(payload())
    expect(assessment).not.toBeNull()
    expect(isStructureIdentified(assessment as StructureAssessment)).toBe(false)
  })

  it('requires both a disclosed dimension and a non-UNKNOWN candidate', () => {
    const unknownOnly = parseStructureAssessment(payload({ intrinsic_dimension_estimate: 2 }))
    expect(isStructureIdentified(unknownOnly as StructureAssessment)).toBe(false)

    const identified = parseStructureAssessment(payload({ intrinsic_dimension_estimate: 2, structure_candidates: ['TIME_SERIES'] }))
    expect(isStructureIdentified(identified as StructureAssessment)).toBe(true)
  })
})

describe('buildLatentRows', () => {
  it('records missing artifacts separately from parse failures', () => {
    const assessments: Record<string, StructureAssessment | null> = {
      [ARTIFACT_ID]: parseStructureAssessment(payload()),
    }
    const rows = buildLatentRows(
      [
        version({ id: VERSION_ID, structure_assessment_artifact_id: null }),
        version({ id: 'version-2', structure_assessment_artifact_id: ARTIFACT_ID }),
        version({ id: 'version-3', structure_assessment_artifact_id: 'artifact-broken' }),
      ],
      [research()],
      assessments,
      new Set(['artifact-broken']),
    )

    expect(rows).toHaveLength(3)
    expect(rows[0]?.assessment).toBeNull()
    expect(rows[0]?.parseFailed).toBe(false)
    expect(rows[1]?.assessment).not.toBeNull()
    expect(rows[2]?.parseFailed).toBe(true)
    expect(rows[0]?.researchName).toBe('sin 週期研究')

    const summary = summarizeLatent(rows)
    expect(summary).toEqual({ identified: 0, artifactBacked: 1, missing: 1, parseFailed: 1 })
  })

  it('falls back to a stable placeholder name when the research is unreadable', () => {
    const rows = buildLatentRows([version()], [], {}, new Set())
    expect(rows[0]?.researchName).toBe('未命名研究')
  })
})
