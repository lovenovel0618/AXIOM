/**
 * 候選、公式版本與擬合結果的唯讀存取；形狀依契約，授權一律由後端決定。
 * 這裡只做投影，不推測後端未提供的指標（如凍結前的 final_test 分數）。
 */
import type { ApiClient } from './client'

export interface Rational {
  numerator: string
  denominator: string
}

export type Comparator = 'lt' | 'lte' | 'gt' | 'gte'

export interface PiecewiseBranch {
  when: { var: string; comparator: Comparator; value: Rational }
  then: DslNode
}

export type DslNode =
  | { op: 'const'; value: Rational }
  | { op: 'var'; name: string }
  | { op: 'param'; name: string }
  | { op: 'add' | 'mul' | 'sub' | 'div' | 'pow'; args: DslNode[] }
  | { op: 'sin' | 'cos' | 'exp' | 'log' | 'abs'; args: DslNode[] }
  | { op: 'piecewise'; branches: PiecewiseBranch[]; otherwise: DslNode }

export interface DslParameter {
  name: string
  unit: number[]
  lower: string
  upper: string
}

export interface DslDomain {
  name: string
  lower: Rational
  upper: Rational
  lower_closed: boolean
  upper_closed: boolean
}

export interface Dsl {
  dsl_version: string
  variables: { name: string; unit: number[] }[]
  parameters: DslParameter[]
  domain: DslDomain[]
  root: DslNode
}

export type ValidationStatus = 'NOT_RUN' | 'PENDING' | 'FINISHED' | 'INVALID'

/** 工作台同屏最多並排比較的候選數（AX-44）。 */
export const MAX_COMPARISON = 4

export interface Candidate {
  kind: 'Candidate'
  id: string
  tenant_id: string
  schema_version: string
  created_at: string
  search_run_id: string
  equation_version_id: string
  source: string
  development_rank: number | null
  validation_status: ValidationStatus
  fit_run_ids: string[]
  validation_run_ids: string[]
}

export interface CandidatePage {
  items: Candidate[]
  next_cursor: string | null
}

export interface EquationVersion {
  kind: 'EquationVersion'
  id: string
  tenant_id: string
  schema_version: string
  created_at: string
  dsl: Dsl
  identity_hash: string
}

export interface FitRun {
  kind: 'FitRun'
  id: string
  tenant_id: string
  schema_version: string
  created_at: string
  run_id: string
  equation_version_id: string
  dataset_version_id: string
  parameters: Record<string, string>
  optimizer: string
  observation_split_id: string
  split_role: 'FIT' | 'FIT_DEVELOPMENT'
  precision_bits: number
  fit_row_ids: number[]
  fit_rows_hash: string
  representation_artifact_id: string
}

export interface CandidatePageQuery {
  cursor?: string | null
  limit?: number
}

/** 同一 SEARCH run 的候選分頁；未帶 cursor 時由 development_rank 起點開始。 */
export async function listRunCandidates(
  client: ApiClient,
  runId: string,
  query: CandidatePageQuery = {},
): Promise<CandidatePage> {
  const params = new URLSearchParams()
  if (query.cursor !== undefined && query.cursor !== null && query.cursor !== '') {
    params.set('cursor', query.cursor)
  }
  if (query.limit !== undefined) params.set('limit', String(query.limit))
  const suffix = params.size === 0 ? '' : `?${params.toString()}`
  return client.request<CandidatePage>('GET', `/api/v2/runs/${runId}/candidates${suffix}`)
}

export async function getEquationVersion(client: ApiClient, id: string): Promise<EquationVersion> {
  return client.request<EquationVersion>('GET', `/api/v2/equation-versions/${id}`)
}

export async function getFitRun(client: ApiClient, id: string): Promise<FitRun> {
  return client.request<FitRun>('GET', `/api/v2/fit-runs/${id}`)
}
