import { describe, expect, it } from 'vitest'
import type { DatasetVersion } from '../src/api/datasets'
import type { SourceMetadata } from '../src/lib/semantics'
import {
  buildDatasetDigest,
  buildQualityChecks,
  compareVersions,
  recentVersions,
  summarizeStructure,
} from '../src/lib/datasetWorkbench'

const SHA_A = 'a'.repeat(64)
const SHA_B = 'b'.repeat(64)

function version(overrides: Partial<DatasetVersion> = {}): DatasetVersion {
  return {
    kind: 'DatasetVersion',
    id: 'version-1',
    dataset_id: 'dataset-1',
    created_at: '2026-10-26T00:00:00Z',
    format: 'CSV',
    row_count: 5000,
    sha256: SHA_A,
    status: 'AVAILABLE',
    artifact_id: 'artifact-1',
    structure_preview_artifact_id: 'preview-1',
    ...overrides,
  }
}

function metadata(overrides: Partial<SourceMetadata> = {}): SourceMetadata {
  return {
    row_count: 5000,
    columns: [
      { name: 'x', physical_type: 'FLOAT' },
      { name: 'y', physical_type: 'FLOAT' },
    ],
    ...overrides,
  }
}

describe('buildDatasetDigest', () => {
  it('counts versions, availability, rows and previews', () => {
    const digest = buildDatasetDigest([
      version({ id: 'v1', row_count: 100, created_at: '2026-10-24T00:00:00Z' }),
      version({ id: 'v2', row_count: 200, status: 'UNAVAILABLE', structure_preview_artifact_id: null, format: 'JSON', created_at: '2026-10-26T00:00:00Z' }),
    ])
    expect(digest.versionCount).toBe(2)
    expect(digest.availableCount).toBe(1)
    expect(digest.unavailableCount).toBe(1)
    expect(digest.totalRows).toBe(300)
    expect(digest.previewCount).toBe(1)
    expect(digest.formats).toEqual(['CSV', 'JSON'])
    expect(digest.latestVersion?.id).toBe('v2')
  })

  it('returns a null latest version when there are no versions', () => {
    const digest = buildDatasetDigest([])
    expect(digest.latestVersion).toBeNull()
    expect(digest.formats).toEqual([])
  })
})

describe('summarizeStructure', () => {
  it('reports duplicates and missing physical types', () => {
    const summary = summarizeStructure(
      metadata({
        columns: [
          { name: 'x', physical_type: 'FLOAT' },
          { name: 'x', physical_type: '' },
        ],
      }),
    )
    expect(summary?.duplicateNames).toEqual(['x'])
    expect(summary?.missingTypeNames).toEqual(['x'])
  })

  it('returns null when there is no metadata', () => {
    expect(summarizeStructure(null)).toBeNull()
  })
})

describe('buildQualityChecks', () => {
  it('marks unparsable preview as unknown rather than guessing', () => {
    const checks = buildQualityChecks(version({ row_count: 2 }), null)
    expect(checks.find((check) => check.label === '結構預覽可解析')?.status).toBe('UNKNOWN')
    expect(checks.find((check) => check.label === '欄位齊備且不重複')?.status).toBe('UNKNOWN')
    expect(checks.find((check) => check.label === '列數足夠三段切分')?.status).toBe('FAIL')
  })

  it('fails when preview row count disagrees with the version', () => {
    const checks = buildQualityChecks(version({ row_count: 5000 }), metadata({ row_count: 4999 }))
    expect(checks.find((check) => check.label === '結構預覽可解析')?.status).toBe('FAIL')
  })

  it('passes a healthy version', () => {
    const checks = buildQualityChecks(version(), metadata())
    expect(checks.every((check) => check.status === 'PASS')).toBe(true)
  })

  it('fails when the checksum is not a sha256 digest', () => {
    const checks = buildQualityChecks(version({ sha256: 'not-a-digest' }), metadata())
    expect(checks.find((check) => check.label === '檔案指紋齊備')?.status).toBe('FAIL')
  })
})

describe('compareVersions', () => {
  it('reports row delta, format and checksum changes', () => {
    const diff = compareVersions(
      version({ id: 'v1', row_count: 100 }),
      version({ id: 'v2', row_count: 150, format: 'JSON', sha256: SHA_B }),
      metadata({ columns: [{ name: 'x', physical_type: 'FLOAT' }] }),
      metadata({
        columns: [
          { name: 'x', physical_type: 'FLOAT' },
          { name: 'z', physical_type: 'INT' },
        ],
      }),
    )
    expect(diff.rowDelta).toBe(50)
    expect(diff.formatChanged).toBe(true)
    expect(diff.sameFile).toBe(false)
    expect(diff.columnsAdded).toEqual(['z'])
    expect(diff.columnsRemoved).toEqual([])
  })

  it('omits column diff when either preview is unavailable', () => {
    const diff = compareVersions(version({ id: 'v1' }), version({ id: 'v2' }), null, metadata())
    expect(diff.columnsAdded).toBeNull()
    expect(diff.columnsRemoved).toBeNull()
  })

  it('reports identical files', () => {
    const diff = compareVersions(version({ id: 'v1' }), version({ id: 'v2' }), metadata(), metadata())
    expect(diff.sameFile).toBe(true)
    expect(diff.rowDelta).toBe(0)
  })
})

describe('recentVersions', () => {
  it('sorts newest first and respects the limit', () => {
    const rows = [
      version({ id: 'old', created_at: '2026-10-20T00:00:00Z' }),
      version({ id: 'new', created_at: '2026-10-26T00:00:00Z' }),
      version({ id: 'mid', created_at: '2026-10-24T00:00:00Z' }),
    ]
    expect(recentVersions(rows).map((row) => row.id)).toEqual(['new', 'mid', 'old'])
    expect(recentVersions(rows, 2).map((row) => row.id)).toEqual(['new', 'mid'])
  })
})
