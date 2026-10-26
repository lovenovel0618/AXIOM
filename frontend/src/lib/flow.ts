/**
 * 研究流程圖的推導：只由後端已回報的真實欄位組出節點與邊，不推測未揭露的內容。
 *
 * 每個節點代表一次可稽核的動作或產物（資料集版本、研究版本、任務、品質與封存、候選、凍結提交、最終評估），
 * 每個節點自帶紀錄（欄位、產物、事件）。邊只表達契約明載的歸屬關係：
 * 任務屬於研究版本、候選屬於 SEARCH 任務、凍結提交屬於研究版本、驗證結果屬於候選或提交槽位。
 * 觀測值（final_test 內容）不進此圖；form 未揭露的分數一律顯示為未提供。
 */
import type { Candidate, EquationVersion, FitRun } from '../api/candidates'
import type { ResearchVersion, ResearchVersionStatus } from '../api/research'
import type { Run, RunStatus, RunType } from '../api/runs'
import type { RunEventEnvelope } from './events'
import { OUTCOME_LABELS, refusalReasons, type ValidationRun } from './evaluation'
import { describeRemaining, QUALITY_LABELS, READINESS_LABELS, type QualityReport } from './evidence'
import { SLOT_STATUS_LABELS, SUBMISSION_STATUS_LABELS, type FinalEvaluation } from './finalEvaluation'

export type FlowNodeKind =
  | 'DATASET'
  | 'VERSION'
  | 'RUN'
  | 'EVIDENCE'
  | 'CANDIDATE'
  | 'SUBMISSION'
  | 'VALIDATION'

/** 節點色調只表示契約狀態，不代表品質評價。 */
export type FlowTone = 'OK' | 'PENDING' | 'RUNNING' | 'FAILED' | 'NEUTRAL'

export interface FlowRecord {
  label: string
  value: string
}

export interface FlowArtifact {
  id: string
  label: string
}

export interface FlowNode {
  id: string
  kind: FlowNodeKind
  /** 由左至右的欄位序；同欄節點代表同一階段的並行產物或分支。 */
  column: number
  row: number
  title: string
  subtitle: string
  badge: string
  tone: FlowTone
  records: FlowRecord[]
  artifacts: FlowArtifact[]
  events: RunEventEnvelope[]
  /** 任務節點可連到任務詳情；其餘為 null。 */
  runId: string | null
}

export interface FlowEdge {
  from: string
  to: string
  /** 同一個父節點分出多條邊時標為分支，供畫面強調。 */
  branch: boolean
}

export interface FlowGraph {
  nodes: FlowNode[]
  edges: FlowEdge[]
  columns: number
  rows: number
}

export interface FlowInput {
  version: ResearchVersion
  runs: Run[]
  candidates: Candidate[]
  equations?: Record<string, EquationVersion>
  fits?: Record<string, FitRun>
  evaluations?: Record<string, ValidationRun>
  finalEvaluations?: Record<string, FinalEvaluation>
  quality?: QualityReport | null
  events?: RunEventEnvelope[]
}

const KIND_COLUMN: Record<FlowNodeKind, number> = {
  DATASET: 0,
  VERSION: 1,
  RUN: 2,
  EVIDENCE: 3,
  CANDIDATE: 4,
  SUBMISSION: 5,
  VALIDATION: 6,
}

export const FLOW_KIND_LABELS: Record<FlowNodeKind, string> = {
  DATASET: '資料集版本',
  VERSION: '研究版本',
  RUN: '任務',
  EVIDENCE: '品質與封存',
  CANDIDATE: '候選假設',
  SUBMISSION: '凍結提交',
  VALIDATION: '最終評估',
}

const RUN_TYPE_LABELS: Record<RunType, string> = {
  INGEST: '匯入',
  PROFILE: '資料剖析',
  SEARCH: '公式搜尋',
  FIT: '擬合',
  VALIDATE: '驗證',
}

