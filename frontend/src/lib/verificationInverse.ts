/**
 * 逆向推導（SSOT 24）的閱讀模型：只依契約已揭露的擬合參數推導「參數恢復」與多解跡象。
 *
 * 後端沒有可識別性檢查與逆問題求解端點，這些欄位一律標示「未取得」。
 * 這裡不以推測補出解集合，只把同一候選在不同擬合中出現的不同參數值標成潛在多解。
 */
import type { EquationVersion, FitRun, ValidationStatus } from '../api/candidates'
import { parameterReadings } from './candidateDetail'
import type { DiscoverySearchRun } from './discoveries'
import { formulaComplexity, renderDomain, renderFormula } from './formula'
import { VERIFICATION_UNKNOWN } from './verificationCenter'

export const IDENTIFIABILITY_UNKNOWN = `可識別性檢查尚無後端端點（${VERIFICATION_UNKNOWN}）`
export const INVERSE_SOLVER_UNKNOWN = `逆問題求解尚無後端端點（${VERIFICATION_UNKNOWN}）`
export const INVERSE_OBSERVATION_UNKNOWN = `指定觀測量與未知參數尚無後端端點（${VERIFICATION_UNKNOWN}）`

export interface InverseParameterObservation {
  name: string
  unit: string
  lower: string
  upper: string
  /** 依擬合順序觀測到的取值；沒有任何擬合揭露時為空陣列。 */
  observations: string[]
  /** 相異取值個數；大於 1 代表同一參數在不同擬合給出不同值。 */
  distinct: number
}

export interface InverseSolutionRow {
  candidateId: string
  rank: number | null
  source: string
  validationStatus: ValidationStatus
  formula: string | null
  domain: string | null
  complexity: number | null
  parameters: InverseParameterObservation[]
  fitCount: number
  /** 相異取值大於 1 的參數名稱；沒有則代表目前讀到的擬合彼此一致。 */
  multiValuedParameters: string[]
}

export interface InverseDerivation {
  runId: string
  researchName: string
  versionId: string | null
  solutions: InverseSolutionRow[]
}

/** 尚未指定候選時的空推導；避免畫面在缺資料時捏造內容。 */
export function emptyInverseDerivation(entry: DiscoverySearchRun | null): InverseDerivation {
  return {
    runId: entry?.run.id ?? '',
    researchName: entry?.research?.name ?? '未命名研究',
    versionId: entry?.version?.id ?? null,
    solutions: [],
  }
}

function observationsFor(name: string, fits: FitRun[]): string[] {
  return fits.map((fit) => fit.parameters[name]).filter((value): value is string => value !== undefined)
}

/**
 * 逐候選整理參數恢復結果；公式或擬合未取得時對應欄位為 null／空陣列，由畫面顯示「未取得」。
 */
export function buildInverseDerivation(
  entry: DiscoverySearchRun | null,
  equations: Record<string, EquationVersion>,
  fits: Record<string, FitRun>,
): InverseDerivation {
  if (entry === null) return emptyInverseDerivation(null)

  const solutions = entry.candidates.map((candidate) => {
    const equation = equations[candidate.equation_version_id] ?? null
    const candidateFits = candidate.fit_run_ids.map((id) => fits[id]).filter((fit): fit is FitRun => fit !== undefined)
    const readings = parameterReadings(equation, candidateFits) ?? []
    const parameters: InverseParameterObservation[] = readings.map((reading) => {
      const observations = observationsFor(reading.name, candidateFits)
      return {
        name: reading.name,
        unit: reading.unit,
        lower: reading.lower,
        upper: reading.upper,
        observations,
        distinct: new Set(observations).size,
      }
    })
    return {
      candidateId: candidate.id,
      rank: candidate.development_rank,
      source: candidate.source,
      validationStatus: candidate.validation_status,
      formula: equation === null ? null : renderFormula(equation.dsl.root),
      domain: equation === null ? null : renderDomain(equation.dsl.domain),
      complexity: equation === null ? null : formulaComplexity(equation.dsl.root),
      parameters,
      fitCount: candidateFits.length,
      multiValuedParameters: parameters.filter((parameter) => parameter.distinct > 1).map((parameter) => parameter.name),
    }
  })

  return {
    runId: entry.run.id,
    researchName: entry.research?.name ?? '未命名研究',
    versionId: entry.version?.id ?? null,
    solutions,
  }
}
