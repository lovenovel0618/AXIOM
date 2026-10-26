import { describe, expect, it } from 'vitest'
import type { Research, ResearchVersion } from '../src/api/research'
import type { BudgetUsage, Run } from '../src/api/runs'
import {
  buildCatalogCsv,
  buildCatalogRows,
  describeStatus,
  filterCatalogRows,
  isActiveRunStatus,
  latestVersionOf,
  sortCatalogRows,
  summarizeSelection,
  UNKNOWN,
  type CatalogSnapshot,
} from '../src/lib/researchCatalog'

const ZERO_USAGE: BudgetUsage = {
  cpu_seconds: 0,
  gpu_seconds: 0,
  tokens: 0,
  peak_memory_bytes: 0,
  elapsed_wall_seconds: 0,
  candidates_generated: 0,
  candidates_accepted: 0,
}

function research(id: string, name: string, createdAt: string): Research {
  return {
    kind: 'Research',
    id,
    tenant_id: 'tenant-1',
    schema_version: '2.0',
    created_at: createdAt,
    name,
    owner_id: 'owner-1',
  }
}

function researchVersion(
  id: string,
  researchId: string,
  status: ResearchVersion['status'],
  createdAt: string,
  frozenSubmissionIds: string[] = [],
): ResearchVersion {
  return {
    kind: 'ResearchVersion',
    id,
    tenant_id: 'tenant-1',
    schema_version: '2.0',
    created_at: createdAt,
    research_id: researchId,
    dataset_version_id: 'dataset-version-1',
    semantic_profile: {
      inputs: [],
      target: {
        name: 'y',
        unit: [],
        source_column: 'y',
        conversion: { source_unit: '1', scale: '1', offset: '0' },
      },
      units_confirmed: true,
      time_ordered: false,
      measurement_resolution: null,
      resolution_reason: 'ok',
      group_column: null,
    },
    budget: {
      cpu_seconds: 600,
      gpu_seconds: 0,
      wall_seconds: 300,
      tokens: 2000,
      candidate_limit: 40,
      memory_bytes: 2147483648,
    },
    purpose: 'DESCRIPTION',
    status,
    revision: 1,
    observation_split: {
      id: 'split-1',
      kind: 'EXPLICIT',
      dataset_version_id: 'dataset-version-1',
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
    frozen_submission_ids: frozenSubmissionIds,
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
      bootstrap_replicates: 100,
      bootstrap_seed: 0,
      block_method: null,
      block_length: null,
      practical_scale_override: null,
      practical_margin_ratio: '0.01',
      baseline: 'FIT_MEAN',
      practical_scale_reason: null,
    },
    evaluation_policy_hash: 'b'.repeat(64),
    research_budget_usage: ZERO_USAGE,
    structure_assessment_artifact_id: null,
  }
}

function run(
  id: string,
  type: Run['type'],
  status: Run['status'],
  createdAt: string,
  researchVersionId: string,
): Run {
  return {
    kind: 'Run',
    id,
    type,
    status,
    revision: 1,
    created_at: createdAt,
    dataset_id: null,
    research_version_id: researchVersionId,
    current_event_cursor: `RUN:${id}:0`,
    stop_reason: null,
    outcome_status: null,
  }
}

function snapshot(overrides: Partial<CatalogSnapshot> = {}): CatalogSnapshot {
  return {
    researches: [],
    versionsByResearch: {},
    runsByVersion: {},
    moreVersionsByResearch: {},
    ...overrides,
  }
}

