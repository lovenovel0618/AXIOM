/** 資料集與上傳 API：呼叫端只傳 DTO，冪等鍵與簽章標頭在此集中處理。 */
import { newKey, toRelativePath, type ApiClient } from './client'

export type UploadFormat = 'CSV' | 'JSON' | 'PARQUET'
export type DatasetVersionStatus = 'AVAILABLE' | 'UNAVAILABLE'

export interface Dataset {
  kind: 'Dataset'
  id: string
  tenant_id: string
  schema_version: string
  created_at: string
  name: string
  owner_id: string
}

export interface DatasetPage {
  items: Dataset[]
  next_cursor: string | null
}

export interface UploadSession {
  id: string
  dataset_id: string
  put_url: string
  expires_at: string
  required_headers: Record<string, string>
}

export interface RunRecord {
  kind: 'Run'
  id: string
  type: string
  status: string
  dataset_id: string
  created_at: string
}

export interface DatasetVersion {
  kind: 'DatasetVersion'
  id: string
  dataset_id: string
  created_at: string
  format: UploadFormat
  row_count: number
  sha256: string
  status: DatasetVersionStatus
  artifact_id: string
  structure_preview_artifact_id: string | null
}

export interface VersionPage {
  items: DatasetVersion[]
  next_cursor: string | null
}

export async function listDatasets(client: ApiClient, cursor = '', limit = 50): Promise<DatasetPage> {
  const params = new URLSearchParams({ limit: String(limit) })
  if (cursor !== '') params.set('cursor', cursor)
  return client.request<DatasetPage>('GET', `/api/v2/datasets?${params.toString()}`)
}

export async function createDataset(client: ApiClient, name: string): Promise<Dataset> {
  return client.request<Dataset>('POST', '/api/v2/datasets', {
    json: { name },
    headers: { 'Idempotency-Key': newKey() },
  })
}

export interface UploadIntent {
  filename: string
  format: UploadFormat
  size_bytes: number
  sha256: string
}

export async function createUpload(client: ApiClient, datasetId: string, intent: UploadIntent): Promise<UploadSession> {
  return client.request<UploadSession>('POST', `/api/v2/datasets/${datasetId}/uploads`, {
    json: { ...intent },
    headers: { 'Idempotency-Key': newKey() },
  })
}

export async function putUploadBytes(client: ApiClient, session: UploadSession, body: BodyInit): Promise<void> {
  const headers: Record<string, string> = { 'Content-Type': 'application/octet-stream' }
  const token = session.required_headers['X-Upload-Token']
  if (typeof token === 'string' && token !== '') headers['X-Upload-Token'] = token
  await client.request<unknown>('PUT', toRelativePath(session.put_url), { body, headers })
}

export async function completeUpload(client: ApiClient, uploadId: string, checksum: string): Promise<RunRecord> {
  return client.request<RunRecord>('POST', `/api/v2/uploads/${uploadId}/complete`, {
    json: { checksum },
    headers: { 'Idempotency-Key': newKey() },
  })
}

export async function listVersions(client: ApiClient, datasetId: string, limit = 50): Promise<VersionPage> {
  return client.request<VersionPage>('GET', `/api/v2/datasets/${datasetId}/versions?limit=${String(limit)}`)
}