const RUN_STATUS_TONES: Record<RunStatus, FlowTone> = {
  QUEUED: 'PENDING',
  RUNNING: 'RUNNING',
  CANCEL_REQUESTED: 'RUNNING',
  SUCCEEDED: 'OK',
  FAILED: 'FAILED',
  CANCELLED: 'NEUTRAL',
}

const VERSION_STATUS_TONES: Record<ResearchVersionStatus, FlowTone> = {
  DRAFT: 'NEUTRAL',
  VALIDATING: 'RUNNING',
  READY: 'OK',
  QUEUED: 'PENDING',
  RUNNING: 'RUNNING',
  FAILED: 'FAILED',
  CANCELLED: 'NEUTRAL',
}

const OUTCOME_TONES: Record<ValidationRun['outcome'], FlowTone> = {
  SUPPORTED: 'OK',
  AMBIGUOUS: 'PENDING',
  INSUFFICIENT_EVIDENCE: 'NEUTRAL',
  FALSIFIED: 'FAILED',
}

function text(value: string | null | undefined): string {
  return value === null || value === undefined || value === '' ? '未提供' : value
}

function number(value: number | null | undefined): string {
  return value === null || value === undefined ? '未提供' : String(value)
}

/** 依序號（ISO 字串）排序並保留同值時的原始次序，讓流程圖與後端建立順序一致。 */
function chronological(runs: Run[]): Run[] {
  return runs
    .map((run, index) => ({ run, index }))
    .sort((left, right) => {
      if (left.run.created_at === right.run.created_at) return left.index - right.index
      return left.run.created_at < right.run.created_at ? -1 : 1
    })
    .map((entry) => entry.run)
}

function runRecords(run: Run): FlowRecord[] {
  const records: FlowRecord[] = [
    { label: '任務識別碼', value: run.id },
    { label: '類型', value: `${run.type}（${RUN_TYPE_LABELS[run.type]}）` },
    { label: '狀態', value: run.status },
    { label: '階段', value: text(run.phase) },
    { label: '停止原因', value: text(run.stop_reason) },
    { label: '結果判定', value: text(run.outcome_status) },
    { label: '控制版本', value: String(run.revision) },
    { label: '建立時間', value: run.created_at },
  ]
  if (run.skipped_phases !== undefined && run.skipped_phases.length > 0) {
    records.push({
      label: '略過階段',
      value: run.skipped_phases.map((entry) => `${entry.phase}：${entry.reason}`).join('；'),
    })
  }
  if (run.child_run_ids !== undefined && run.child_run_ids.length > 0) {
    records.push({ label: '子任務', value: String(run.child_run_ids.length) })
  }
  if (run.budget_usage !== undefined) {
    records.push({
      label: '用量',
      value: `CPU ${String(run.budget_usage.cpu_seconds)} 秒／GPU ${String(run.budget_usage.gpu_seconds)} 秒／Token ${String(run.budget_usage.tokens)}／候選產生 ${String(run.budget_usage.candidates_generated)}、接受 ${String(run.budget_usage.candidates_accepted)}`,
    })
  }
  return records
}

function runArtifacts(run: Run): FlowArtifact[] {
  return [
    ...(run.diagnostic_artifact_ids ?? []).map((id) => ({ id, label: '診斷產物' })),
    ...(run.research_trace_artifact_ids ?? []).map((id) => ({ id, label: '研究軌跡產物' })),
  ]
}

