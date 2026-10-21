/** 產物（Artifact）metadata 與內容路徑；內容為同源附件下載，不經 JS 解析。 */
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
