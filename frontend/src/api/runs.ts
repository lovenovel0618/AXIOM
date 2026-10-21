/** 任務（Run）讀取、取消與事件續接；控制 revision 與冪等鍵在此集中處理。 */
import { newKey, type ApiClient } from './client'
import { parseEventBatch, type RunEventEnvelope } from '../lib/events'

export type RunType = 'INGEST' | 'PROFILE' | 'SEARCH' | 'FIT' | 'VALIDATE' | 'REVOKE'
export type RunStatus = 'QUEUED' | 'RUNNING' | 'CANCEL_REQUESTED' | 'SUCCEEDED' | 'FAILED' | 'CANCELLED'
export type RunPhase =
  | 'PROFILING'
  | 'FEASIBILITY'
  | 'RETRIEVING'
  | 'PLANNING'
  | 'SEARCHING'
  | 'FITTING'
  | 'VALIDATING'
  | 'FINALIZING'
export type StopReason =
  | 'BUDGET_EXHAUSTED'
  | 'NO_IMPROVEMENT'
  | 'NUMERICAL_FAILURE'
  | 'AMBIGUOUS'
  | 'USER_CANCELLED'
  | 'COMPLETED'
  | 'DEPENDENCY_FAILURE'
  | 'NO_VALID_CANDIDATE'
export type OutcomeStatus = 'SUPPORTED' | 'AMBIGUOUS' | 'INSUFFICIENT_EVIDENCE' | 'FALSIFIED'

export interface BudgetUsage {
  cpu_seconds: number
  gpu_seconds: number
  tokens: number
  peak_memory_bytes: number
  elapsed_wall_seconds: number
  candidates_generated: number
  candidates_accepted: number
}

export interface Run {
  kind: 'Run'
  id: string
  type: RunType
  status: RunStatus
  revision: number
  created_at: string
  dataset_id: string | null
  research_version_id: string | null
  current_event_cursor: string
  phase?: RunPhase | null
  stop_reason?: StopReason | null
  outcome_status?: OutcomeStatus | null
  budget_usage?: BudgetUsage
  skipped_phases?: { phase: RunPhase; reason: string }[]
  diagnostic_artifact_ids?: string[]
  research_trace_artifact_ids?: string[]
  evidence_bundle_ids?: string[]
  child_run_ids?: string[]
}

export const TERMINAL_STATUSES: readonly RunStatus[] = ['SUCCEEDED', 'FAILED', 'CANCELLED']

export function isTerminal(status: RunStatus): boolean {
  return TERMINAL_STATUSES.includes(status)
}

export async function getRun(client: ApiClient, id: string): Promise<Run> {
  return client.request<Run>('GET', `/api/v2/runs/${id}`)
}

/** 取消需帶目前控制 revision；後端只對 PROFILE 任務提供，其餘回 503。 */
export async function cancelRun(client: ApiClient, run: Run): Promise<Run> {
  return client.request<Run>('POST', `/api/v2/runs/${run.id}/cancel`, {
    json: {},
    headers: { 'Idempotency-Key': newKey(), 'If-Control-Revision': String(run.revision) },
  })
}

/** 取單批已授權事件；游標為 null 時由序號 0 開始。 */
export async function fetchRunEvents(
  client: ApiClient,
  runId: string,
  cursor: string | null,
): Promise<RunEventEnvelope[]> {
  const headers: Record<string, string> = {}
  if (cursor !== null) headers['Last-Event-ID'] = cursor
  const body = await client.text('GET', `/api/v2/runs/${runId}/events`, { headers })
  return parseEventBatch(body)
}
