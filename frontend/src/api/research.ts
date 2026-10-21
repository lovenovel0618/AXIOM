/** 研究容器、固定草稿與 PROFILE 觸發；冪等鍵與控制 revision 在此集中處理。 */
import { newKey, type ApiClient } from './client'
import type { BudgetUsage, Run } from './runs'

export interface Research {
  kind: 'Research'
  id: string
  tenant_id: string
  schema_version: string
  created_at: string
  name: string
  owner_id: string
}

export interface ResearchPage {
  items: Research[]
  next_cursor: string | null
}

export type ResearchPurpose = 'DESCRIPTION' | 'PREDICTION' | 'MECHANISM'
export type ResearchVersionStatus =
  | 'DRAFT'
  | 'VALIDATING'
  | 'READY'
  | 'QUEUED'
  | 'RUNNING'
  | 'REVIEW'
  | 'PUBLISHED'
  | 'FAILED'
  | 'CANCELLED'
export type SplitKind = 'IID_ROWS' | 'GROUPED_ROWS' | 'TIME_ORDERED' | 'EXPLICIT'
export type ComparisonMethod = 'IID_PAIRED_BOOTSTRAP' | 'BLOCK_BOOTSTRAP' | 'NONE'
export type ErrorModel = 'EXACT' | 'ABSOLUTE_BOUND' | 'UNSPECIFIED'
export type Baseline = 'ZERO' | 'FIT_MEAN'

export interface UnitConversion {
  source_unit: string
  scale: string
  offset: string
}

export interface SemanticQuantity {
  name: string
  unit: number[]
  source_column: string
  conversion: UnitConversion
}

export interface SemanticProfile {
  inputs: SemanticQuantity[]
  target: SemanticQuantity
  units_confirmed: boolean
  time_ordered: boolean
  measurement_resolution: string | null
  resolution_reason: string
  group_column: string | null
}

export interface BudgetLimit {
  cpu_seconds: number
  gpu_seconds: number
  wall_seconds: number
  tokens: number
  candidate_limit: number
  memory_bytes: number
}

export interface Rational {
  numerator: string
  denominator: string
}

export interface DomainInterval {
  name: string
  lower: Rational
  upper: Rational
  lower_closed: boolean
  upper_closed: boolean
}

/** 建立版本時送入的切分宣告；後端會重算並比對，不接受任意列集合。 */
export interface ObservationSplitRequest {
  kind: SplitKind
  dataset_version_id: string
  fit: number[]
  development: number[]
  final_test: number[]
  gap_rows: number
  lookback_rows: number
  horizon_rows: number
  seed: number
  time_column: string | null
  group_column: string | null
  group_assignment_digest: string | null
  splitter_version: string
  policy_version: string
  sealed_final_test: boolean
}

/** 讀取回來的切分另含後端固定的身分欄位。 */
export interface ObservationSplit extends ObservationSplitRequest {
  id: string
  row_ids_hash: string
  sealed_test_id: string | null
}

export interface EvaluationPolicy {
  policy_version: string
  metric_version: string
  error_model: ErrorModel
  absolute_error_bound: string | null
  comparison_method: ComparisonMethod
  bootstrap_replicates: number
  bootstrap_seed: number
  block_method: 'MOVING_BLOCK' | null
  block_length: number | null
  practical_scale_override: string | null
  practical_margin_ratio: string
  baseline: Baseline
  practical_scale_reason: string | null
}

export interface CreateResearchVersionRequest {
  dataset_version_id: string
  semantic_profile: SemanticProfile
  budget: BudgetLimit
  purpose: ResearchPurpose
  observation_split: ObservationSplitRequest
  domain: DomainInterval[]
  evaluation_policy: EvaluationPolicy
}

export interface ResearchVersion {
  kind: 'ResearchVersion'
  id: string
  tenant_id: string
  schema_version: string
  created_at: string
  research_id: string
  dataset_version_id: string
  semantic_profile: SemanticProfile
  budget: BudgetLimit
  purpose: ResearchPurpose
  status: ResearchVersionStatus
  revision: number
  observation_split: ObservationSplit
  current_event_cursor: string
  frozen_submission_ids: string[]
  review_ids: string[]
  published_artifact_ids: string[]
  evidence_bundle_ids: string[]
  quality_report_id: string | null
  refit_policy_artifact_id: string | null
  domain: DomainInterval[]
  evaluation_policy: EvaluationPolicy
  evaluation_policy_hash: string
  research_budget_usage: BudgetUsage
  released_summary_ids: string[]
  structure_assessment_artifact_id: string | null
}

export interface ResearchVersionPage {
  items: ResearchVersion[]
  next_cursor: string | null
}

export interface RunPage {
  items: Run[]
  next_cursor: string | null
}

export async function listResearches(client: ApiClient, limit = 50): Promise<ResearchPage> {
  return client.request<ResearchPage>('GET', `/api/v2/researches?limit=${String(limit)}`)
}

export async function createResearch(client: ApiClient, name: string): Promise<Research> {
  return client.request<Research>('POST', '/api/v2/researches', {
    json: { name },
    headers: { 'Idempotency-Key': newKey() },
  })
}

export async function listResearchVersions(
  client: ApiClient,
  researchId: string,
  limit = 50,
): Promise<ResearchVersionPage> {
  return client.request<ResearchVersionPage>(
    'GET',
    `/api/v2/researches/${researchId}/versions?limit=${String(limit)}`,
  )
}

export async function createResearchVersion(
  client: ApiClient,
  researchId: string,
  request: CreateResearchVersionRequest,
): Promise<ResearchVersion> {
  return client.request<ResearchVersion>('POST', `/api/v2/researches/${researchId}/versions`, {
    json: request,
    headers: { 'Idempotency-Key': newKey() },
  })
}

export async function getResearchVersion(client: ApiClient, id: string): Promise<ResearchVersion> {
  return client.request<ResearchVersion>('GET', `/api/v2/research-versions/${id}`)
}

/** 觸發 PROFILE 需要目前控制 revision；未啟用時後端回 503，缺 revision 回 428。 */
export async function validateDraft(
  client: ApiClient,
  versionId: string,
  revision: number,
  runBudget?: BudgetLimit,
): Promise<Run> {
  return client.request<Run>('POST', `/api/v2/research-versions/${versionId}/validate`, {
    json: runBudget === undefined ? {} : { run_budget: runBudget },
    headers: { 'Idempotency-Key': newKey(), 'If-Control-Revision': String(revision) },
  })
}

export async function listResearchVersionRuns(
  client: ApiClient,
  versionId: string,
  limit = 50,
): Promise<RunPage> {
  return client.request<RunPage>(
    'GET',
    `/api/v2/research-versions/${versionId}/runs?limit=${String(limit)}`,
  )
}
