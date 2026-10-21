/** 證據包（EvidenceBundle）讀取；後端只回契約白名單欄位，前端不得推測內容。 */
import type { ApiClient } from './client'

/** 形狀驗證與遮罩解讀集中在 lib/evidence，這裡只負責傳輸。 */
export async function getEvidenceBundle(client: ApiClient, id: string): Promise<unknown> {
  return client.request<unknown>('GET', `/api/v2/evidence-bundles/${id}`)
}
