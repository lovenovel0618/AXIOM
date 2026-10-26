import { describe, expect, it } from 'vitest'
import type { RunEventEnvelope } from '../src/lib/events'
import type { FlowNode } from '../src/lib/flow'
import {
  buildCandidateFocusDetailPanel,
  buildCandidateFocusSummary,
  buildFocusCollectionDigest,
  buildNodeActionLinks,
  buildSubmissionFocusDetailPanel,
  buildSubmissionFocusSummary,
  collectCandidateCollectionLinks,
  collectSubmissionCollectionLink,
  findNodeIdsByRecordValues,
  groupNodeArtifacts,
  groupNodeEvents,
  recentNodeEvents,
  summarizeEventPayload,
} from '../src/lib/researchNodeDetails'

const event = (sequence: number, event_type: string, occurred_at: string): RunEventEnvelope => ({
  event_id: `${event_type}-${sequence}`,
  event_type,
  sequence,
  occurred_at,
  run_id: 'run-1',
  stream_scope: 'RUN',
  payload: { value: sequence },
})

const node = (overrides: Partial<FlowNode> = {}): FlowNode => ({
  id: 'candidate:cand-1',
  kind: 'CANDIDATE',
  column: 4,
  row: 0,
  title: '候選 #1',
  subtitle: 'POLYNOMIAL',
  badge: 'PENDING',
  tone: 'RUNNING',
  records: [
    { label: '候選識別碼', value: 'cand-1' },
    { label: '所屬搜尋任務', value: 'run-search-1' },
  ],
  artifacts: [],
  events: [],
  runId: null,
  ...overrides,
})