describe('researchCatalog', () => {
  it('reports NONE when a research has no readable version', () => {
    const rows = buildCatalogRows(
      snapshot({ researches: [research('r1', 'sin-wave', '2026-10-26T01:00:00Z')] }),
    )

    expect(rows).toHaveLength(1)
    expect(rows[0]?.latestStatus).toBe('NONE')
    expect(rows[0]?.latestVersionId).toBeNull()
    expect(rows[0]?.latestPurpose).toBeNull()
    expect(rows[0]?.versionCount).toBe(0)
    expect(describeStatus(rows[0]?.latestStatus ?? 'NONE')).toBe('尚無版本')
  })

  it('picks the newest version by created_at, not by list order', () => {
    const rows = buildCatalogRows(
      snapshot({
        researches: [research('r1', 'sin-wave', '2026-10-26T01:00:00Z')],
        versionsByResearch: {
          r1: [
            researchVersion('v-new', 'r1', 'RUNNING', '2026-10-26T05:00:00Z'),
            researchVersion('v-old', 'r1', 'READY', '2026-10-26T02:00:00Z'),
          ],
        },
      }),
    )

    expect(rows[0]?.latestVersionId).toBe('v-new')
    expect(rows[0]?.latestStatus).toBe('RUNNING')
    expect(rows[0]?.versionCount).toBe(2)
  })

  it('counts runs only for versions whose runs were actually read', () => {
    const rows = buildCatalogRows(
      snapshot({
        researches: [research('r1', 'sin-wave', '2026-10-26T01:00:00Z')],
        versionsByResearch: {
          r1: [
            researchVersion('v1', 'r1', 'RUNNING', '2026-10-26T05:00:00Z'),
            researchVersion('v0', 'r1', 'READY', '2026-10-26T02:00:00Z'),
          ],
        },
        runsByVersion: {
          v1: [
            run('run-a', 'SEARCH', 'RUNNING', '2026-10-26T06:00:00Z', 'v1'),
            run('run-b', 'FIT', 'FAILED', '2026-10-26T07:00:00Z', 'v1'),
          ],
        },
      }),
    )

    const row = rows[0]
    expect(row?.runScopedVersionIds).toEqual(['v1'])
    expect(row?.runCount).toBe(2)
    expect(row?.activeRunCount).toBe(1)
    expect(row?.failedRunCount).toBe(1)
    expect(row?.searchRunCount).toBe(1)
    expect(row?.lastActivityAt).toBe('2026-10-26T07:00:00Z')
  })

  it('treats an unread version as unknown instead of zero runs', () => {
    const rows = buildCatalogRows(
      snapshot({
        researches: [research('r1', 'sin-wave', '2026-10-26T01:00:00Z')],
        versionsByResearch: { r1: [researchVersion('v1', 'r1', 'READY', '2026-10-26T05:00:00Z')] },
      }),
    )

    expect(rows[0]?.runScopedVersionIds).toEqual([])
    expect(rows[0]?.lastActivityAt).toBeNull()
    expect(buildCatalogCsv(rows)).toContain(UNKNOWN)
  })

  it('marks that the backend still has unread version pages', () => {
    const rows = buildCatalogRows(
      snapshot({
        researches: [research('r1', 'sin-wave', '2026-10-26T01:00:00Z')],
        versionsByResearch: { r1: [researchVersion('v1', 'r1', 'READY', '2026-10-26T05:00:00Z')] },
        moreVersionsByResearch: { r1: true },
      }),
    )

    expect(rows[0]?.hasMoreVersions).toBe(true)
  })

  it('sums frozen submissions across every readable version', () => {
    const rows = buildCatalogRows(
      snapshot({
        researches: [research('r1', 'sin-wave', '2026-10-26T01:00:00Z')],
        versionsByResearch: {
          r1: [
            researchVersion('v1', 'r1', 'READY', '2026-10-26T05:00:00Z', ['sub-1', 'sub-2']),
            researchVersion('v0', 'r1', 'READY', '2026-10-26T02:00:00Z', ['sub-3']),
          ],
        },
      }),
    )

    expect(rows[0]?.frozenSubmissionCount).toBe(3)
  })

  it('filters by keyword over name and id, and by latest status', () => {
    const rows = buildCatalogRows(
      snapshot({
        researches: [
          research('r1', 'sin-wave', '2026-10-26T01:00:00Z'),
          research('r2', 'cos-wave', '2026-10-26T02:00:00Z'),
        ],
        versionsByResearch: {
          r1: [researchVersion('v1', 'r1', 'FAILED', '2026-10-26T05:00:00Z')],
          r2: [researchVersion('v2', 'r2', 'READY', '2026-10-26T06:00:00Z')],
        },
      }),
    )

    expect(filterCatalogRows(rows, 'SIN', 'ALL').map((row) => row.id)).toEqual(['r1'])
    expect(filterCatalogRows(rows, 'r2', 'ALL').map((row) => row.id)).toEqual(['r2'])
    expect(filterCatalogRows(rows, '', 'READY').map((row) => row.id)).toEqual(['r2'])
    expect(filterCatalogRows(rows, '', 'NONE')).toEqual([])
  })

  it('sorts by created_at when no activity time is known', () => {
    const rows = buildCatalogRows(
      snapshot({
        researches: [
          research('r-old', 'a', '2026-10-26T01:00:00Z'),
          research('r-new', 'b', '2026-10-26T03:00:00Z'),
        ],
      }),
    )

    expect(sortCatalogRows(rows, 'CREATED_DESC').map((row) => row.id)).toEqual(['r-new', 'r-old'])
    expect(sortCatalogRows(rows, 'CREATED_ASC').map((row) => row.id)).toEqual(['r-old', 'r-new'])
    expect(sortCatalogRows(rows, 'NAME_ASC').map((row) => row.id)).toEqual(['r-old', 'r-new'])
  })

  it('places rows without activity time last in activity sort', () => {
    const rows = buildCatalogRows(
      snapshot({
        researches: [
          research('r-read', 'read', '2026-10-26T01:00:00Z'),
          research('r-unread', 'unread', '2026-10-26T03:00:00Z'),
        ],
        versionsByResearch: {
          'r-read': [researchVersion('v-read', 'r-read', 'RUNNING', '2026-10-26T02:00:00Z')],
          'r-unread': [researchVersion('v-unread', 'r-unread', 'READY', '2026-10-26T04:00:00Z')],
        },
        runsByVersion: {
          'v-read': [run('run-a', 'SEARCH', 'RUNNING', '2026-10-26T05:00:00Z', 'v-read')],
        },
      }),
    )

    const sorted = sortCatalogRows(rows, 'ACTIVITY_DESC')
    expect(sorted.map((row) => row.id)).toEqual(['r-read', 'r-unread'])
    expect(sorted[1]?.lastActivityAt).toBeNull()
  })

  it('sorts by version count when asked', () => {
    const rows = buildCatalogRows(
      snapshot({
        researches: [
          research('r-one', 'one', '2026-10-26T01:00:00Z'),
          research('r-two', 'two', '2026-10-26T02:00:00Z'),
        ],
        versionsByResearch: {
          'r-one': [researchVersion('v-a', 'r-one', 'READY', '2026-10-26T03:00:00Z')],
          'r-two': [
            researchVersion('v-b', 'r-two', 'READY', '2026-10-26T04:00:00Z'),
            researchVersion('v-c', 'r-two', 'READY', '2026-10-26T05:00:00Z'),
          ],
        },
      }),
    )

    expect(sortCatalogRows(rows, 'VERSION_DESC').map((row) => row.id)).toEqual(['r-two', 'r-one'])
  })

  it('summarizes a selection and reports ids outside the current view', () => {
    const rows = buildCatalogRows(
      snapshot({
        researches: [
          research('r1', 'one', '2026-10-26T01:00:00Z'),
          research('r2', 'two', '2026-10-26T02:00:00Z'),
        ],
        versionsByResearch: {
          r1: [researchVersion('v1', 'r1', 'RUNNING', '2026-10-26T05:00:00Z')],
          r2: [researchVersion('v2', 'r2', 'FAILED', '2026-10-26T06:00:00Z')],
        },
        runsByVersion: {
          v1: [run('run-a', 'SEARCH', 'RUNNING', '2026-10-26T07:00:00Z', 'v1')],
          v2: [run('run-b', 'FIT', 'FAILED', '2026-10-26T08:00:00Z', 'v2')],
        },
      }),
    )

    const summary = summarizeSelection(rows, ['r1', 'r2', 'r-missing'])
    expect(summary.selected).toBe(2)
    expect(summary.missing).toBe(1)
    expect(summary.versionCount).toBe(2)
    expect(summary.runCount).toBe(2)
    expect(summary.activeRunCount).toBe(1)
    expect(summary.failedRunCount).toBe(1)
    expect(summary.researchIds).toEqual(['r1', 'r2'])
  })

  it('exports CRLF csv with the unread scope spelled out', () => {
    const rows = buildCatalogRows(
      snapshot({
        researches: [research('r1', '"quoted"', '2026-10-26T01:00:00Z')],
      }),
    )

    const csv = buildCatalogCsv(rows)
    expect(csv.endsWith('\r\n')).toBe(true)
    expect(csv).toContain('research_id,name')
    expect(csv).toContain('""quoted""')
    expect(csv.split('\r\n')[1]).toContain(UNKNOWN)
  })

  it('treats only queued, running and cancel-requested runs as active', () => {
    expect(isActiveRunStatus('QUEUED')).toBe(true)
    expect(isActiveRunStatus('RUNNING')).toBe(true)
    expect(isActiveRunStatus('CANCEL_REQUESTED')).toBe(true)
    expect(isActiveRunStatus('SUCCEEDED')).toBe(false)
    expect(isActiveRunStatus('FAILED')).toBe(false)
    expect(isActiveRunStatus('CANCELLED')).toBe(false)
  })

  it('returns null for the newest version of an empty list', () => {
    expect(latestVersionOf([])).toBeNull()
  })
})
