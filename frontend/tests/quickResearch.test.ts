import { describe, expect, it } from 'vitest'
import type { DatasetVersion } from '../src/api/datasets'
import { buildQuickResearchDraft, quickResearchName } from '../src/lib/quickResearch'

function version(overrides: Partial<DatasetVersion> = {}): DatasetVersion {
  return {
    kind: 'DatasetVersion',
    id: '11111111-1111-1111-1111-111111111111',
    dataset_id: '22222222-2222-2222-2222-222222222222',
    created_at: '2026-10-26T00:00:00Z',
    format: 'CSV',
    row_count: 5000,
    sha256: 'a'.repeat(64),
    status: 'AVAILABLE',
    artifact_id: '33333333-3333-3333-3333-333333333333',
    structure_preview_artifact_id: '44444444-4444-4444-4444-444444444444',
    ...overrides,
  }
}

describe('quickResearchName', () => {
  it('prefixes the dataset name and keeps a stable timestamp shape', () => {
    expect(quickResearchName('sin-periodic-5000', new Date('2026-10-26T06:30:45Z'))).toBe(
      'sin-periodic-5000 分析 2026-10-26 06:30:45',
    )
  })
})

describe('buildQuickResearchDraft', () => {
  it('builds a valid default request from the first two columns', () => {
    const draft = buildQuickResearchDraft(version(), {
      row_count: 5000,
      columns: [
        { name: 'x', physical_type: 'float64' },
        { name: 'y', physical_type: 'float64' },
      ],
    })
    expect(draft.problems).toEqual([])
    expect(draft.request?.dataset_version_id).toBe('11111111-1111-1111-1111-111111111111')
    expect(draft.request?.semantic_profile.inputs[0]?.source_column).toBe('x')
    expect(draft.request?.semantic_profile.target.source_column).toBe('y')
    expect(draft.request?.observation_split.fit).toHaveLength(3000)
    expect(draft.request?.observation_split.development).toHaveLength(1000)
    expect(draft.request?.observation_split.final_test).toHaveLength(1000)
  })

  it('falls back to safe symbol names when columns are not identifier-like', () => {
    const draft = buildQuickResearchDraft(version(), {
      row_count: 10,
      columns: [
        { name: 'input value', physical_type: 'float64' },
        { name: 'target value', physical_type: 'float64' },
      ],
    })
    expect(draft.problems).toEqual([])
    expect(draft.request?.semantic_profile.inputs[0]?.name).toBe('x')
    expect(draft.request?.semantic_profile.target.name).toBe('y')
  })
})
