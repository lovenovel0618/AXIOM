import { describe, expect, it } from 'vitest'
import { createApiClient, type Fetcher } from '../src/api/client'
import { getArtifactContent } from '../src/api/artifacts'
import {
  createResearch,
  createResearchVersion,
  fetchResearchVersionEvents,
  getFrozenSubmission,
  listResearchVersionRuns,
  validateDraft,
  type CreateResearchVersionRequest,
  type Research,
} from '../src/api/research'

const RESEARCH_ID = '11111111-1111-1111-1111-111111111111'
const VERSION_ID = '22222222-2222-2222-2222-222222222222'
const DATASET_ID = '33333333-3333-3333-3333-333333333333'
const PREVIEW_ID = '44444444-4444-4444-4444-444444444444'
const SUBMISSION_ID = '77777777-7777-7777-7777-777777777777'
const CSRF = 'csrf-1'

interface Call {
  url: string
  method: string
  headers: Headers
  body: unknown
}

function scenario(responder: (call: Call) => Response): { calls: Call[]; client: ReturnType<typeof createApiClient> } {
  const calls: Call[] = []
  const fetcher: Fetcher = async (url, init) => {
    const call: Call = { url, method: init?.method ?? 'GET', headers: new Headers(init?.headers), body: init?.body }
    calls.push(call)
    return responder(call)
  }
  return { calls, client: createApiClient(fetcher, () => CSRF) }
}

function researchDocument(): Research {
  return {
    kind: 'Research',
    id: RESEARCH_ID,
    tenant_id: '55555555-5555-5555-5555-555555555555',
    schema_version: '2.0',
    created_at: '2026-10-21T00:00:00Z',
    name: 'demo',
    owner_id: '66666666-6666-6666-6666-666666666666',
  }
}

function draftRequest(): CreateResearchVersionRequest {
  const quantity = (name: string, column: string): CreateResearchVersionRequest['semantic_profile']['target'] => ({
    name,
    unit: [0, 0, 0, 0, 0, 0, 0],
    source_column: column,
    conversion: { source_unit: '1', scale: '1', offset: '0' },
  })
  return {
    dataset_version_id: DATASET_ID,
    semantic_profile: {
      inputs: [quantity('x', 'x_col')],
      target: quantity('y', 'y_col'),
      units_confirmed: true,
      time_ordered: false,
      measurement_resolution: null,
      resolution_reason: '欄位以 0.001 為最小刻度。',
      group_column: null,
    },
    budget: { cpu_seconds: 60, gpu_seconds: 0, wall_seconds: 120, tokens: 0, candidate_limit: 0, memory_bytes: 2147483648 },
    purpose: 'DESCRIPTION',
    observation_split: {
      kind: 'EXPLICIT',
      dataset_version_id: DATASET_ID,
      fit: [0, 1],
      development: [2],
      final_test: [3],
      gap_rows: 0,
      lookback_rows: 0,
      horizon_rows: 0,
      seed: 0,
      time_column: null,
      group_column: null,
      group_assignment_digest: null,
      splitter_version: 'axiom-ui-sequential-v1',
      policy_version: '2.0',
      sealed_final_test: true,
    },
    domain: [{ name: 'x', lower: { numerator: '0', denominator: '1' }, upper: { numerator: '1', denominator: '1' }, lower_closed: true, upper_closed: true }],
    evaluation_policy: {
      policy_version: '1.0',
      metric_version: '2.0',
      error_model: 'UNSPECIFIED',
      absolute_error_bound: null,
      comparison_method: 'NONE',
      bootstrap_replicates: 2000,
      bootstrap_seed: 0,
      block_method: null,
      block_length: null,
      practical_scale_override: null,
      practical_margin_ratio: '0.01',
      baseline: 'FIT_MEAN',
      practical_scale_reason: null,
    },
  }
}

describe('createResearch', () => {
  it('posts the name with an idempotency key and CSRF token', async () => {
    const { calls, client } = scenario(() => Response.json(researchDocument(), { status: 201 }))
    const research = await createResearch(client, 'demo')
    expect(research.id).toBe(RESEARCH_ID)
    const call = calls[0]
    expect(call?.url).toBe('/api/v2/researches')
    expect(call?.method).toBe('POST')
    expect(call?.headers.get('Idempotency-Key')).toMatch(/\S/)
    expect(call?.headers.get('X-CSRFToken')).toBe(CSRF)
    expect(call?.body).toBe(JSON.stringify({ name: 'demo' }))
  })
})

describe('createResearchVersion', () => {
  it('posts the immutable draft under the research container', async () => {
    const request = draftRequest()
    const { calls, client } = scenario(() => Response.json({ id: VERSION_ID, status: 'DRAFT', revision: 0 }, { status: 201 }))
    const version = await createResearchVersion(client, RESEARCH_ID, request)
    expect(version.status).toBe('DRAFT')
    expect(calls[0]?.url).toBe(`/api/v2/researches/${RESEARCH_ID}/versions`)
    expect(calls[0]?.headers.get('Idempotency-Key')).toMatch(/\S/)
    expect(calls[0]?.body).toBe(JSON.stringify(request))
  })
})

