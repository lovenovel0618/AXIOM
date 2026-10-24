import { describe, expect, it } from 'vitest'
import { createApiClient, type Fetcher } from '../src/api/client'
import { listDatasetRuns } from '../src/api/datasets'

const DATASET_ID = '11111111-1111-1111-1111-111111111111'
const CSRF = 'csrf-1'

interface Call {
  url: string
  method: string
}

function scenario(responder: (call: Call) => Response): { calls: Call[]; client: ReturnType<typeof createApiClient> } {
  const calls: Call[] = []
  const fetcher: Fetcher = async (url, init) => {
    const call: Call = { url, method: init?.method ?? 'GET' }
    calls.push(call)
    return responder(call)
  }
  return { calls, client: createApiClient(fetcher, () => CSRF) }
}

describe('listDatasetRuns', () => {
  it('reads the documented dataset runs path with a limit and no cursor by default', async () => {
    const { calls, client } = scenario(() =>
      Response.json({
        items: [
          {
            kind: 'Run',
            id: 'run-1',
            type: 'INGEST',
            status: 'QUEUED',
            dataset_id: DATASET_ID,
            created_at: '2026-10-21T00:00:00Z',
          },
        ],
        next_cursor: null,
      }),
    )
    const page = await listDatasetRuns(client, DATASET_ID)
    expect(page.items).toHaveLength(1)
    expect(page.items[0]?.type).toBe('INGEST')
    expect(page.next_cursor).toBeNull()
    expect(calls).toEqual([{ url: `/api/v2/datasets/${DATASET_ID}/runs?limit=50`, method: 'GET' }])
  })

  it('passes the cursor back so the import page can recover older runs', async () => {
    const { calls, client } = scenario(() => Response.json({ items: [], next_cursor: 'next' }))
    const page = await listDatasetRuns(client, DATASET_ID, 'signed-cursor', 10)
    expect(page.next_cursor).toBe('next')
    expect(calls[0]?.url).toBe(`/api/v2/datasets/${DATASET_ID}/runs?limit=10&cursor=signed-cursor`)
  })
})
