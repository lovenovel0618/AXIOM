/** 產物（Artifact）metadata 與內容取得；二進位附件走網址下載，結構預覽等 JSON 才在此解析。 */
import type { ApiClient } from './client'

export type ArtifactStatus = 'AVAILABLE' | 'QUARANTINED' | 'DELETED'
export type ArtifactAccessClass = 'PROJECT' | 'SEALED_DETAIL' | 'RELEASED_AGGREGATE'

export interface Artifact {
  kind: 'Artifact'
  id: string
  tenant_id: string
  created_at: string
  artifact_uri: string
  sha256: string
  status: ArtifactStatus
  owner_id: string
  size_bytes: number
  media_type: string
  access_class: ArtifactAccessClass
}

export async function getArtifact(client: ApiClient, id: string): Promise<Artifact> {
  return client.request<Artifact>('GET', `/api/v2/artifacts/${id}`)
}

/** 下載走瀏覽器原生導覽，沿用同源 cookie 與後端的 attachment 標頭。 */
export function artifactContentPath(id: string): string {
  return `/api/v2/artifacts/${id}/content`
}

/** JSON 內容產物（如結構預覽）；後端回應前會重驗 sha256 與大小。 */
export async function getArtifactContent<T>(client: ApiClient, id: string): Promise<T> {
  return client.request<T>('GET', `/api/v2/artifacts/${id}/content`)
}