describe('validateDraft', () => {
  it('sends the current control revision and an empty body without a run budget', async () => {
    const { calls, client } = scenario(() => Response.json({ kind: 'Run', id: 'run-1', status: 'QUEUED' }, { status: 202 }))
    const run = await validateDraft(client, VERSION_ID, 3)
    expect(run.status).toBe('QUEUED')
    const call = calls[0]
    expect(call?.url).toBe(`/api/v2/research-versions/${VERSION_ID}/validate`)
    expect(call?.headers.get('If-Control-Revision')).toBe('3')
    expect(call?.headers.get('Idempotency-Key')).toMatch(/\S/)
    expect(call?.body).toBe('{}')
  })

  it('forwards an explicit run budget when supplied', async () => {
    const budget = draftRequest().budget
    const { calls, client } = scenario(() => Response.json({ kind: 'Run', id: 'run-1', status: 'QUEUED' }, { status: 202 }))
    await validateDraft(client, VERSION_ID, 0, budget)
    expect(calls[0]?.body).toBe(JSON.stringify({ run_budget: budget }))
  })
})

describe('listResearchVersionRuns', () => {
  it('reads the version run page from the documented path', async () => {
    const { calls, client } = scenario(() => Response.json({ items: [], next_cursor: null }))
    const page = await listResearchVersionRuns(client, VERSION_ID, 20)
    expect(page.items).toEqual([])
    expect(calls[0]?.url).toBe(`/api/v2/research-versions/${VERSION_ID}/runs?limit=20`)
  })
})

describe('fetchResearchVersionEvents', () => {
  it('reads the bounded research event stream and forwards Last-Event-ID when present', async () => {
    const body =
      'retry: 2000\n\n' +
      'id: RESEARCH:22222222-2222-2222-2222-222222222222:1\n' +
      'event: ResearchVersionStateChanged\n' +
      'data: {"event_id":"event-1","event_type":"ResearchVersionStateChanged","sequence":1,"occurred_at":"2026-10-21T00:00:00Z","run_id":null,"stream_scope":"RESEARCH","payload":{"status":"VALIDATING","revision":1}}\n\n'
    const { calls, client } = scenario(() => new Response(body))
    const events = await fetchResearchVersionEvents(client, VERSION_ID, 'RESEARCH:22222222-2222-2222-2222-222222222222:0')
    expect(events).toHaveLength(1)
    expect(events[0]?.event_type).toBe('ResearchVersionStateChanged')
    expect(events[0]?.sequence).toBe(1)
    expect(calls[0]?.url).toBe(`/api/v2/research-versions/${VERSION_ID}/events`)
    expect(calls[0]?.headers.get('Last-Event-ID')).toBe(
      'RESEARCH:22222222-2222-2222-2222-222222222222:0',
    )
  })
})

describe('getFrozenSubmission', () => {
  it('reads the frozen submission resource from the documented path', async () => {
    const { calls, client } = scenario(() =>
      Response.json({
        kind: 'FrozenSubmission',
        id: SUBMISSION_ID,
        tenant_id: '55555555-5555-5555-5555-555555555555',
        schema_version: '2.0',
        created_at: '2026-10-21T00:00:00Z',
        research_version_id: VERSION_ID,
        sealed_test_id: '88888888-8888-8888-8888-888888888888',
        frozen_candidate_ids: ['99999999-9999-9999-9999-999999999999'],
        metric_version: '2.0',
        snapshot_hash: 'a'.repeat(64),
        status: 'FROZEN',
        evaluation_policy_hash: 'b'.repeat(64),
        verification_plan_artifact_id: PREVIEW_ID,
        verification_plan_hash: 'c'.repeat(64),
      }),
    )
    const submission = await getFrozenSubmission(client, SUBMISSION_ID)
    expect(submission.id).toBe(SUBMISSION_ID)
    expect(calls[0]?.url).toBe(`/api/v2/frozen-submissions/${SUBMISSION_ID}`)
  })
})

describe('getArtifactContent', () => {
  it('parses JSON artifact content from the same path the download link uses', async () => {
    const { calls, client } = scenario(() =>
      Response.json({ source_metadata: { row_count: 1, columns: [{ name: 'a', physical_type: 'int' }] } }),
    )
    const content = await getArtifactContent<{ source_metadata: { row_count: number } }>(client, PREVIEW_ID)
    expect(content.source_metadata.row_count).toBe(1)
    expect(calls[0]?.url).toBe(`/api/v2/artifacts/${PREVIEW_ID}/content`)
    expect(calls[0]?.method).toBe('GET')
  })
})

describe('SEARCH dispatch', () => {
  it('sends the current revision, fixed type and seed with an idempotency key', async () => {
    const { createSearchRun } = await import('../src/api/research')
    const { calls, client } = scenario(() => new Response(JSON.stringify({ id: 'run', type: 'SEARCH', status: 'QUEUED' }), { status: 202, headers: { 'Content-Type': 'application/json' } }))
    await createSearchRun(client, VERSION_ID, 7, 42)
    const call = calls[0]
    expect(call?.url).toBe(`/api/v2/research-versions/${VERSION_ID}/runs`)
    expect(call?.headers.get('If-Control-Revision')).toBe('7')
    expect(call?.headers.get('Idempotency-Key')).toBeTruthy()
    expect(JSON.parse(String(call?.body))).toEqual({ type: 'SEARCH', seed: 42 })
  })
})
