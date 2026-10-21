import { describe, expect, it } from 'vitest'
import { ApiError, createApiClient, type Fetcher } from '../src/api/client'
import { describeError } from '../src/lib/messages'
import { MAX_UPLOAD_BYTES, deriveFormat, uploadDatasetFile, type UploadStage } from '../src/lib/upload'

const DATASET_ID = '11111111-1111-1111-1111-111111111111'
const UPLOAD_ID = '22222222-2222-2222-2222-222222222222'
const CSRF = 'csrf-1'

interface Call {
  url: string
  method: string
  headers: Headers
  body: unknown
}

function scenario(complete: Response): { calls: Call[]; client: ReturnType<typeof createApiClient> } {
  const calls: Call[] = []
  const fetcher: Fetcher = async (url, init) => {
    calls.push({ url, method: init?.method ?? 'GET', headers: new Headers(init?.headers), body: init?.body })
    if (url === `/api/v2/datasets/${DATASET_ID}/uploads`) {
      return Response.json(
        {
          id: UPLOAD_ID,
          dataset_id: DATASET_ID,
          put_url: `http://127.0.0.1:18000/storage/uploads/${UPLOAD_ID}`,
          expires_at: '2026-10-21T00:00:00Z',
          required_headers: { 'X-Upload-Token': 'signed-token', 'Content-Type': 'application/octet-stream' },
        },
        { status: 201 },
      )
    }
    if (url === `/storage/uploads/${UPLOAD_ID}`) return new Response(null, { status: 204 })
    if (url === `/api/v2/uploads/${UPLOAD_ID}/complete`) return complete.clone()
    if (url.startsWith(`/api/v2/datasets/${DATASET_ID}/versions`)) {
      return Response.json({
        items: [
          {
            kind: 'DatasetVersion',
            id: 'version-1',
            dataset_id: DATASET_ID,
            created_at: '2026-10-21T00:00:00Z',
            format: 'CSV',
            row_count: 2,
            sha256: 'a'.repeat(64),
            status: 'AVAILABLE',
            artifact_id: 'artifact-1',
            structure_preview_artifact_id: null,
          },
        ],
        next_cursor: null,
      })
    }
    throw new Error(`unexpected request ${url}`)
  }
  return { calls, client: createApiClient(fetcher, () => CSRF) }
}

function csvFile(): File {
  return new File([new TextEncoder().encode('a,b\n1,2\n')], 'sample.csv', { type: 'text/csv' })
}

const okComplete = (): Response =>
  Response.json(
    { kind: 'Run', id: 'run-1', type: 'INGEST', status: 'QUEUED', dataset_id: DATASET_ID, created_at: '2026-10-21T00:00:00Z' },
    { status: 202 },
  )

describe('deriveFormat', () => {
  const supported: [string, string][] = [
    ['data.csv', 'CSV'],
    ['DATA.CSV', 'CSV'],
    ['series.json', 'JSON'],
    ['table.parquet', 'PARQUET'],
  ]
  it.each(supported)('maps %s to %s', (filename, expected) => {
    expect(deriveFormat(filename)).toBe(expected)
  })

  const rejected: string[] = ['notes.txt', 'archive.tar.gz', 'noextension', 'trailing.']
  it.each(rejected)('rejects %s', (filename) => {
    expect(deriveFormat(filename)).toBeNull()
  })
})

describe('uploadDatasetFile', () => {
  it('walks hashing → session → transfer → complete and returns refreshed versions', async () => {
    const { calls, client } = scenario(okComplete())
    const stages: UploadStage[] = []
    const outcome = await uploadDatasetFile(client, DATASET_ID, csvFile(), (stage) => stages.push(stage))

    expect(stages).toEqual(['hashing', 'session', 'transfer', 'complete'])
    expect(outcome.checksum).toMatch(/^[0-9a-f]{64}$/)
    expect(outcome.run.status).toBe('QUEUED')
    expect(outcome.versions).toHaveLength(1)

    const put = calls.find((call) => call.method === 'PUT')
    expect(put?.url).toBe(`/storage/uploads/${UPLOAD_ID}`)
    expect(put?.headers.get('X-Upload-Token')).toBe('signed-token')
    expect(put?.headers.get('Content-Type')).toBe('application/octet-stream')
    expect(put?.headers.get('X-CSRFToken')).toBe(CSRF)

    const created = calls.find((call) => call.url === `/api/v2/datasets/${DATASET_ID}/uploads`)
    expect(JSON.parse(String(created?.body))).toMatchObject({ filename: 'sample.csv', format: 'CSV', size_bytes: 8 })
  })

  it('refuses an unsupported extension before any network call', async () => {
    const { calls, client } = scenario(okComplete())
    await expect(uploadDatasetFile(client, DATASET_ID, new File(['x'], 'notes.txt'))).rejects.toBeInstanceOf(ApiError)
    expect(calls).toHaveLength(0)
  })

  it('refuses a file beyond the documented size limit', async () => {
    const { calls, client } = scenario(okComplete())
    const oversized = {
      name: 'big.csv',
      size: MAX_UPLOAD_BYTES + 1,
      arrayBuffer: async (): Promise<ArrayBuffer> => new ArrayBuffer(0),
    } as unknown as Blob & { name?: string }
    await expect(uploadDatasetFile(client, DATASET_ID, oversized)).rejects.toMatchObject({ code: 'UPLOAD_TOO_LARGE' })
    expect(calls).toHaveLength(0)
  })

  it('surfaces a disabled ingest service as a readable message', async () => {
    const disabled = Response.json({ code: 'DEPENDENCY_UNAVAILABLE', retryable: true }, { status: 503 })
    const { client } = scenario(disabled)
    const error: unknown = await uploadDatasetFile(client, DATASET_ID, csvFile()).catch((cause: unknown) => cause)
    expect(error).toMatchObject({ code: 'DEPENDENCY_UNAVAILABLE' })
    expect(describeError(error)).toContain('未啟用')
  })
})