describe('researchNodeDetails', () => {
  it('groups artifacts by label', () => {
    const groups = groupNodeArtifacts([
      { id: 'a1', label: '證據包' },
      { id: 'a2', label: '證據包' },
      { id: 'a3', label: '品質報告產物' },
    ])
    expect(groups).toHaveLength(2)
    expect(groups[0]?.items).toHaveLength(2)
  })

  it('groups events by type and sorts by latest time', () => {
    const groups = groupNodeEvents([
      event(1, 'RUN_STARTED', '2026-10-26T00:00:00Z'),
      event(2, 'RUN_PROGRESS', '2026-10-26T00:01:00Z'),
      event(3, 'RUN_PROGRESS', '2026-10-26T00:02:00Z'),
    ])
    expect(groups[0]?.type).toBe('RUN_PROGRESS')
    expect(groups[0]?.count).toBe(2)
  })

  it('returns recent events in descending sequence order', () => {
    const rows = recentNodeEvents([event(1, 'A', 'a'), event(3, 'C', 'c'), event(2, 'B', 'b')], 2)
    expect(rows.map((row) => row.sequence)).toEqual([3, 2])
  })

  it('builds candidate and submission shortcuts', () => {
    const candidateActions = buildNodeActionLinks(node(), (extra) => ({ ref: '/researches/r1', ...(extra ?? {}) }))
    expect(candidateActions.map((row) => row.label)).toContain('回到發現頁')

    const submissionActions = buildNodeActionLinks(
      node({
        id: 'submission:sub-1',
        kind: 'SUBMISSION',
        records: [{ label: '提交識別碼', value: 'sub-1' }],
      }),
      (extra) => ({ ref: '/researches/r1', ...(extra ?? {}) }),
    )
    expect(submissionActions.map((row) => row.label)).toContain('前往驗證頁')
  })

  it('collects visible candidate nodes into discoveries links', () => {
    const links = collectCandidateCollectionLinks([
      node(),
      node({
        id: 'candidate:cand-2',
        title: '候選 #2',
        records: [
          { label: '候選識別碼', value: 'cand-2' },
          { label: '所屬搜尋任務', value: 'run-search-1' },
        ],
      }),
      node({
        id: 'candidate:cand-3',
        title: '候選 #3',
        records: [
          { label: '候選識別碼', value: 'cand-3' },
          { label: '所屬搜尋任務', value: 'run-search-2' },
        ],
      }),
    ])
    expect(links).toHaveLength(2)
    expect(links[0]?.searchRunId).toBe('run-search-1')
    expect(links[0]?.candidateIds).toEqual(['cand-1', 'cand-2'])
  })

  it('collects visible submission nodes into one verification link', () => {
    const link = collectSubmissionCollectionLink([
      node({
        id: 'submission:sub-1',
        kind: 'SUBMISSION',
        records: [{ label: '提交識別碼', value: 'sub-1' }],
      }),
      node({
        id: 'submission:sub-2',
        kind: 'SUBMISSION',
        title: '提交 #2',
        records: [{ label: '提交識別碼', value: 'sub-2' }],
      }),
    ])
    expect(link?.submissionIds).toEqual(['sub-1', 'sub-2'])
  })

  it('finds node ids by record values', () => {
    const ids = findNodeIdsByRecordValues(
      [
        node({
          id: 'candidate:cand-1',
          kind: 'CANDIDATE',
          records: [{ label: '候選識別碼', value: 'cand-1' }],
        }),
        node({
          id: 'submission:sub-1',
          kind: 'SUBMISSION',
          records: [{ label: '提交識別碼', value: 'sub-1' }],
        }),
        node({
          id: 'submission:sub-2',
          kind: 'SUBMISSION',
          records: [{ label: '提交識別碼', value: 'sub-2' }],
        }),
      ],
      '候選識別碼',
      ['cand-1'],
    )
    expect(ids).toEqual(['candidate:cand-1'])
  })

  it('builds a candidate focus summary with missing ids and grouped links', () => {
    const summary = buildCandidateFocusSummary(
      [
        node(),
        node({
          id: 'candidate:cand-2',
          title: '候選 #2',
          records: [
            { label: '候選識別碼', value: 'cand-2' },
            { label: '所屬搜尋任務', value: 'run-search-1' },
          ],
        }),
      ],
      ['cand-1', 'cand-2', 'cand-missing', 'cand-1'],
    )

    expect(summary?.requestedIds).toEqual(['cand-1', 'cand-2', 'cand-missing'])
    expect(summary?.matchedValues).toEqual(['cand-1', 'cand-2'])
    expect(summary?.missingIds).toEqual(['cand-missing'])
    expect(summary?.groups[0]?.candidateIds).toEqual(['cand-1', 'cand-2'])
  })

  it('builds candidate focus detail panel in requested order with aggregate counts', () => {
    const panel = buildCandidateFocusDetailPanel(
      [
        node({
          id: 'candidate:cand-1',
          title: '候選 #1',
          badge: 'PENDING',
          tone: 'RUNNING',
          artifacts: [{ id: 'artifact-1', label: '證據' }],
          events: [event(1, 'RUN_PROGRESS', '2026-10-26T00:00:00Z')],
          records: [
            { label: '候選識別碼', value: 'cand-1' },
            { label: '所屬搜尋任務', value: 'run-search-1' },
          ],
        }),
        node({
          id: 'candidate:cand-2',
          title: '候選 #2',
          badge: 'FINISHED',
          tone: 'OK',
          artifacts: [{ id: 'artifact-2', label: '證據' }],
          events: [event(2, 'RUN_FINISHED', '2026-10-26T00:01:00Z'), event(3, 'RUN_STABLE', '2026-10-26T00:02:00Z')],
          records: [
            { label: '候選識別碼', value: 'cand-2' },
            { label: '所屬搜尋任務', value: 'run-search-2' },
          ],
        }),
      ],
      ['cand-2', 'cand-1', 'cand-missing'],
    )

    expect(panel?.items.map((item) => item.primaryValue)).toEqual(['cand-2', 'cand-1'])
    expect(panel?.totalArtifacts).toBe(2)
    expect(panel?.totalEvents).toBe(3)
    expect(panel?.toneCounts.OK).toBe(1)
    expect(panel?.toneCounts.RUNNING).toBe(1)
    expect(panel?.missingIds).toEqual(['cand-missing'])
  })

  it('builds a submission focus summary with missing ids', () => {
    const summary = buildSubmissionFocusSummary(
      [
        node({
          id: 'submission:sub-1',
          kind: 'SUBMISSION',
          records: [{ label: '提交識別碼', value: 'sub-1' }],
        }),
        node({
          id: 'submission:sub-2',
          kind: 'SUBMISSION',
          records: [{ label: '提交識別碼', value: 'sub-2' }],
        }),
      ],
      ['sub-1', 'sub-missing'],
    )

    expect(summary?.requestedIds).toEqual(['sub-1', 'sub-missing'])
    expect(summary?.matchedValues).toEqual(['sub-1'])
    expect(summary?.missingIds).toEqual(['sub-missing'])
    expect(summary?.group?.submissionIds).toEqual(['sub-1'])
  })

  it('builds submission focus detail panel', () => {
    const panel = buildSubmissionFocusDetailPanel(
      [
        node({
          id: 'submission:sub-1',
          kind: 'SUBMISSION',
          badge: 'EVALUATED',
          tone: 'OK',
          artifacts: [{ id: 'artifact-1', label: '報告' }],
          events: [event(1, 'FINALIZED', '2026-10-26T00:00:00Z')],
          records: [{ label: '提交識別碼', value: 'sub-1' }],
        }),
        node({
          id: 'submission:sub-2',
          kind: 'SUBMISSION',
          badge: 'PENDING',
          tone: 'PENDING',
          records: [{ label: '提交識別碼', value: 'sub-2' }],
        }),
      ],
      ['sub-2', 'sub-1'],
    )

    expect(panel?.items.map((item) => item.primaryValue)).toEqual(['sub-2', 'sub-1'])
    expect(panel?.totalArtifacts).toBe(1)
    expect(panel?.totalEvents).toBe(1)
    expect(panel?.toneCounts.PENDING).toBe(1)
    expect(panel?.toneCounts.OK).toBe(1)
  })

  it('summarizes large payloads', () => {
    expect(summarizeEventPayload({ text: 'x'.repeat(400) })).toContain('...')
  })

  it('aggregates collection artifacts and events across focus members', () => {
    const nodes = [
      node({
        id: 'candidate:cand-1',
        title: '候選 #1',
        artifacts: [{ id: 'artifact-shared', label: '證據包' }],
        events: [event(1, 'RUN_PROGRESS', '2026-10-26T00:00:00Z')],
        records: [
          { label: '候選識別碼', value: 'cand-1' },
          { label: '所屬搜尋任務', value: 'run-search-1' },
        ],
      }),
      node({
        id: 'candidate:cand-2',
        title: '候選 #2',
        artifacts: [
          { id: 'artifact-shared', label: '證據包' },
          { id: 'artifact-only-2', label: '診斷產物' },
        ],
        events: [
          event(2, 'RUN_PROGRESS', '2026-10-26T00:05:00Z'),
          event(3, 'RUN_FINISHED', '2026-10-26T00:06:00Z'),
        ],
        records: [
          { label: '候選識別碼', value: 'cand-2' },
          { label: '所屬搜尋任務', value: 'run-search-1' },
        ],
      }),
    ]
    const panel = buildCandidateFocusDetailPanel(nodes, ['cand-1', 'cand-2'])
    expect(panel).not.toBeNull()

    const digest = panel === null ? null : buildFocusCollectionDigest(nodes, panel)
    expect(digest?.memberStats.map((stat) => stat.value)).toEqual(['cand-1', 'cand-2'])
    expect(digest?.memberStats[1]?.eventCount).toBe(2)
    expect(digest?.artifactGroups[0]?.label).toBe('證據包')
    expect(digest?.artifactGroups[0]?.shared).toBe(true)
    expect(digest?.artifactGroups[0]?.memberCount).toBe(2)
    expect(digest?.sharedArtifactLabels).toEqual(['證據包'])
    expect(digest?.eventGroups[0]?.type).toBe('RUN_PROGRESS')
    expect(digest?.eventGroups[0]?.count).toBe(2)
    expect(digest?.eventGroups[0]?.shared).toBe(true)
    expect(digest?.sharedEventTypes).toContain('RUN_PROGRESS')
    expect(digest?.sharedEventTypes).not.toContain('RUN_FINISHED')
  })

  it('returns no digest when a focus panel has no members', () => {
    const panel = buildCandidateFocusDetailPanel([], ['cand-1'])
    expect(panel?.items).toEqual([])
    expect(panel === null ? null : buildFocusCollectionDigest([], panel)).toBeNull()
  })
})
