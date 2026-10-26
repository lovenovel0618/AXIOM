/**
 * 候選公式的閱讀模型：只依契約已揭露的候選、公式版本、擬合與驗證結果推導。
 * 任何缺漏（公式未取得、驗證未取得）一律回報未取得，不以推測補值。
 */
import type { Candidate, EquationVersion, FitRun, ValidationStatus } from '../api/candidates'
import type { ValidationRun } from './evaluation'
import { formulaComplexity, parameterPrecision, renderDomain, renderFormula } from './formula'

/** 同任務候選清單最多並列筆數，避免一次展開無上限的節點。 */
export const PEER_LIMIT = 12

/** 單位以契約的維度向量呈現；全零視為無因次，不臆測實體單位名稱。 */
export function renderUnit(unit: number[]): string {
  if (unit.length === 0 || unit.every((value) => value === 0)) return '無因次'
  return `[${unit.join(', ')}]`
}

export function findCandidate(candidates: Candidate[], id: string): Candidate | null {
  return candidates.find((row) => row.id === id) ?? null
}

export function orderedFits(candidate: Candidate, fits: Record<string, FitRun>): FitRun[] {
  return candidate.fit_run_ids.map((id) => fits[id]).filter((row): row is FitRun => row !== undefined)
}

export function firstFit(candidate: Candidate, fits: Record<string, FitRun>): FitRun | null {
  const id = candidate.fit_run_ids[0]
  if (id === undefined) return null
  return fits[id] ?? null
}

export interface ParameterReading {
  name: string
  unit: string
  lower: string
  upper: string
  /** 取自擬合結果；沒有任何擬合揭露此參數時為未取得。 */
  fittedValue: string | null
}

export function parameterReadings(equation: EquationVersion | null, fits: FitRun[]): ParameterReading[] | null {
  if (equation === null) return null
  return equation.dsl.parameters.map((parameter) => {
    const fitted = fits.map((fit) => fit.parameters[parameter.name]).find((value) => value !== undefined) ?? null
    return {
      name: parameter.name,
      unit: renderUnit(parameter.unit),
      lower: parameter.lower,
      upper: parameter.upper,
      fittedValue: fitted,
    }
  })
}

export interface FitReading {
  id: string
  optimizer: string
  splitRole: FitRun['split_role']
  precisionBits: number
  parameterCount: number
  fitRowCount: number
  datasetVersionId: string
  observationSplitId: string
  representationArtifactId: string
}

export function fitReadings(fits: FitRun[]): FitReading[] {
  return fits.map((fit) => ({
    id: fit.id,
    optimizer: fit.optimizer,
    splitRole: fit.split_role,
    precisionBits: fit.precision_bits,
    parameterCount: Object.keys(fit.parameters).length,
    fitRowCount: fit.fit_row_ids.length,
    datasetVersionId: fit.dataset_version_id,
    observationSplitId: fit.observation_split_id,
    representationArtifactId: fit.representation_artifact_id,
  }))
}

export interface CandidateReading {
  id: string
  rank: number | null
  source: string
  validationStatus: ValidationStatus
  equationVersionId: string
  identityHash: string | null
  formulaText: string | null
  complexity: number | null
  domains: string | null
  variables: { name: string; unit: string }[] | null
  parameters: ParameterReading[] | null
  fits: FitReading[]
  /** 所有擬合中最大的參數有效位數；沒有擬合時為未取得。 */
  fitPrecisionBits: number | null
  searchRunId: string
  validations: ValidationRun[]
  /** 無法解析的驗證識別碼，仍完整列出，不假裝已取得。 */
  missingValidationIds: string[]
}

export function buildCandidateReading(
  candidate: Candidate,
  equation: EquationVersion | null,
  fits: FitRun[],
  validations: Record<string, ValidationRun>,
): CandidateReading {
  const precision = fits.reduce((max, fit) => Math.max(max, parameterPrecision(fit.parameters)), 0)
  return {
    id: candidate.id,
    rank: candidate.development_rank,
    source: candidate.source,
    validationStatus: candidate.validation_status,
    equationVersionId: candidate.equation_version_id,
    identityHash: equation === null ? null : equation.identity_hash,
    formulaText: equation === null ? null : renderFormula(equation.dsl.root),
    complexity: equation === null ? null : formulaComplexity(equation.dsl.root),
    domains: equation === null ? null : renderDomain(equation.dsl.domain),
    variables:
      equation === null
        ? null
        : equation.dsl.variables.map((variable) => ({ name: variable.name, unit: renderUnit(variable.unit) })),
    parameters: parameterReadings(equation, fits),
    fits: fitReadings(fits),
    fitPrecisionBits: fits.length === 0 ? null : precision,
    searchRunId: candidate.search_run_id,
    validations: candidate.validation_run_ids
      .map((id) => validations[id])
      .filter((row): row is ValidationRun => row !== undefined && row !== null),
    missingValidationIds: candidate.validation_run_ids.filter((id) => validations[id] === undefined),
  }
}

export interface CandidatePeerRow {
  id: string
  equationVersionId: string
  rank: number | null
  source: string
  validationStatus: ValidationStatus
  active: boolean
  complexity: number | null
  parameterCount: number | null
  precisionBits: number | null
}

/** 同任務候選並列；development_rank 為 null 的候選排在最後，不用推測名次。 */
export function buildCandidatePeerRows(
  candidates: Candidate[],
  equations: Record<string, EquationVersion>,
  fits: Record<string, FitRun>,
  activeId: string,
): CandidatePeerRow[] {
  const rows = candidates.map((candidate) => {
    const equation = equations[candidate.equation_version_id] ?? null
    const fit = firstFit(candidate, fits)
    return {
      id: candidate.id,
      equationVersionId: candidate.equation_version_id,
      rank: candidate.development_rank,
      source: candidate.source,
      validationStatus: candidate.validation_status,
      active: candidate.id === activeId,
      complexity: equation === null ? null : formulaComplexity(equation.dsl.root),
      parameterCount: equation === null ? null : equation.dsl.parameters.length,
      precisionBits: fit === null ? null : parameterPrecision(fit.parameters),
    }
  })
  const list = rows.slice(0, PEER_LIMIT)
  list.sort((left, right) => {
    if (left.rank === right.rank) return 0
    if (left.rank === null) return 1
    if (right.rank === null) return -1
    return left.rank - right.rank
  })
  return list
}
