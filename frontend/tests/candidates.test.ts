import { describe, expect, it } from 'vitest'
import { createApiClient, type Fetcher } from '../src/api/client'
import {
  getEquationVersion,
  getFitRun,
  listRunCandidates,
  MAX_COMPARISON,
  type Candidate,
  type EquationVersion,
  type FitRun,
} from '../src/api/candidates'

const RUN_ID = '11111111-1111-1111-1111-111111111111'
const CANDIDATE_ID = '22222222-2222-2222-2222-222222222222'
const EQUATION_ID = '33333333-3333-3333-3333-333333333333'
const FIT_ID = '44444444-4444-4444-4444-444444444444'
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

function candidateDocument(): Candidate {
  return {
    kind: 'Candidate',
    id: CANDIDATE_ID,
    tenant_id: '55555555-5555-5555-5555-555555555555',
    schema_version: '2.0',
    created_at: '2026-10-24T00:00:00Z',
    search_run_id: RUN_ID,
    equation_version_id: EQUATION_ID,
    source: 'SYMBOLIC_REGRESSION',
    development_rank: 1,
    validation_status: 'NOT_RUN',
    fit_run_ids: [FIT_ID],
    validation_run_ids: [],
  }
}

function equationDocument(): EquationVersion {
  return {
    kind: 'EquationVersion',
    id: EQUATION_ID,
    tenant_id: '55555555-5555-5555-5555-555555555555',
    schema_version: '2.0',
    created_at: '2026-10-24T00:00:00Z',
    identity_hash: 'a'.repeat(64),
    dsl: {
      dsl_version: '1.0',
      variables: [{ name: 'x', unit: [0, 0, 0, 0, 0, 0, 0] }],
      parameters: [{ name: 'c0', unit: [0, 0, 0, 0, 0, 0, 0], lower: '0', upper: '10' }],
      domain: [{ name: 'x', lower: { numerator: '0', denominator: '1' }, upper: { numerator: '1', denominator: '1' }, lower_closed: true, upper_closed: false }],
      root: { op: 'add', args: [{ op: 'param', name: 'c0' }, { op: 'var', name: 'x' }] },
    },
  }
}

function fitDocument(): FitRun {
  return {
    kind: 'FitRun',
    id: FIT_ID,
    tenant_id: '55555555-5555-5555-5555-555555555555',
    schema_version: '2.0',
    created_at: '2026-10-24T00:00:00Z',
    run_id: '66666666-6666-6666-6666-666666666666',
    equation_version_id: EQUATION_ID,
    dataset_version_id: '77777777-7777-7777-7777-777777777777',
    parameters: { c0: '2.5' },
    optimizer: 'SYMBOLIC_REGRESSION',
    observation_split_id: '88888888-8888-8888-8888-888888888888',
    split_role: 'FIT',
    precision_bits: 53,
    fit_row_ids: [0, 1, 2],
    fit_rows_hash: 'b'.repeat(64),
    representation_artifact_id: '99999999-9999-9999-9999-999999999999',
  }
}

describe('listRunCandidates', () => {
  it('reads the documented candidates path without query parameters by default', async () => {
    const { calls, client } = scenario(() => Response.json({ items: [candidateDocument()], next_cursor: null }))
    const page = await listRunCandidates(client, RUN_ID)
    expect(page.items).toHaveLength(1)
    expect(page.next_cursor).toBeNull()
    expect(calls[0]?.url).toBe(`/api/v2/runs/${RUN_ID}/candidates`)
    expect(calls[0]?.method).toBe('GET')
  })

  it('passes cursor and limit through when provided', async () => {
    const { calls, client } = scenario(() => Response.json({ items: [], next_cursor: null }))
    await listRunCandidates(client, RUN_ID, { cursor: 'signed-cursor', limit: MAX_COMPARISON })
    expect(calls[0]?.url).toBe(`/api/v2/runs/${RUN_ID}/candidates?cursor=signed-cursor&limit=4`)
  })
})

describe('equation and fit reads', () => {
  it('reads an equation version from its documented path', async () => {
    const { calls, client } = scenario(() => Response.json(equationDocument()))
    const equation = await getEquationVersion(client, EQUATION_ID)
    expect(equation.identity_hash).toHaveLength(64)
    expect(calls[0]?.url).toBe(`/api/v2/equation-versions/${EQUATION_ID}`)
  })

  it('reads a fit run from its documented path', async () => {
    const { calls, client } = scenario(() => Response.json(fitDocument()))
    const fit = await getFitRun(client, FIT_ID)
    expect(fit.precision_bits).toBe(53)
    expect(calls[0]?.url).toBe(`/api/v2/fit-runs/${FIT_ID}`)
  })
})
