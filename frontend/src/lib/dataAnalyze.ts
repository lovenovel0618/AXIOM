/**
 * 由資料集版本快速建立研究並啟動分析：資料集清單與資料集工作區共用同一條流程，
 * 避免兩處各寫一份 IO。草稿規則沿用 quickResearch，不在此層自創欄位或補值。
 */
import type { ApiClient } from '../api/client'
import type { Dataset, DatasetVersion } from '../api/datasets'
import { createResearch, createResearchVersion, getResearchVersion, validateDraft } from '../api/research'
import { buildQuickResearchDraft, quickResearchName } from './quickResearch'
import type { SourceMetadata } from './semantics'

export interface QuickAnalysis {
  researchId: string
  researchVersionId: string
  runStatus: string
}

export type QuickAnalysisOutcome =
  | { ok: true; analysis: QuickAnalysis }
  | { ok: false; reason: string }

/** 前置條件不成立時回報原因而非丟錯；只有後端錯誤才往上拋給呼叫端描述。 */
export async function runQuickAnalysis(
  client: ApiClient,
  dataset: Dataset,
  version: DatasetVersion,
  metadata: SourceMetadata | null,
): Promise<QuickAnalysisOutcome> {
  if (version.status !== 'AVAILABLE') {
    return { ok: false, reason: '此資料集版本狀態為不可用，無法建立分析。' }
  }
  if (version.structure_preview_artifact_id === null) {
    return { ok: false, reason: '此資料集版本沒有結構預覽，無法自動建立分析草稿。' }
  }
  if (metadata === null) {
    return { ok: false, reason: '結構預覽產物格式不符，無法自動建立分析草稿。' }
  }
  const draft = buildQuickResearchDraft(version, metadata)
  if (draft.request === null) {
    return { ok: false, reason: `無法自動建立分析草稿：${draft.problems.join('；')}` }
  }

  const research = await createResearch(client, quickResearchName(dataset.name))
  const createdVersion = await createResearchVersion(client, research.id, draft.request)
  const run = await validateDraft(client, createdVersion.id, createdVersion.revision)
  const freshVersion = await getResearchVersion(client, createdVersion.id)
  return {
    ok: true,
    analysis: { researchId: research.id, researchVersionId: freshVersion.id, runStatus: run.status },
  }
}
