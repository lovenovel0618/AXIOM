/**
 * 形式化證明（SSOT 25）的閱讀模型：只依證據包引用的證明產物與 validation run 的證明等級。
 *
 * 後端沒有命題、前提與 Lean 目標的端點，這些欄位一律標示「未取得」。
 * 這裡不推測證明的語意內容，只投影產物的 metadata 與後端已回報的 P0／P1／P2 等級。
 */
import type { Artifact, ArtifactAccessClass, ArtifactStatus } from '../api/artifacts'
import type { EmpiricalLevel, ProofLevel } from './evaluation'
import type { VerificationCenter } from './verificationCenter'
import { VERIFICATION_UNKNOWN } from './verificationCenter'

/** 後端未提供命題、前提與 Lean 目標端點；畫面必須固定顯示此狀態。 */
export const PROOF_STATEMENT_UNKNOWN = `命題與 Lean 目標尚無後端端點（${VERIFICATION_UNKNOWN}）`
export const PROOF_PREMISE_UNKNOWN = `證明前提尚無後端端點（${VERIFICATION_UNKNOWN}）`

export const ARTIFACT_STATUS_LABELS: Record<ArtifactStatus, string> = {
  AVAILABLE: '可用',
  QUARANTINED: '已隔離',
  DELETED: '已刪除',
}

export const ARTIFACT_ACCESS_LABELS: Record<ArtifactAccessClass, string> = {
  PROJECT: '專案可見',
  SEALED_DETAIL: '封存明細',
}

export interface ProofArtifactRow {
  artifactId: string
  versionId: string
  researchName: string
  /** metadata 抓不到時為 null，由畫面顯示「未取得」。 */
  artifact: Artifact | null
  /** 同一版本所有 validation run 已回報的證明等級集合。 */
  proofLevels: ProofLevel[]
  empiricalLevels: EmpiricalLevel[]
}

export interface ProofSummary {
  total: number
  available: number
  quarantined: number
  /** 有引用但 metadata 未取得的產物數。 */
  unreadable: number
}

/** 證明產物只來自證據包的 proof_artifact_ids；沒有引用就不憑空生列表。 */
export function buildProofRows(center: VerificationCenter): ProofArtifactRow[] {
  const rows: ProofArtifactRow[] = []

  for (const item of center.evidenceItems) {
    const versionId = item.version.id
    const validations = center.submissionRows
      .filter((row) => row.version.id === versionId)
      .flatMap((row) => row.validations)
    const proofLevels = [...new Set(validations.map((validation) => validation.proofLevel))].sort()
    const empiricalLevels = [...new Set(validations.map((validation) => validation.empiricalLevel))].sort()

    for (const bundle of item.bundles) {
      for (const artifactId of bundle.proofArtifactIds) {
        rows.push({
          artifactId,
          versionId,
          researchName: item.research?.name ?? '未命名研究',
          artifact: center.proofArtifacts[artifactId] ?? null,
          proofLevels,
          empiricalLevels,
        })
      }
    }
  }

  return rows.sort((left, right) => (left.artifactId < right.artifactId ? -1 : left.artifactId > right.artifactId ? 1 : 0))
}

export function summarizeProof(rows: ProofArtifactRow[]): ProofSummary {
  return {
    total: rows.length,
    available: rows.filter((row) => row.artifact?.status === 'AVAILABLE').length,
    quarantined: rows.filter((row) => row.artifact?.status === 'QUARANTINED').length,
    unreadable: rows.filter((row) => row.artifact === null).length,
  }
}

/** 證明等級的固定顯示順序；後端目前只回 P0／P1／P2。 */
export const PROOF_LEVEL_ORDER: readonly ProofLevel[] = ['P0', 'P1', 'P2']

export function describeProofLevels(levels: ProofLevel[]): string {
  if (levels.length === 0) return VERIFICATION_UNKNOWN
  return PROOF_LEVEL_ORDER.filter((level) => levels.includes(level)).join('、')
}

export function describeEmpiricalLevels(levels: EmpiricalLevel[]): string {
  return levels.length === 0 ? VERIFICATION_UNKNOWN : levels.join('、')
}