function candidateRecords(
  candidate: Candidate,
  equations: Record<string, EquationVersion>,
  fits: Record<string, FitRun>,
): FlowRecord[] {
  const records: FlowRecord[] = [
    { label: '候選識別碼', value: candidate.id },
    { label: '開發序位', value: number(candidate.development_rank) },
    { label: '來源', value: text(candidate.source) },
    { label: '驗證狀態', value: candidate.validation_status },
    { label: '公式版本', value: candidate.equation_version_id },
    { label: '所屬搜尋任務', value: candidate.search_run_id },
    { label: '擬合任務', value: candidate.fit_run_ids.length === 0 ? '無' : candidate.fit_run_ids.join('、') },
    { label: '驗證任務', value: candidate.validation_run_ids.length === 0 ? '無' : candidate.validation_run_ids.join('、') },
  ]
  const equation = equations[candidate.equation_version_id]
  if (equation !== undefined) {
    records.push({ label: '公式身分雜湊', value: equation.identity_hash })
  }
  const fitId = candidate.fit_run_ids[0]
  const fit = fitId === undefined ? undefined : fits[fitId]
  if (fit !== undefined) {
    const parameters = Object.entries(fit.parameters)
    records.push({ label: '擬合角色', value: fit.split_role })
    records.push({ label: '最佳化器', value: fit.optimizer })
    records.push({ label: '精度位元', value: String(fit.precision_bits) })
    records.push({ label: '擬合列數', value: String(fit.fit_row_ids.length) })
    records.push({
      label: '參數',
      value: parameters.length === 0 ? '無參數' : parameters.map(([name, value]) => `${name} = ${value}`).join('；'),
    })
  }
  // final_test 分數在凍結前不會由後端提供；這裡明示不推測，避免被誤讀成 0 分。
  records.push({ label: 'final_test', value: '尚未評估（凍結前不揭露）' })
  return records
}

function submissionRecords(
  id: string,
  evaluation: FinalEvaluation | undefined,
): FlowRecord[] {
  if (evaluation === undefined) {
    return [
      { label: '提交識別碼', value: id },
      { label: '狀態', value: '未取得或格式不符，不顯示推測內容' },
    ]
  }
  return [
    { label: '提交識別碼', value: id },
    { label: '狀態', value: `${SUBMISSION_STATUS_LABELS[evaluation.status]}（${evaluation.status}）` },
    { label: '指標版本', value: evaluation.metricVersion },
    {
      label: '曝光預算',
      value: `總額 ${String(evaluation.exposure.budget)}／待評估 ${String(evaluation.exposure.reserved)}／已完成 ${String(evaluation.exposure.consumed)}／失敗 ${String(evaluation.exposure.retired)}`,
    },
    { label: '槽位', value: evaluation.slots.length === 0 ? '無' : String(evaluation.slots.length) },
    {
      label: '槽位狀態',
      value:
        evaluation.slots.length === 0
          ? '無'
          : evaluation.slots
              .map((slot) => `${SLOT_STATUS_LABELS[slot.status]}（${slot.frozenCandidateId}）`)
              .join('；'),
    },
  ]
}

function validationRecords(id: string, run: Run | undefined, evaluation: ValidationRun | undefined): FlowRecord[] {
  if (evaluation === undefined) {
    return [
      { label: '驗證結果識別碼', value: id },
      { label: '內容', value: '未取得或格式不符契約，不顯示推測內容' },
      ...(run === undefined ? [] : runRecords(run)),
    ]
  }
  const records: FlowRecord[] = [
    { label: '驗證結果識別碼', value: evaluation.id },
    { label: '結果判定', value: `${OUTCOME_LABELS[evaluation.outcome]}（${evaluation.outcome}）` },
    { label: '指標版本', value: evaluation.metricVersion },
    { label: '切分角色', value: evaluation.splitRole },
    { label: '誤差量', value: `MAE ${number(evaluation.mae)}／RMSE ${number(evaluation.rmse)}` },
    { label: '有效覆蓋率', value: String(evaluation.validCoverage) },
    {
      label: '計數',
      value: `選用 ${String(evaluation.selectedCount)}／可評分 ${String(evaluation.validCount)}／失敗 ${String(evaluation.failedCount)}`,
    },
    { label: '證據等級', value: `${evaluation.empiricalLevel}／${evaluation.proofLevel}` },
    { label: '結果摘要雜湊', value: evaluation.sha256 },
    { label: '建立時間', value: evaluation.createdAt },
  ]
  const reasons = refusalReasons(evaluation)
  if (reasons.length > 0) records.push({ label: '拒答理由', value: reasons.join('；') })
  return records
}

