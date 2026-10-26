import { describe, expect, it } from 'vitest'
import { createApiClient, type Fetcher } from '../src/api/client'
import type { Dataset, DatasetVersion, RunRecord } from '../src/api/datasets'
import {
  DATASETS_READ,
  DATA_UNKNOWN,
  buildCatalogRows,
  buildDiffRows,
  buildExploreAxes,
  buildExploreProjections,
  buildPipelineNodes,
  buildPipelineStages,
  buildPreviewTable,
  buildQualityDimensions,
  buildUploadSteps,
  buildVersionLineage,
  classifyAxis,
  filterCatalogRows,
  filterPreviewFields,
  latestAnalyzableVersion,
  loadDataCenter,
  metadataForVersion,
  resolveVersionId,
  summarizeCatalog,
  summarizeQuality,
} from '../src/lib/dataCenter'
import { runQuickAnalysis } from '../src/lib/dataAnalyze'
import type { SourceMetadata } from '../src/lib/semantics'

const SHA_A = 'a'.repeat(64)
const SHA_B = 'b'.repeat(64)
const DATASET_ID = '11111111-1111-1111-1111-111111111111'
const VERSION_ID = '22222222-2222-2222-2222-222222222222'
const RESEARCH_ID = '33333333-3333-3333-3333-333333333333'
const RESEARCH_VERSION_ID = '44444444-4444-4444-4444-444444444444'
const CSRF = 'csrf-1'

function dataset(overrides: Partial<Dataset> = {}): Dataset {
  return {
    kind: 'Dataset',
    id: DATASET_ID,
    tenant_id: '55555555-5555-5555-5555-555555555555',
    schema_version: '2.0',
    created_at: '2026-10-20T00:00:00Z',
    name: 'sin 週期資料',
    owner_id: '66666666-6666-6666-6666-666666666666',
    ...overrides,
  }
}

