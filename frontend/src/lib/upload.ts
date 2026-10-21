/** 上傳流程純邏輯：算雜湊、建立上傳、傳輸位元組、完成匯入、回讀版本。 */
import { ApiError, type ApiClient } from '../api/client'
import {
  completeUpload,
  createUpload,
  listVersions,
  putUploadBytes,
  type DatasetVersion,
  type RunRecord,
  type UploadFormat,
} from '../api/datasets'
import { sha256Hex } from './sha256'

export const MAX_UPLOAD_BYTES = 52_428_800

const FORMAT_BY_EXTENSION: Record<string, UploadFormat> = {
  csv: 'CSV',
  json: 'JSON',
  parquet: 'PARQUET',
}

export type UploadStage = 'hashing' | 'session' | 'transfer' | 'complete'

export interface UploadOutcome {
  checksum: string
  run: RunRecord
  versions: DatasetVersion[]
}

export function deriveFormat(filename: string): UploadFormat | null {
  const dot = filename.lastIndexOf('.')
  if (dot < 0 || dot === filename.length - 1) return null
  return FORMAT_BY_EXTENSION[filename.slice(dot + 1).toLowerCase()] ?? null
}

export async function uploadDatasetFile(
  client: ApiClient,
  datasetId: string,
  file: Blob & { name?: string },
  onStage: (stage: UploadStage) => void = () => undefined,
): Promise<UploadOutcome> {
  const filename = file.name ?? 'unnamed'
  const format = deriveFormat(filename)
  if (format === null) throw new ApiError('UNSUPPORTED_MEDIA_TYPE', 415, false)
  if (file.size === 0 || file.size > MAX_UPLOAD_BYTES) throw new ApiError('UPLOAD_TOO_LARGE', 413, false)

  onStage('hashing')
  const bytes = await file.arrayBuffer()
  const checksum = await sha256Hex(bytes)

  onStage('session')
  const session = await createUpload(client, datasetId, { filename, format, size_bytes: file.size, sha256: checksum })

  onStage('transfer')
  await putUploadBytes(client, session, bytes)

  onStage('complete')
  const run = await completeUpload(client, session.id, checksum)

  const page = await listVersions(client, datasetId)
  return { checksum, run, versions: page.items }
}