/** 由單一研究版本的真實資料推導流程圖；輸入不完整時只少節點，不以推測補位。 */
export function buildFlow(input: FlowInput): FlowGraph {
  const version = input.version
  const equations = input.equations ?? {}
  const fits = input.fits ?? {}
  const evaluations = input.evaluations ?? {}
  const finalEvaluations = input.finalEvaluations ?? {}
  const events = input.events ?? []
  const researchEvents = events.filter((event) => event.run_id === null)

  const nodes: FlowNode[] = []
  const edges: FlowEdge[] = []
  const rows: number[] = [0, 0, 0, 0, 0, 0, 0]

  function add(node: Omit<FlowNode, 'column' | 'row'>): string {
    const column = KIND_COLUMN[node.kind]
    const row = rows[column] ?? 0
    rows[column] = row + 1
    nodes.push({ ...node, column, row })
    return node.id
  }

  const datasetId = `dataset:${version.dataset_version_id}`
  const profile = version.semantic_profile
  add({
    id: datasetId,
    kind: 'DATASET',
    title: '資料集版本',
    subtitle: '研究分析的輸入來源',
    badge: '—',
    tone: 'NEUTRAL',
    records: [
      { label: '資料集版本', value: version.dataset_version_id },
      { label: '目標量', value: `${profile.target.name}（欄位 ${profile.target.source_column}）` },
      {
        label: '輸入量',
        value:
          profile.inputs.length === 0
            ? '無'
            : profile.inputs.map((item) => `${item.name}（欄位 ${item.source_column}）`).join('；'),
      },
      { label: '單位確認', value: profile.units_confirmed ? '已確認' : '未確認' },
      { label: '時間序列', value: profile.time_ordered ? '是' : '否' },
      { label: '量測解析度', value: text(profile.measurement_resolution) },
      { label: '解析度理由', value: text(profile.resolution_reason) },
      { label: '分組欄位', value: text(profile.group_column) },
    ],
    artifacts: [],
    events: researchEvents,
    runId: null,
  })

  const versionNodeId = add({
    id: `version:${version.id}`,
    kind: 'VERSION',
    title: '研究版本',
    subtitle: `${version.purpose}／控制版本 ${String(version.revision)}`,
    badge: version.status,
    tone: VERSION_STATUS_TONES[version.status],
    records: [
      { label: '研究版本', value: version.id },
      { label: '狀態', value: version.status },
      { label: '目的', value: version.purpose },
      { label: '控制版本', value: String(version.revision) },
      {
        label: '切分',
        value: `${version.observation_split.kind}／fit ${String(version.observation_split.fit.length)} 列／development ${String(version.observation_split.development.length)} 列／final_test ${String(version.observation_split.final_test.length)} 列`,
      },
      { label: '切分器版本', value: version.observation_split.splitter_version },
      { label: '列集合雜湊', value: version.observation_split.row_ids_hash },
      { label: '評估政策雜湊', value: version.evaluation_policy_hash },
      {
        label: '研究用量',
        value: `CPU ${String(version.research_budget_usage.cpu_seconds)} 秒／候選產生 ${String(version.research_budget_usage.candidates_generated)}、接受 ${String(version.research_budget_usage.candidates_accepted)}`,
      },
    ],
    artifacts: [
      ...(version.quality_report_id === null ? [] : [{ id: version.quality_report_id, label: '品質報告產物' }]),
      ...(version.structure_assessment_artifact_id === null
        ? []
        : [{ id: version.structure_assessment_artifact_id, label: '結構評估產物' }]),
      ...(version.refit_policy_artifact_id === null
        ? []
        : [{ id: version.refit_policy_artifact_id, label: '重擬合政策產物' }]),
    ],
    events: researchEvents,
    runId: null,
  })
  edges.push({ from: datasetId, to: versionNodeId, branch: false })

  const orderedRuns = chronological(input.runs)
  const runNodes = new Map<string, string>()
  for (const run of orderedRuns) {
    const id = add({
      id: `run:${run.id}`,
      kind: 'RUN',
      title: `${run.type} 任務`,
      subtitle: text(run.phase),
      badge: run.status,
      tone: RUN_STATUS_TONES[run.status],
      records: runRecords(run),
      artifacts: runArtifacts(run),
      events: events.filter((event) => event.run_id === run.id),
      runId: run.id,
    })
    runNodes.set(run.id, id)
    edges.push({ from: versionNodeId, to: id, branch: false })
  }

  const sealedTestId = version.observation_split.sealed_test_id
  const hasEvidence =
    version.quality_report_id !== null ||
    version.structure_assessment_artifact_id !== null ||
    sealedTestId !== null ||
    version.evidence_bundle_ids.length > 0
  let evidenceNodeId: string | null = null
  if (hasEvidence) {
    const quality = input.quality ?? null
    const remaining = quality?.remaining ?? []
    evidenceNodeId = add({
      id: `evidence:${version.id}`,
      kind: 'EVIDENCE',
      title: '品質與封存',
      subtitle: quality === null ? '品質報告狀態未提供' : `${QUALITY_LABELS[quality.quality]}／${READINESS_LABELS[quality.readiness]}`,
      badge: quality === null ? '未提供' : quality.quality,
      tone: quality === null ? 'NEUTRAL' : quality.quality === 'PASS' ? 'OK' : 'FAILED',
      records: [
        { label: '品質', value: quality === null ? '未提供' : `${QUALITY_LABELS[quality.quality]}（${quality.quality}）` },
        { label: '就緒狀態', value: quality === null ? '未提供' : `${READINESS_LABELS[quality.readiness]}（${quality.readiness}）` },
        { label: '阻擋代碼', value: text(quality?.blockingCode) },
        {
          label: '待完成事項',
          value: remaining.length === 0 ? '無' : remaining.map((code) => `${describeRemaining(code)}（${code}）`).join('；'),
        },
        { label: '封存測試', value: text(sealedTestId) },
        { label: '證據包', value: version.evidence_bundle_ids.length === 0 ? '尚未產生' : version.evidence_bundle_ids.join('、') },
        {
          label: 'fit 摘要',
          value:
            quality?.fitSummary === null || quality?.fitSummary === undefined
              ? '後端未提供'
              : `選用 ${String(quality.fitSummary.selectedCount)} 列／唯一輸入 ${String(quality.fitSummary.uniqueX)}／目標範圍 ${quality.fitSummary.targetMin}～${quality.fitSummary.targetMax}`,
        },
      ],
      artifacts: version.evidence_bundle_ids.map((id) => ({ id, label: '證據包' })),
      events: researchEvents,
      runId: null,
    })
    edges.push({ from: versionNodeId, to: evidenceNodeId, branch: false })
  }

  const candidateNodes = new Map<string, string>()
  for (const candidate of input.candidates) {
    const id = add({
      id: `candidate:${candidate.id}`,
      kind: 'CANDIDATE',
      title: `候選 #${number(candidate.development_rank)}`,
      subtitle: text(candidate.source),
      badge: candidate.validation_status,
      tone:
        candidate.validation_status === 'FINISHED'
          ? 'OK'
          : candidate.validation_status === 'INVALID'
            ? 'FAILED'
            : candidate.validation_status === 'PENDING'
              ? 'RUNNING'
              : 'NEUTRAL',
      records: candidateRecords(candidate, equations, fits),
      artifacts: [],
      events: [],
      runId: null,
    })
    candidateNodes.set(candidate.id, id)
    const parent = runNodes.get(candidate.search_run_id)
    if (parent !== undefined) edges.push({ from: parent, to: id, branch: false })
    else edges.push({ from: versionNodeId, to: id, branch: false })
  }

  const validationReferences = new Set<string>()
  for (const candidate of input.candidates) {
    for (const validationId of candidate.validation_run_ids) validationReferences.add(validationId)
  }
  for (const submissionId of version.frozen_submission_ids) {
    const evaluation = finalEvaluations[submissionId]
    if (evaluation === undefined) continue
    for (const slot of evaluation.slots) {
      if (slot.validationRunId !== null) validationReferences.add(slot.validationRunId)
    }
  }
  for (const run of orderedRuns) {
    if (run.type === 'VALIDATE') validationReferences.add(run.id)
  }

  const submissionNodes = new Map<string, string>()
  for (const submissionId of version.frozen_submission_ids) {
    const evaluation = finalEvaluations[submissionId]
    const id = add({
      id: `submission:${submissionId}`,
      kind: 'SUBMISSION',
      title: '凍結提交',
      subtitle: evaluation === undefined ? '狀態未取得' : `指標版本 ${evaluation.metricVersion}`,
      badge: evaluation === undefined ? '未取得' : evaluation.status,
      tone:
        evaluation === undefined
          ? 'NEUTRAL'
          : evaluation.status === 'EVALUATED'
            ? 'OK'
            : evaluation.status === 'FAILED'
              ? 'FAILED'
              : evaluation.status === 'EVALUATING'
                ? 'RUNNING'
                : 'PENDING',
      records: submissionRecords(submissionId, evaluation),
      artifacts: [],
      events: researchEvents,
      runId: null,
    })
    submissionNodes.set(submissionId, id)
    edges.push({ from: versionNodeId, to: id, branch: false })
  }

  const validationNodes = new Map<string, string>()
  for (const validationId of validationReferences) {
    const run = orderedRuns.find((row) => row.id === validationId)
    const evaluation = evaluations[validationId]
    const id = add({
      id: `validation:${validationId}`,
      kind: 'VALIDATION',
      title: '最終評估',
      subtitle: evaluation === undefined ? (run?.type ?? '結果未取得') : evaluation.splitRole,
      badge: evaluation === undefined ? (run?.status ?? '未取得') : evaluation.outcome,
      tone:
        evaluation === undefined
          ? run === undefined
            ? 'NEUTRAL'
            : RUN_STATUS_TONES[run.status]
          : OUTCOME_TONES[evaluation.outcome],
      records: validationRecords(validationId, run, evaluation),
      artifacts: run === undefined ? [] : runArtifacts(run),
      events: events.filter((event) => event.run_id === validationId),
      runId: run === undefined ? null : run.id,
    })
    validationNodes.set(validationId, id)
  }

  for (const candidate of input.candidates) {
    const source = candidateNodes.get(candidate.id)
    if (source === undefined) continue
    for (const validationId of candidate.validation_run_ids) {
      const target = validationNodes.get(validationId)
      if (target !== undefined) edges.push({ from: source, to: target, branch: false })
    }
  }
  for (const submissionId of version.frozen_submission_ids) {
    const source = submissionNodes.get(submissionId)
    if (source === undefined) continue
    const evaluation = finalEvaluations[submissionId]
    if (evaluation === undefined) continue
    for (const slot of evaluation.slots) {
      if (slot.validationRunId === null) continue
      const target = validationNodes.get(slot.validationRunId)
      if (target !== undefined) edges.push({ from: source, to: target, branch: false })
    }
  }

  // 只有實際存在的邊才算數：驗證節點若無任何來源（例如候選引用了未載入的結果），仍保留節點但不畫假邊。
  const outgoing = new Map<string, number>()
  for (const edge of edges) outgoing.set(edge.from, (outgoing.get(edge.from) ?? 0) + 1)
  const marked = edges.map((edge) => ({ ...edge, branch: (outgoing.get(edge.from) ?? 0) > 1 }))

  const columns = rows.length
  const maxRows = rows.reduce((best, count) => Math.max(best, count), 0)
  return { nodes, edges: marked, columns, rows: maxRows }
}