function version(overrides: Partial<DatasetVersion> = {}): DatasetVersion {
  return {
    kind: 'DatasetVersion',
    id: VERSION_ID,
    dataset_id: DATASET_ID,
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

function ingestRun(overrides: Partial<RunRecord> = {}): RunRecord {
  return {
    kind: 'Run',
    id: 'run-1',
    type: 'INGEST',
    status: 'SUCCEEDED',
    dataset_id: DATASET_ID,
    created_at: '2026-10-26T00:00:00Z',
    ...overrides,
  }
}

describe('loadDataCenter', () => {
  it('limits the read scope and flags datasets with a next page', async () => {
    const rows = Array.from({ length: DATASETS_READ + 2 }, (_item, index) =>
      dataset({ id: `dataset-${String(index)}`, name: `資料集 ${String(index)}` }),
    )
    const center = await loadDataCenter({
      listDatasets: () => Promise.resolve({ items: rows, next_cursor: null }),
      listVersions: () => Promise.resolve({ items: [version()], next_cursor: null }),
    })
    expect(center.datasets).toHaveLength(DATASETS_READ)
    expect(center.datasetTruncated).toBe(true)
    expect(center.scope.datasetsRead).toBe(DATASETS_READ)
  })

  it('keeps version reads per dataset and marks truncated version lists', async () => {
    const many = Array.from({ length: 9 }, (_item, index) =>
      version({ id: `v-${String(index)}`, created_at: `2026-10-0${String(index + 1)}T00:00:00Z` }),
    )
    const center = await loadDataCenter({
      listDatasets: () => Promise.resolve({ items: [dataset()], next_cursor: null }),
      listVersions: () => Promise.resolve({ items: many, next_cursor: null }),
    })
    expect(center.versionsByDataset[DATASET_ID]).toHaveLength(8)
    expect(center.versionTruncated).toEqual([DATASET_ID])
    expect(center.scope.versionsRead).toBe(8)
  })

  it('treats a failing version read as未取得 instead of failing the page', async () => {
    const center = await loadDataCenter({
      listDatasets: () => Promise.resolve({ items: [dataset()], next_cursor: null }),
      listVersions: () => Promise.reject(new Error('boom')),
    })
    expect(center.versionsByDataset[DATASET_ID]).toEqual([])
    expect(center.versionTruncated).toEqual([])
  })
})

describe('latestAnalyzableVersion / resolveVersionId / metadataForVersion', () => {
  it('picks the newest version that is available and has a preview', () => {
    const rows = [
      version({ id: 'old', created_at: '2026-10-24T00:00:00Z' }),
      version({ id: 'newest', created_at: '2026-10-26T00:00:00Z', structure_preview_artifact_id: null }),
      version({ id: 'mid', created_at: '2026-10-25T00:00:00Z' }),
    ]
    expect(latestAnalyzableVersion(rows)?.id).toBe('mid')
    expect(latestAnalyzableVersion([])).toBeNull()
  })

  it('accepts the requested version id only when it was actually read', () => {
    const rows = [version({ id: 'v1' }), version({ id: 'v2' })]
    expect(resolveVersionId(rows, 'v2')).toBe('v2')
    expect(resolveVersionId(rows, 'ghost')).toBe('v1')
    expect(resolveVersionId(rows, '')).toBe('v1')
    expect(resolveVersionId([], 'ghost')).toBe('')
  })

  it('returns null when the version or its preview is missing', () => {
    const cache = { 'preview-1': metadata() }
    expect(metadataForVersion(cache, null)).toBeNull()
    expect(metadataForVersion(cache, version({ structure_preview_artifact_id: null }))).toBeNull()
    expect(metadataForVersion(cache, version({ structure_preview_artifact_id: 'ghost' }))).toBeNull()
    expect(metadataForVersion(cache, version())).toEqual(metadata())
  })
})

describe('catalog rows', () => {
  it('summarises and filters rows with後端已揭露欄位', async () => {
    const center = await loadDataCenter({
      listDatasets: () =>
        Promise.resolve({
          items: [dataset({ id: 'd1', name: 'sin 週期' }), dataset({ id: 'd2', name: 'cos 週期' })],
          next_cursor: null,
        }),
      listVersions: (datasetId) =>
        Promise.resolve({
          items:
            datasetId === 'd1'
              ? [version({ dataset_id: 'd1', row_count: 100 }), version({ dataset_id: 'd1', id: 'v2', row_count: 200, status: 'UNAVAILABLE', structure_preview_artifact_id: null })]
              : [],
          next_cursor: null,
        }),
    })
    const rows = buildCatalogRows(center)
    expect(rows).toHaveLength(2)
    expect(rows[0]?.analyzeVersionId).toBe(VERSION_ID)
    expect(rows[1]?.analyzeVersionId).toBeNull()

    const summary = summarizeCatalog(rows)
    expect(summary).toEqual({ datasets: 2, versions: 2, rows: 300, unavailable: 1, analyzable: 1 })

    expect(filterCatalogRows(rows, 'sin')).toHaveLength(1)
    expect(filterCatalogRows(rows, 'd2')).toHaveLength(1)
    expect(filterCatalogRows(rows, '   ')).toHaveLength(2)
    expect(filterCatalogRows(rows, '不存在')).toHaveLength(0)
  })
})

describe('buildUploadSteps', () => {
  it('passes all four steps for a healthy version', () => {
    const steps = buildUploadSteps(version(), metadata(), [])
    expect(steps.map((step) => step.key)).toEqual(['INGEST', 'MAPPING', 'CHECK', 'SNAPSHOT'])
    expect(steps.every((step) => step.status === 'PASS')).toBe(true)
  })

  it('reports未取得 when nothing has been uploaded yet', () => {
    const steps = buildUploadSteps(null, null, [])
    expect(steps.every((step) => step.status === 'UNKNOWN')).toBe(true)
  })

  it('fails the ingest step when the latest ingest run failed', () => {
    const steps = buildUploadSteps(null, null, [ingestRun({ status: 'FAILED' })])
    expect(steps[0]?.status).toBe('FAIL')
    expect(steps[0]?.detail).toContain('FAILED')
  })

  it('fails mapping when there is no metadata and fails the snapshot when unavailable', () => {
    const steps = buildUploadSteps(version({ status: 'UNAVAILABLE' }), null, [])
    expect(steps[1]?.status).toBe('UNKNOWN')
    expect(steps[3]?.status).toBe('FAIL')
  })
})

describe('preview table', () => {
  it('maps columns and flags duplicates and missing types', () => {
    const table = buildPreviewTable(
      version({ row_count: 5000 }),
      metadata({
        columns: [
          { name: 'x', physical_type: 'FLOAT' },
          { name: 'x', physical_type: '' },
        ],
      }),
    )
    expect(table.declaredRowCount).toBe(5000)
    expect(table.previewRowCount).toBe(5000)
    expect(table.sampleRows).toBeNull()
    expect(table.dictionaryEntryCount).toBe(2)
    expect(table.fields[1]).toEqual({ name: 'x', physicalType: '', duplicate: true, missingType: true })
  })

  it('reports未取得 when the preview cannot be parsed', () => {
    const table = buildPreviewTable(version(), null)
    expect(table.previewRowCount).toBeNull()
    expect(table.fields).toEqual([])
    expect(table.dictionaryEntryCount).toBe(0)
  })

  it('filters fields by name or physical type', () => {
    const fields = [
      { name: 'x', physicalType: 'FLOAT', duplicate: false, missingType: false },
      { name: 'label', physicalType: 'VARCHAR', duplicate: false, missingType: false },
    ]
    expect(filterPreviewFields(fields, 'lab')).toHaveLength(1)
    expect(filterPreviewFields(fields, 'float')).toHaveLength(1)
    expect(filterPreviewFields(fields, '')).toHaveLength(2)
  })
})

describe('quality dimensions', () => {
  it('reports four statistical dimensions as未取得 and never guesses', () => {
    const dimensions = buildQualityDimensions(version(), metadata())
    expect(dimensions.map((dimension) => dimension.key)).toEqual(['MISSING', 'OUTLIER', 'DRIFT', 'LEAKAGE'])
    expect(dimensions.every((dimension) => dimension.status === 'UNKNOWN')).toBe(true)
    expect(dimensions[0]?.detail).toContain('2 個欄位')
  })

  it('counts check outcomes', () => {
    expect(
      summarizeQuality([
        { label: 'a', status: 'PASS', detail: '' },
        { label: 'b', status: 'FAIL', detail: '' },
        { label: 'c', status: 'UNKNOWN', detail: '' },
        { label: 'd', status: 'PASS', detail: '' },
      ]),
    ).toEqual({ pass: 2, fail: 1, unknown: 1 })
  })
})

describe('pipeline', () => {
  it('orders snapshot nodes oldest first and reports unavailable versions as failed', () => {
    const nodes = buildPipelineNodes([
      version({ id: 'new', created_at: '2026-10-26T00:00:00Z', row_count: 200 }),
      version({ id: 'old', created_at: '2026-10-24T00:00:00Z', row_count: 100, status: 'UNAVAILABLE' }),
    ])
    expect(nodes.map((node) => node.versionId)).toEqual(['old', 'new'])
    expect(nodes[0]?.status).toBe('FAIL')
    expect(nodes[1]?.status).toBe('PASS')
  })

  it('reports未取得 for every pipeline stage when there are no versions', () => {
    const stages = buildPipelineStages([], [], {})
    expect(stages.map((stage) => stage.key)).toEqual(['SELECT', 'DAG', 'PARAM', 'PREVIEW', 'EXEC', 'PUBLISH'])
    expect(stages.every((stage) => stage.status === 'UNKNOWN')).toBe(true)
  })

  it('only passes preview and publish when two parsed versions exist', () => {
    const versions = [
      version({ id: 'v1', row_count: 100, created_at: '2026-10-24T00:00:00Z' }),
      version({ id: 'v2', row_count: 200, created_at: '2026-10-26T00:00:00Z', structure_preview_artifact_id: 'preview-2' }),
    ]
    const stages = buildPipelineStages(
      buildPipelineNodes(versions),
      versions,
      { 'preview-1': metadata({ row_count: 100 }), 'preview-2': metadata({ row_count: 200 }) },
    )
    expect(stages.find((stage) => stage.key === 'SELECT')?.status).toBe('PASS')
    expect(stages.find((stage) => stage.key === 'PREVIEW')?.status).toBe('PASS')
    expect(stages.find((stage) => stage.key === 'EXEC')?.status).toBe('PASS')
    expect(stages.find((stage) => stage.key === 'PUBLISH')?.status).toBe('PASS')
    expect(stages.find((stage) => stage.key === 'DAG')?.status).toBe('UNKNOWN')
  })

  it('keeps preview未取得 when only one side parses', () => {
    const versions = [
      version({ id: 'v1', row_count: 100, created_at: '2026-10-24T00:00:00Z', structure_preview_artifact_id: null }),
      version({ id: 'v2', row_count: 200, created_at: '2026-10-26T00:00:00Z' }),
    ]
    const stages = buildPipelineStages(buildPipelineNodes(versions), versions, { 'preview-1': metadata({ row_count: 200 }) })
    expect(stages.find((stage) => stage.key === 'PREVIEW')?.status).toBe('UNKNOWN')
    expect(stages.find((stage) => stage.key === 'PREVIEW')?.detail).toContain('僅 1 個版本')
  })
})

describe('explore axes and projections', () => {
  it('classifies physical types without guessing unknown ones', () => {
    expect(classifyAxis('FLOAT')).toBe('NUMERIC')
    expect(classifyAxis(' int64 ')).toBe('NUMERIC')
    expect(classifyAxis('DECIMAL(10,2)')).toBe('NUMERIC')
    expect(classifyAxis('VARCHAR')).toBe('TEXT')
    expect(classifyAxis('date')).toBe('TEXT')
    expect(classifyAxis('')).toBe('UNKNOWN')
    expect(classifyAxis('GEOMETRY')).toBe('UNKNOWN')
  })

  it('builds axes from the parsed preview only', () => {
    expect(buildExploreAxes(null)).toEqual([])
    expect(buildExploreAxes(metadata())).toEqual([
      { name: 'x', physicalType: 'FLOAT', kind: 'NUMERIC' },
      { name: 'y', physicalType: 'FLOAT', kind: 'NUMERIC' },
    ])
  })

  it('reports every projection as未取得', () => {
    const empty = buildExploreProjections([])
    expect(empty.map((projection) => projection.key)).toEqual(['TIME', 'PHASE', 'FREQUENCY', 'HIGH_DIM'])
    expect(empty.every((projection) => projection.status === 'UNKNOWN')).toBe(true)
    expect(empty[0]?.detail).toContain('無候選座標軸')

    const withAxes = buildExploreProjections(buildExploreAxes(metadata()))
    expect(withAxes[3]?.detail).toContain('2 個候選座標軸')
  })
})

describe('version diff and lineage', () => {
  it('reports no change for identical versions', () => {
    const outcome = buildDiffRows(version({ id: 'v1' }), version({ id: 'v2' }), metadata(), metadata())
    expect(outcome.changedCount).toBe(0)
    expect(outcome.rows.every((row) => !row.changed)).toBe(true)
  })

  it('reports row, format, checksum and column changes', () => {
    const outcome = buildDiffRows(
      version({ id: 'v1', row_count: 100 }),
      version({ id: 'v2', row_count: 150, format: 'JSON', sha256: SHA_B, created_at: '2026-10-27T00:00:00Z' }),
      metadata({ columns: [{ name: 'x', physical_type: 'FLOAT' }] }),
      metadata({
        columns: [
          { name: 'x', physical_type: 'FLOAT' },
          { name: 'z', physical_type: 'INT' },
        ],
      }),
    )
    const byLabel = (label: string) => outcome.rows.find((row) => row.label === label)
    expect(byLabel('列數')?.changed).toBe(true)
    expect(byLabel('格式')?.changed).toBe(true)
    expect(byLabel('檔案指紋')?.changed).toBe(true)
    expect(byLabel('新增欄位')?.target).toBe('z')
    expect(byLabel('移除欄位')?.target).toBe('無')
    expect(outcome.changedCount).toBe(5)
  })

  it('marks column diff as未取得 when a preview is missing', () => {
    const outcome = buildDiffRows(version({ id: 'v1' }), version({ id: 'v2' }), null, metadata())
    const added = outcome.rows.find((row) => row.label === '新增欄位')
    expect(added?.target).toBe('未取得（需兩邊皆有結構預覽）')
    expect(added?.changed).toBe(false)
  })

  it('lists lineage in chronological order without inventing parents', () => {
    const entries = buildVersionLineage([
      version({ id: 'new', created_at: '2026-10-26T00:00:00Z', row_count: 200 }),
      version({ id: 'old', created_at: '2026-10-24T00:00:00Z', row_count: 100 }),
    ])
    expect(entries.map((entry) => entry.versionId)).toEqual(['old', 'new'])
    expect(entries[0]?.label).toBe('2026-10-24T00:00:00Z｜CSV｜100 列')
  })
})

describe('runQuickAnalysis', () => {
  function scenario(responder: (url: string, method: string) => Response): ReturnType<typeof createApiClient> {
    const fetcher: Fetcher = (url, init) => Promise.resolve(responder(url, init?.method ?? 'GET'))
    return createApiClient(fetcher, () => CSRF)
  }

  function json(value: unknown, status = 200): Response {
    return new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } })
  }

  it('refuses an unusable version before touching the network', async () => {
    const client = scenario(() => {
      throw new Error('不應發出請求')
    })
    const outcome = await runQuickAnalysis(client, dataset(), version({ status: 'UNAVAILABLE' }), metadata())
    expect(outcome.ok).toBe(false)
    expect(outcome.ok || outcome.reason).toContain('不可用')
  })

  it('refuses when the preview artifact is missing', async () => {
    const client = scenario(() => {
      throw new Error('不應發出請求')
    })
    const outcome = await runQuickAnalysis(
      client,
      dataset(),
      version({ structure_preview_artifact_id: null }),
      metadata(),
    )
    expect(outcome.ok).toBe(false)
    expect(outcome.ok || outcome.reason).toContain('沒有結構預覽')
  })

  it('refuses when the preview cannot be parsed', async () => {
    const client = scenario(() => {
      throw new Error('不應發出請求')
    })
    const outcome = await runQuickAnalysis(client, dataset(), version(), null)
    expect(outcome.ok).toBe(false)
    expect(outcome.ok || outcome.reason).toContain('格式不符')
  })

  it('surfaces the draft problems instead of sending a half-built request', async () => {
    const client = scenario(() => {
      throw new Error('不應發出請求')
    })
    const outcome = await runQuickAnalysis(client, dataset(), version({ row_count: 2 }), metadata({ row_count: 2 }))
    expect(outcome.ok).toBe(false)
    expect(outcome.ok || outcome.reason).toContain('無法自動建立分析草稿')
  })

  it('creates the research, version and PROFILE run in order', async () => {
    const urls: string[] = []
    const client = scenario((url, method) => {
      urls.push(`${method} ${url}`)
      if (method === 'POST' && url === '/api/v2/researches') {
        return json({ kind: 'Research', id: RESEARCH_ID, name: '快速分析' })
      }
      if (method === 'POST' && url === `/api/v2/researches/${RESEARCH_ID}/versions`) {
        return json({ id: RESEARCH_VERSION_ID, revision: 3 })
      }
      if (method === 'POST' && url === `/api/v2/research-versions/${RESEARCH_VERSION_ID}/validate`) {
        return json({ id: 'run-1', status: 'QUEUED' })
      }
      if (method === 'GET' && url === `/api/v2/research-versions/${RESEARCH_VERSION_ID}`) {
        return json({ id: RESEARCH_VERSION_ID })
      }
      return json({ code: 'NOT_FOUND' }, 404)
    })
    const outcome = await runQuickAnalysis(client, dataset(), version(), metadata())
    expect(outcome.ok).toBe(true)
    expect(outcome.ok && outcome.analysis).toEqual({
      researchId: RESEARCH_ID,
      researchVersionId: RESEARCH_VERSION_ID,
      runStatus: 'QUEUED',
    })
    expect(urls).toEqual([
      'POST /api/v2/researches',
      `POST /api/v2/researches/${RESEARCH_ID}/versions`,
      `POST /api/v2/research-versions/${RESEARCH_VERSION_ID}/validate`,
      `GET /api/v2/research-versions/${RESEARCH_VERSION_ID}`,
    ])
  })
})

describe('unknown markers', () => {
  it('uses the shared未取得 label', () => {
    expect(DATA_UNKNOWN).toBe('未取得')
  })
})
