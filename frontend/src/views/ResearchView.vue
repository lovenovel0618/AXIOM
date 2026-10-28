<script setup lang="ts">
/**
 * 研究工作台（SSOT SCREEN 07）：多面板自主研究進度與假設探索。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { getArtifactContent } from '../api/artifacts'
import { getFinalEvaluation, getValidationRun } from '../api/evaluations'
import {
  createSearchRun,
  fetchResearchEventBatch,
  getResearchVersion,
  listResearchVersionRuns,
  listResearchVersions,
  listResearches,
  type Research,
  type ResearchVersion,
} from '../api/research'
import type { Run } from '../api/runs'
import { listRunCandidates, type Candidate } from '../api/candidates'
import ResearchFlow from '../components/ResearchFlow.vue'
import { parseQualityReport, describeBlindEvaluation, type QualityReport } from '../lib/evidence'
import type { RunEventEnvelope } from '../lib/events'
import { parseValidationRun, type ValidationRun } from '../lib/evaluation'
import { parseFinalEvaluation, type FinalEvaluation } from '../lib/finalEvaluation'
import { buildFlow, type FlowGraph, type FlowNode, type FlowNodeKind, type FlowTone } from '../lib/flow'
import { describeError } from '../lib/messages'
import { readBackRef, withBackRef } from '../lib/navigationState'
import { readQueryList, readQueryString, replaceQueryState } from '../lib/queryState'
import { filterFlowGraph, highlightFlowNodes, type FlowFilterState } from '../lib/researchFlowFilters'
import {
  buildCandidateFocusDetailPanel,
  buildCandidateFocusSummary,
  buildFocusCollectionDigest,
  buildNodeActionLinks,
  buildSubmissionFocusDetailPanel,
  buildSubmissionFocusSummary,
  collectCandidateCollectionLinks,
  collectSubmissionCollectionLink,
  findNodeIdsByRecordValues,
  groupNodeArtifacts,
  groupNodeEvents,
  recentNodeEvents,
  summarizeEventPayload,
} from '../lib/researchNodeDetails'
import { client } from '../lib/session'

const route = useRoute()
const router = useRouter()

const researches = ref<Research[]>([])
const versions = ref<ResearchVersion[]>([])
const workbenchVersion = ref<ResearchVersion | null>(null)
const runs = ref<Run[]>([])
const candidates = ref<Candidate[]>([])
const researchEvents = ref<RunEventEnvelope[]>([])
const quality = ref<QualityReport | null>(null)
const validationMap = ref<Record<string, ValidationRun>>({})
const finalEvaluationMap = ref<Record<string, FinalEvaluation>>({})

const loading = ref(false)
const refreshingWorkbench = ref(false)
const startingSearch = ref(false)
const error = ref('')
const notice = ref('')
const selectedResearch = ref<Research | null>(null)
const selectedVersionId = ref('')
const selectedNodeId = ref<string | null>(readQueryString(route.query, 'node') || null)
const backRef = computed(() => readBackRef(route.query))
const focusCandidateIds = ref<string[]>(readQueryList(route.query, 'focuscandidates'))
const focusSubmissionIds = ref<string[]>(readQueryList(route.query, 'focussubmissions'))
const flowKindFilter = ref<'ALL' | FlowNodeKind>(
  (['ALL', 'DATASET', 'VERSION', 'RUN', 'EVIDENCE', 'CANDIDATE', 'SUBMISSION', 'VALIDATION'] as const).includes(
    readQueryString(route.query, 'flowkind') as 'ALL' | FlowNodeKind,
  )
    ? (readQueryString(route.query, 'flowkind') as 'ALL' | FlowNodeKind)
    : 'ALL',
)
const flowToneFilter = ref<'ALL' | FlowTone>(
  (['ALL', 'NEUTRAL', 'PENDING', 'RUNNING', 'OK', 'FAILED'] as const).includes(
    readQueryString(route.query, 'flowtone') as 'ALL' | FlowTone,
  )
    ? (readQueryString(route.query, 'flowtone') as 'ALL' | FlowTone)
    : 'ALL',
)
const flowQuery = ref(readQueryString(route.query, 'flowq'))

/** 目前路由上的研究容器識別碼；`/researches/:id` 以外一律為空字串。 */
const currentResearchId = computed<string>(() => {
  const id = typeof route.params.id === 'string' ? route.params.id : ''
  return id === 'new' ? '' : id
})

const graph = computed<FlowGraph | null>(() => {
  if (workbenchVersion.value === null) return null
  return buildFlow({
    version: workbenchVersion.value,
    runs: runs.value,
    candidates: candidates.value,
    evaluations: validationMap.value,
    finalEvaluations: finalEvaluationMap.value,
    quality: quality.value,
    events: researchEvents.value,
  })
})

const flowFilters = computed<FlowFilterState>(() => ({
  kind: flowKindFilter.value,
  tone: flowToneFilter.value,
  query: flowQuery.value,
}))

const displayGraph = computed<FlowGraph | null>(() =>
  graph.value === null ? null : filterFlowGraph(graph.value, flowFilters.value),
)

const selectedNode = computed<FlowNode | null>(() => {
  const current = displayGraph.value
  if (current === null) return null
  return current.nodes.find((node) => node.id === selectedNodeId.value) ?? current.nodes[0] ?? null
})
const selectedNodeArtifactGroups = computed(() =>
  selectedNode.value === null ? [] : groupNodeArtifacts(selectedNode.value.artifacts),
)
const selectedNodeEventGroups = computed(() =>
  selectedNode.value === null ? [] : groupNodeEvents(selectedNode.value.events),
)
const selectedNodeRecentEvents = computed(() =>
  selectedNode.value === null ? [] : recentNodeEvents(selectedNode.value.events, 8),
)
const selectedNodeActions = computed(() =>
  selectedNode.value === null
    ? []
    : buildNodeActionLinks(selectedNode.value, (extra) => withBackRef(route.fullPath, extra), currentResearchId.value),
)
const visibleCandidateCollections = computed(() =>
  displayGraph.value === null ? [] : collectCandidateCollectionLinks(displayGraph.value.nodes),
)
const visibleSubmissionCollection = computed(() =>
  displayGraph.value === null ? null : collectSubmissionCollectionLink(displayGraph.value.nodes),
)
const candidateFocusSummary = computed(() =>
  displayGraph.value === null ? null : buildCandidateFocusSummary(displayGraph.value.nodes, focusCandidateIds.value),
)
const submissionFocusSummary = computed(() =>
  displayGraph.value === null ? null : buildSubmissionFocusSummary(displayGraph.value.nodes, focusSubmissionIds.value),
)
const candidateFocusPanel = computed(() =>
  displayGraph.value === null ? null : buildCandidateFocusDetailPanel(displayGraph.value.nodes, focusCandidateIds.value),
)
const submissionFocusPanel = computed(() =>
  displayGraph.value === null ? null : buildSubmissionFocusDetailPanel(displayGraph.value.nodes, focusSubmissionIds.value),
)
const focusedCandidateNodeIds = computed(() =>
  displayGraph.value === null ? [] : findNodeIdsByRecordValues(displayGraph.value.nodes, '候選識別碼', focusCandidateIds.value),
)
const focusedSubmissionNodeIds = computed(() =>
  displayGraph.value === null ? [] : findNodeIdsByRecordValues(displayGraph.value.nodes, '提交識別碼', focusSubmissionIds.value),
)
const hasFocusWorkspace = computed(() => candidateFocusSummary.value !== null || submissionFocusSummary.value !== null)
const activeFocusScope = computed<'candidate' | 'submission' | null>(() => {
  if (selectedNode.value?.kind === 'CANDIDATE' && candidateFocusPanel.value !== null) return 'candidate'
  if (selectedNode.value?.kind === 'SUBMISSION' && submissionFocusPanel.value !== null) return 'submission'
  if (candidateFocusPanel.value !== null) return 'candidate'
  if (submissionFocusPanel.value !== null) return 'submission'
  return null
})
const activeFocusPanel = computed(() =>
  activeFocusScope.value === 'candidate'
    ? candidateFocusPanel.value
    : activeFocusScope.value === 'submission'
      ? submissionFocusPanel.value
      : null,
)
const activeFocusLabel = computed(() =>
  activeFocusScope.value === 'candidate' ? '候選集合導覽' : activeFocusScope.value === 'submission' ? '提交集合導覽' : '',
)
const activeFocusIndex = computed(() =>
  activeFocusPanel.value === null || selectedNode.value === null
    ? -1
    : activeFocusPanel.value.items.findIndex((item) => item.nodeId === selectedNode.value?.id),
)
const activeFocusDigest = computed(() =>
  activeFocusPanel.value === null || displayGraph.value === null
    ? null
    : buildFocusCollectionDigest(displayGraph.value.nodes, activeFocusPanel.value),
)
const flowHighlightIds = computed(() =>
  displayGraph.value === null
    ? []
    : [
        ...new Set([
          ...highlightFlowNodes(displayGraph.value, selectedNodeId.value),
          ...focusedCandidateNodeIds.value,
          ...focusedSubmissionNodeIds.value,
        ]),
      ],
)

const backQuery = computed<Record<string, string>>(() => withBackRef(route.fullPath))
const flowKindOptions: Array<'ALL' | FlowNodeKind> = [
  'ALL',
  'DATASET',
  'VERSION',
  'RUN',
  'EVIDENCE',
  'CANDIDATE',
  'SUBMISSION',
  'VALIDATION',
]
const flowToneOptions: Array<'ALL' | FlowTone> = ['ALL', 'NEUTRAL', 'PENDING', 'RUNNING', 'OK', 'FAILED']

const runCounts = computed(() => ({
  total: runs.value.length,
  active: runs.value.filter((row) => ['QUEUED', 'RUNNING', 'CANCEL_REQUESTED'].includes(row.status)).length,
  failed: runs.value.filter((row) => row.status === 'FAILED').length,
}))

const blindEvaluation = computed(() =>
  describeBlindEvaluation({
    sealedTestId: workbenchVersion.value?.observation_split.sealed_test_id ?? null,
    frozenSubmissionCount: workbenchVersion.value?.frozen_submission_ids.length ?? 0,
  }),
)

function workbenchSteps(version: ResearchVersion | null): Array<{ label: string; done: boolean }> {
  if (version === null) {
    return [
      { label: '建立研究', done: false },
      { label: '建立研究版本', done: false },
      { label: '啟動 PROFILE', done: false },
      { label: '產生候選分支', done: false },
      { label: '封存與驗證', done: false },
    ]
  }
  return [
    { label: '建立研究', done: true },
    { label: '建立研究版本', done: true },
    { label: '啟動 PROFILE', done: version.status !== 'DRAFT' },
    { label: '產生候選分支', done: candidates.value.length > 0 },
    { label: '封存與驗證', done: version.frozen_submission_ids.length > 0 || version.evidence_bundle_ids.length > 0 },
  ]
}

async function loadResearches(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const page = await listResearches(client)
    researches.value = page.items
  } catch (cause) {
    error.value = describeError(cause)
  } finally {
    loading.value = false
  }
}

function clearWorkbench(): void {
  workbenchVersion.value = null
  runs.value = []
  candidates.value = []
  researchEvents.value = []
  quality.value = null
  validationMap.value = {}
  finalEvaluationMap.value = {}
  selectedNodeId.value = null
}

async function loadVersions(): Promise<void> {
  const id = typeof route.params.id === 'string' ? route.params.id : ''
  if (id === '' || id === 'new') {
    selectedResearch.value = null
    versions.value = []
    selectedVersionId.value = ''
    clearWorkbench()
    return
  }

  selectedResearch.value = researches.value.find((row) => row.id === id) ?? null
  if (selectedResearch.value === null) {
    versions.value = []
    selectedVersionId.value = ''
    clearWorkbench()
    return
  }

  try {
    const page = await listResearchVersions(client, id)
    versions.value = page.items
    const requestedVersion = typeof route.query.version === 'string' ? route.query.version : ''
    selectedVersionId.value = versions.value.some((row) => row.id === requestedVersion)
      ? requestedVersion
      : (versions.value[0]?.id ?? '')
  } catch (cause) {
    versions.value = []
    selectedVersionId.value = ''
    clearWorkbench()
    error.value = describeError(cause)
  }
}

async function loadWorkbench(versionId: string): Promise<void> {
  if (versionId === '') {
    clearWorkbench()
    return
  }

  refreshingWorkbench.value = true
  error.value = ''
  try {
    const version = await getResearchVersion(client, versionId)
    workbenchVersion.value = version
    versions.value = versions.value.map((row) => (row.id === version.id ? version : row))

    const runPage = await listResearchVersionRuns(client, versionId)
    runs.value = runPage.items

    researchEvents.value = (await fetchResearchEventBatch(client, versionId, null)).events

    const collectedCandidates: Candidate[] = []
    for (const row of runPage.items) {
      if (row.type !== 'SEARCH') continue
      try {
        const page = await listRunCandidates(client, row.id, { limit: 50 })
        collectedCandidates.push(...page.items)
      } catch {
        // 候選分頁單獨失敗時保留其餘資料，不用空資料覆蓋整個工作台。
      }
    }
    candidates.value = collectedCandidates

    const validations: Record<string, ValidationRun> = {}
    const validationIds = new Set<string>()
    for (const row of collectedCandidates) {
      for (const validationId of row.validation_run_ids) validationIds.add(validationId)
    }
    for (const validationId of validationIds) {
      try {
        const parsed = parseValidationRun(await getValidationRun(client, validationId))
        if (parsed !== null) validations[validationId] = parsed
      } catch {
        // 逐筆缺失不推測也不拋全域錯。
      }
    }
    validationMap.value = validations

    const finalEvaluations: Record<string, FinalEvaluation> = {}
    for (const submissionId of version.frozen_submission_ids) {
      try {
        const parsed = parseFinalEvaluation(await getFinalEvaluation(client, submissionId))
        if (parsed !== null) finalEvaluations[submissionId] = parsed
      } catch {
        // 評估尚未產生時保持空白狀態。
      }
    }
    finalEvaluationMap.value = finalEvaluations

    if (version.quality_report_id === null) {
      quality.value = null
    } else {
      try {
        quality.value = parseQualityReport(await getArtifactContent<unknown>(client, version.quality_report_id))
      } catch {
        quality.value = null
      }
    }
  } catch (cause) {
    clearWorkbench()
    error.value = describeError(cause)
  } finally {
    refreshingWorkbench.value = false
  }
}

async function startSearch(): Promise<void> {
  const version = workbenchVersion.value
  if (version === null || startingSearch.value) return
  startingSearch.value = true
  error.value = ''
  notice.value = ''
  try {
    const run = await createSearchRun(client, version.id, version.revision, Date.now())
    notice.value = `已建立 SEARCH 任務 ${run.id}。`
    await loadWorkbench(version.id)
  } catch (cause) {
    error.value = describeError(cause)
  } finally {
    startingSearch.value = false
  }
}

function selectNode(id: string): void {
  selectedNodeId.value = id
}

function summarizeNodePayload(payload: Record<string, unknown>): string {
  return summarizeEventPayload(payload)
}

function summarizeMissingIds(ids: string[]): string {
  if (ids.length === 0) return ''
  if (ids.length <= 3) return ids.join('、')
  return `${ids.slice(0, 3).join('、')} 等 ${ids.length} 筆`
}

function focusCandidateCollection(): void {
  const summary = candidateFocusSummary.value
  if (summary === null || summary.matchedNodeIds.length === 0) return
  flowKindFilter.value = 'CANDIDATE'
  flowToneFilter.value = 'ALL'
  flowQuery.value = ''
  selectedNodeId.value = summary.matchedNodeIds[0] ?? null
}

function focusSubmissionCollection(): void {
  const summary = submissionFocusSummary.value
  if (summary === null || summary.matchedNodeIds.length === 0) return
  flowKindFilter.value = 'SUBMISSION'
  flowToneFilter.value = 'ALL'
  flowQuery.value = ''
  selectedNodeId.value = summary.matchedNodeIds[0] ?? null
}

async function clearFocusScope(scope: 'candidate' | 'submission' | 'all'): Promise<void> {
  const candidateSummary = candidateFocusSummary.value
  const submissionSummary = submissionFocusSummary.value
  let nextKind: 'ALL' | FlowNodeKind = flowKindFilter.value
  let nextNode = selectedNodeId.value
  const patch: Record<string, string | undefined> = {}

  if (scope === 'all') {
    focusCandidateIds.value = []
    focusSubmissionIds.value = []
    nextKind = 'ALL'
    nextNode = null
    patch.focuscandidates = undefined
    patch.focussubmissions = undefined
  } else if (scope === 'candidate') {
    focusCandidateIds.value = []
    patch.focuscandidates = undefined
    if (flowKindFilter.value === 'CANDIDATE') {
      nextKind = submissionSummary === null ? 'ALL' : 'SUBMISSION'
    }
    if (selectedNode.value?.kind === 'CANDIDATE') {
      nextNode = submissionSummary?.matchedNodeIds[0] ?? null
    }
  } else {
    focusSubmissionIds.value = []
    patch.focussubmissions = undefined
    if (flowKindFilter.value === 'SUBMISSION') {
      nextKind = candidateSummary === null ? 'ALL' : 'CANDIDATE'
    }
    if (selectedNode.value?.kind === 'SUBMISSION') {
      nextNode = candidateSummary?.matchedNodeIds[0] ?? null
    }
  }

  flowKindFilter.value = nextKind
  selectedNodeId.value = nextNode
  patch.flowkind = nextKind === 'ALL' ? undefined : nextKind
  patch.node = nextNode ?? undefined
  await replaceQueryState(router, route, patch)
}

function selectFocusPanelItem(nodeId: string): void {
  selectedNodeId.value = nodeId
}

function moveFocusSelection(direction: -1 | 1): void {
  const panel = activeFocusPanel.value
  if (panel === null || panel.items.length === 0) return
  const currentIndex = activeFocusIndex.value
  const nextIndex =
    currentIndex < 0
      ? 0
      : (currentIndex + direction + panel.items.length) % panel.items.length
  selectedNodeId.value = panel.items[nextIndex]?.nodeId ?? null
}

function resolveSelectedNodeId(next: FlowGraph | null): string | null {
  if (next === null || next.nodes.length === 0) return null
  const requested = readQueryString(route.query, 'node')
  if (requested !== '' && next.nodes.some((node) => node.id === requested)) return requested
  const focusedCandidate = findNodeIdsByRecordValues(next.nodes, '候選識別碼', focusCandidateIds.value)[0]
  if (focusedCandidate !== undefined) return focusedCandidate
  const focused = findNodeIdsByRecordValues(next.nodes, '提交識別碼', focusSubmissionIds.value)[0]
  if (focused !== undefined) return focused
  if (selectedNodeId.value !== null && next.nodes.some((node) => node.id === selectedNodeId.value)) {
    return selectedNodeId.value
  }
  return next.nodes[0]?.id ?? null
}

onMounted(async () => {
  await loadResearches()
  await loadVersions()
})

watch(
  () => route.params.id,
  async () => {
    await loadResearches()
    await loadVersions()
  },
)

watch(
  () => route.query.version,
  async (value) => {
    const requested = typeof value === 'string' ? value : ''
    if (requested !== '' && requested !== selectedVersionId.value) selectedVersionId.value = requested
  },
)

watch(
  [flowKindFilter, flowToneFilter, flowQuery],
  async ([kind, tone, query]) => {
    if (currentResearchId.value === '') return
    await replaceQueryState(router, route, {
      flowkind: kind === 'ALL' ? undefined : kind,
      flowtone: tone === 'ALL' ? undefined : tone,
      flowq: query === '' ? undefined : query,
    })
  },
)

watch(
  selectedNodeId,
  async (value) => {
    if (currentResearchId.value === '') return
    await replaceQueryState(router, route, { node: value ?? undefined })
  },
)

watch(
  () => route.query,
  () => {
    focusCandidateIds.value = readQueryList(route.query, 'focuscandidates')
    focusSubmissionIds.value = readQueryList(route.query, 'focussubmissions')
    flowKindFilter.value =
      (['ALL', 'DATASET', 'VERSION', 'RUN', 'EVIDENCE', 'CANDIDATE', 'SUBMISSION', 'VALIDATION'] as const).includes(
        readQueryString(route.query, 'flowkind') as 'ALL' | FlowNodeKind,
      )
        ? (readQueryString(route.query, 'flowkind') as 'ALL' | FlowNodeKind)
        : 'ALL'
    flowToneFilter.value =
      (['ALL', 'NEUTRAL', 'PENDING', 'RUNNING', 'OK', 'FAILED'] as const).includes(
        readQueryString(route.query, 'flowtone') as 'ALL' | FlowTone,
      )
        ? (readQueryString(route.query, 'flowtone') as 'ALL' | FlowTone)
        : 'ALL'
    flowQuery.value = readQueryString(route.query, 'flowq')
    selectedNodeId.value = readQueryString(route.query, 'node') || null
  },
)

watch(
  selectedVersionId,
  async (value) => {
    if (currentResearchId.value === '') return
    const nextQuery = { ...route.query }
    if (value === '') delete nextQuery.version
    else nextQuery.version = value
    if ((typeof route.query.version === 'string' ? route.query.version : '') !== value) {
      await router.replace({ query: nextQuery })
    }
    await loadWorkbench(value)
  },
  { immediate: true },
)

watch(displayGraph, (next) => {
  selectedNodeId.value = resolveSelectedNodeId(next)
})
</script>

<template>
  <section>
    <div class="head">
      <div>
        <div class="eyebrow">研究 / 第 8 頁</div>
        <h1>研究工作台</h1>
        <p class="muted">以真實研究版本、任務、候選與事件重建工作流。</p>
      </div>
      <div class="actions">
        <button v-if="backRef !== ''" type="button" @click="router.push(backRef)">返回來源頁</button>
        <button type="button" @click="loadResearches">重新載入</button>
        <button
          type="button"
          :disabled="selectedVersionId === '' || refreshingWorkbench"
          @click="loadWorkbench(selectedVersionId)"
        >
          {{ refreshingWorkbench ? '同步中…' : '同步工作台' }}
        </button>
        <button
          type="button"
          class="primary"
          :disabled="workbenchVersion === null || startingSearch"
          @click="startSearch"
        >
          {{ startingSearch ? '建立中…' : '啟動 SEARCH' }}
        </button>
        <RouterLink :to="{ name: 'research-list' }">
          <button type="button">回研究清單</button>
        </RouterLink>
        <button type="button" class="primary" @click="router.push({ name: 'research-create' })">
          新增 / 執行
        </button>
      </div>
    </div>

    <div class="layout cols3">
        <section class="card">
          <h3>研究版本</h3>
          <div class="row">
            <span>研究名稱</span>
            <span>{{ selectedResearch?.name ?? '未找到研究' }}</span>
          </div>
          <div class="row">
            <span>最新版本數</span>
            <span class="tag">{{ versions.length }}</span>
          </div>
          <div class="row">
            <span>任務數</span>
            <span class="tag">{{ runCounts.total }}</span>
          </div>
          <div class="row">
            <span>候選分支</span>
            <span class="tag">{{ candidates.length }}</span>
          </div>
          <div class="row">
            <span>盲測狀態</span>
            <span class="tag" :class="blindEvaluation.tone === 'BLOCKED' ? 'bad' : 'warn'">
              {{ blindEvaluation.summary }}
            </span>
          </div>

          <div v-if="versions.length === 0" class="muted" style="margin-top: 12px;">目前研究尚無研究版本。</div>
          <button
            v-for="row in versions"
            :key="row.id"
            type="button"
            class="branch"
            :class="{ active: selectedVersionId === row.id }"
            @click="selectedVersionId = row.id"
          >
            <div>
              <strong>{{ row.purpose }}</strong>
              <div class="muted mono">{{ row.id }}</div>
            </div>
            <span class="tag">{{ row.status }}</span>
          </button>

          <div class="stage-list">
            <div v-for="step in workbenchSteps(workbenchVersion)" :key="step.label" class="row">
              <span>{{ step.label }}</span>
              <span class="tag" :class="step.done ? 'good' : 'warn'">{{ step.done ? '完成' : '待續' }}</span>
            </div>
          </div>
        </section>

        <section class="card">
          <h3>工作流流程圖</h3>
          <p v-if="workbenchVersion === null" class="muted">請先選擇一個研究版本。</p>
          <template v-else>
            <div class="row compact">
              <span>資料集版本</span>
              <span class="mono">{{ workbenchVersion.dataset_version_id }}</span>
            </div>
            <div class="row compact">
              <span>研究狀態</span>
              <span class="tag">{{ workbenchVersion.status }}</span>
            </div>
            <div class="formgrid flow-filters">
              <div class="field">
                <label>節點類型</label>
                <select v-model="flowKindFilter">
                  <option v-for="option in flowKindOptions" :key="option" :value="option">{{ option }}</option>
                </select>
              </div>
              <div class="field">
                <label>節點狀態</label>
                <select v-model="flowToneFilter">
                  <option v-for="option in flowToneOptions" :key="option" :value="option">{{ option }}</option>
                </select>
              </div>
              <div class="field">
                <label>關鍵字</label>
                <input v-model="flowQuery" placeholder="搜尋標題 / 摘要 / 欄位">
              </div>
            </div>
            <div class="actions wrap" style="margin-bottom: 12px;">
              <button type="button" @click="flowKindFilter = 'ALL'; flowToneFilter = 'ALL'; flowQuery = ''">
                清空流程篩選
              </button>
              <span class="tag">{{ displayGraph?.nodes.length ?? 0 }} / {{ graph?.nodes.length ?? 0 }} 節點</span>
            </div>
            <section v-if="hasFocusWorkspace" class="focus-workspace">
              <div class="focus-workspace-head">
                <div>
                  <strong>焦點集合工作區</strong>
                  <p class="muted">整合從發現頁與驗證頁帶回的集合，支援聚焦、清除與成組回跳。</p>
                </div>
                <div class="actions wrap">
                  <button type="button" @click="clearFocusScope('all')">清除全部焦點</button>
                </div>
              </div>

              <div class="focus-grid">
                <section v-if="candidateFocusSummary !== null" class="focus-card">
                  <div class="row compact">
                    <span>來源</span>
                    <span class="tag">發現頁 / 候選集合</span>
                  </div>
                  <div class="row compact">
                    <span>帶回候選</span>
                    <span class="tag">{{ candidateFocusSummary.requestedIds.length }}</span>
                  </div>
                  <div class="row compact">
                    <span>命中節點</span>
                    <span class="tag">{{ candidateFocusSummary.matchedValues.length }}</span>
                  </div>
                  <div class="row compact">
                    <span>SEARCH 任務</span>
                    <span class="tag">{{ candidateFocusSummary.groups.length }}</span>
                  </div>
                  <div class="row compact">
                    <span>未命中</span>
                    <span class="tag" :class="candidateFocusSummary.missingIds.length === 0 ? 'good' : 'warn'">
                      {{ candidateFocusSummary.missingIds.length }}
                    </span>
                  </div>
                  <div class="actions wrap" style="margin: 12px 0;">
                    <button
                      type="button"
                      :disabled="candidateFocusSummary.matchedNodeIds.length === 0"
                      @click="focusCandidateCollection"
                    >
                      聚焦候選節點
                    </button>
                    <button type="button" @click="clearFocusScope('candidate')">清除此集合</button>
                  </div>
                  <div v-if="candidateFocusSummary.groups.length !== 0" class="candidate-actions">
                    <RouterLink
                      v-for="group in candidateFocusSummary.groups"
                      :key="`focus:${group.searchRunId}`"
                      :to="{
                        name: 'discoveries',
                        query: withBackRef(route.fullPath, {
                          run: group.searchRunId,
                          pins: group.candidateIds.join(','),
                        }),
                      }"
                      class="candidate-action-link"
                    >
                      <strong>回到 {{ group.label }}</strong>
                      <span class="muted mono">{{ group.searchRunId }}</span>
                    </RouterLink>
                  </div>
                  <p v-else class="muted">目前流程圖中沒有命中的候選節點。</p>
                  <div v-if="candidateFocusSummary.missingIds.length !== 0" class="note focus-missing">
                    尚有候選未出現在目前流程圖：{{ summarizeMissingIds(candidateFocusSummary.missingIds) }}
                  </div>
                </section>

                <section v-if="submissionFocusSummary !== null" class="focus-card">
                  <div class="row compact">
                    <span>來源</span>
                    <span class="tag">驗證頁 / 提交集合</span>
                  </div>
                  <div class="row compact">
                    <span>帶回提交</span>
                    <span class="tag">{{ submissionFocusSummary.requestedIds.length }}</span>
                  </div>
                  <div class="row compact">
                    <span>命中節點</span>
                    <span class="tag">{{ submissionFocusSummary.matchedValues.length }}</span>
                  </div>
                  <div class="row compact">
                    <span>目前可見集合</span>
                    <span class="tag">{{ submissionFocusSummary.group === null ? 0 : 1 }}</span>
                  </div>
                  <div class="row compact">
                    <span>未命中</span>
                    <span class="tag" :class="submissionFocusSummary.missingIds.length === 0 ? 'good' : 'warn'">
                      {{ submissionFocusSummary.missingIds.length }}
                    </span>
                  </div>
                  <div class="actions wrap" style="margin: 12px 0;">
                    <button
                      type="button"
                      :disabled="submissionFocusSummary.matchedNodeIds.length === 0"
                      @click="focusSubmissionCollection"
                    >
                      聚焦提交節點
                    </button>
                    <button type="button" @click="clearFocusScope('submission')">清除此集合</button>
                  </div>
                  <div v-if="submissionFocusSummary.group !== null" class="candidate-actions">
                    <RouterLink
                      :to="{
                        name: 'verification',
                        query: withBackRef(route.fullPath, {
                          submission: submissionFocusSummary.group.submissionIds[0],
                          submissions: submissionFocusSummary.group.submissionIds.join(','),
                        }),
                      }"
                      class="candidate-action-link"
                    >
                      <strong>回到 {{ submissionFocusSummary.group.label }}</strong>
                      <span class="muted mono">驗證中心</span>
                    </RouterLink>
                  </div>
                  <p v-else class="muted">目前流程圖中沒有命中的提交節點。</p>
                  <div v-if="submissionFocusSummary.missingIds.length !== 0" class="note focus-missing">
                    尚有提交未出現在目前流程圖：{{ summarizeMissingIds(submissionFocusSummary.missingIds) }}
                  </div>
                </section>
              </div>
            </section>
            <div v-if="visibleCandidateCollections.length !== 0" class="candidate-actions">
              <RouterLink
                v-for="group in visibleCandidateCollections"
                :key="group.searchRunId"
                :to="{
                  name: 'discoveries',
                  query: withBackRef(route.fullPath, {
                    run: group.searchRunId,
                    pins: group.candidateIds.join(','),
                  }),
                }"
                class="candidate-action-link"
              >
                <strong>比較 {{ group.label }}</strong>
                <span class="muted mono">{{ group.searchRunId }}</span>
              </RouterLink>
            </div>
            <div v-if="visibleSubmissionCollection !== null" class="candidate-actions">
              <RouterLink
                :to="{
                  name: 'verification',
                  query: withBackRef(route.fullPath, {
                    submission: visibleSubmissionCollection.submissionIds[0],
                    submissions: visibleSubmissionCollection.submissionIds.join(','),
                  }),
                }"
                class="candidate-action-link"
              >
                <strong>查看 {{ visibleSubmissionCollection.label }}</strong>
                <span class="muted mono">驗證中心</span>
              </RouterLink>
            </div>
            <ResearchFlow
              v-if="displayGraph !== null"
              :graph="displayGraph"
              :selected-id="selectedNodeId"
              :highlight-ids="flowHighlightIds"
              @select="selectNode"
            />
            <p class="muted" style="margin-top: 14px;">
              流程圖只根據研究版本、任務、候選、封存與驗證投影建立；沒有後端資料的節點不補猜。
            </p>
          </template>
        </section>

        <section class="card">
          <h3>節點詳情</h3>
          <template v-if="selectedNode === null">
            <p class="muted">選擇流程圖節點後，這裡會顯示實際紀錄、產物與事件。</p>
          </template>
          <template v-else>
            <section v-if="activeFocusPanel !== null" class="focus-detail-workspace">
              <div class="focus-detail-head">
                <div>
                  <strong>{{ activeFocusLabel }}</strong>
                  <p class="muted">目前選中 {{ activeFocusIndex + 1 > 0 ? activeFocusIndex + 1 : 0 }} / {{ activeFocusPanel.items.length }}，可直接在這裡切換集合成員並檢視其詳情。</p>
                </div>
                <div class="actions wrap">
                  <button type="button" :disabled="activeFocusPanel.items.length < 2" @click="moveFocusSelection(-1)">上一筆</button>
                  <button type="button" :disabled="activeFocusPanel.items.length < 2" @click="moveFocusSelection(1)">下一筆</button>
                </div>
              </div>
              <div class="focus-detail-summary">
                <div class="row compact">
                  <span>命中成員</span>
                  <span class="tag">{{ activeFocusPanel.items.length }}</span>
                </div>
                <div class="row compact">
                  <span>總產物</span>
                  <span class="tag">{{ activeFocusPanel.totalArtifacts }}</span>
                </div>
                <div class="row compact">
                  <span>總事件</span>
                  <span class="tag">{{ activeFocusPanel.totalEvents }}</span>
                </div>
                <div class="row compact">
                  <span>完成 / 進行 / 待補</span>
                  <span class="tag">
                    {{ activeFocusPanel.toneCounts.OK }} / {{ activeFocusPanel.toneCounts.RUNNING + activeFocusPanel.toneCounts.PENDING }} / {{ activeFocusPanel.toneCounts.NEUTRAL + activeFocusPanel.toneCounts.FAILED }}
                  </span>
                </div>
              </div>
              <div class="focus-item-list">
                <button
                  v-for="item in activeFocusPanel.items"
                  :key="item.nodeId"
                  type="button"
                  class="focus-item-card"
                  :class="{ active: selectedNode.id === item.nodeId }"
                  @click="selectFocusPanelItem(item.nodeId)"
                >
                  <div class="focus-item-main">
                    <strong>{{ item.title }}</strong>
                    <span class="tag">{{ item.badge }}</span>
                  </div>
                  <span class="muted">{{ item.subtitle }}</span>
                  <div class="focus-item-meta">
                    <span class="mono">{{ item.primaryValue }}</span>
                    <span v-if="item.secondaryValue !== null" class="mono">{{ item.secondaryValue }}</span>
                  </div>
                  <div class="focus-item-meta">
                    <span>產物 {{ item.artifactCount }}</span>
                    <span>事件 {{ item.eventCount }}</span>
                  </div>
                </button>
              </div>

              <div v-if="activeFocusDigest !== null" class="focus-digest">
                <div class="focus-detail-head">
                  <div>
                    <strong>集合彙總</strong>
                    <p class="muted">彙整這組成員的產物與事件，並標示跨成員共用的項目；只呈現節點已揭露的內容。</p>
                  </div>
                  <div class="actions wrap">
                    <span class="tag">共用產物 {{ activeFocusDigest.sharedArtifactLabels.length }}</span>
                    <span class="tag">共用事件 {{ activeFocusDigest.sharedEventTypes.length }}</span>
                  </div>
                </div>

                <h4 class="digest-heading">成員分布</h4>
                <div class="focus-member-stats">
                  <button
                    v-for="stat in activeFocusDigest.memberStats"
                    :key="`digest-member:${stat.nodeId}`"
                    type="button"
                    class="focus-member-row"
                    :class="{ active: selectedNode.id === stat.nodeId }"
                    @click="selectFocusPanelItem(stat.nodeId)"
                  >
                    <span class="mono">{{ stat.value }}</span>
                    <span>{{ stat.title }}</span>
                    <span>產物 {{ stat.artifactCount }}</span>
                    <span>事件 {{ stat.eventCount }}</span>
                    <span class="muted mono">{{ stat.latestEventAt || '尚無事件' }}</span>
                  </button>
                </div>

                <h4 class="digest-heading">產物彙總</h4>
                <p v-if="activeFocusDigest.artifactGroups.length === 0" class="muted">此集合目前沒有可讀產物。</p>
                <div v-else class="artifact-groups">
                  <section
                    v-for="group in activeFocusDigest.artifactGroups"
                    :key="`digest-artifact:${group.label}`"
                    class="artifact-group"
                  >
                    <div class="row compact">
                      <span>{{ group.label }}</span>
                      <span class="tag" :class="group.shared ? 'good' : ''">
                        {{ group.items.length }} 項 / {{ group.memberCount }} 成員
                      </span>
                    </div>
                    <div class="artifact-list">
                      <RouterLink
                        v-for="item in group.items"
                        :key="`digest-artifact:${item.id}`"
                        :to="{ name: 'artifact', params: { id: item.id }, query: backQuery }"
                        class="artifact-link"
                      >
                        <span>{{ item.sourceValue }} · {{ item.sourceTitle }}</span>
                        <span class="mono">{{ item.id }}</span>
                      </RouterLink>
                    </div>
                  </section>
                </div>

                <h4 class="digest-heading">事件彙總</h4>
                <p v-if="activeFocusDigest.eventGroups.length === 0" class="muted">此集合目前沒有可讀事件。</p>
                <div v-else class="event-groups">
                  <section
                    v-for="group in activeFocusDigest.eventGroups"
                    :key="`digest-event:${group.type}`"
                    class="event-group"
                  >
                    <div class="row compact">
                      <span>{{ group.type }}</span>
                      <span class="tag" :class="group.shared ? 'good' : ''">
                        {{ group.count }} 筆 / {{ group.memberCount }} 成員
                      </span>
                    </div>
                    <div class="muted">最近時間 {{ group.latestAt || '未提供' }}</div>
                    <ol class="timeline compact-timeline">
                      <li v-for="event in group.recent" :key="event.event_id || `${group.type}:${event.sequence}`">
                        <span class="mono">#{{ event.sequence }}</span>
                        <span>{{ event.event_type }}</span>
                        <span class="mono">{{ event.occurred_at }}</span>
                        <span class="record-value">{{ summarizeNodePayload(event.payload) }}</span>
                      </li>
                    </ol>
                  </section>
                </div>
              </div>
            </section>
            <div class="row compact">
              <span>節點</span>
              <span>{{ selectedNode.title }}</span>
            </div>
            <div class="row compact">
              <span>類型</span>
              <span class="tag">{{ selectedNode.kind }}</span>
            </div>
            <div class="row compact">
              <span>狀態</span>
              <span class="tag">{{ selectedNode.badge }}</span>
            </div>
            <div class="row compact">
              <span>摘要</span>
              <span>{{ selectedNode.subtitle }}</span>
            </div>
            <div v-if="selectedNodeActions.length !== 0" class="actions wrap" style="margin: 14px 0;">
              <RouterLink
                v-for="action in selectedNodeActions"
                :key="`${selectedNode.id}:${action.label}`"
                :to="action.to"
              >
                <button type="button">{{ action.label }}</button>
              </RouterLink>
            </div>

            <h3 style="margin-top: 18px;">欄位紀錄</h3>
            <div v-if="selectedNode.records.length === 0" class="muted">此節點目前沒有可呈現的欄位。</div>
            <div v-else class="record-list">
              <div v-for="record in selectedNode.records" :key="`${selectedNode.id}:${record.label}`" class="row">
                <span>{{ record.label }}</span>
                <span class="record-value">{{ record.value }}</span>
              </div>
            </div>

            <h3 style="margin-top: 18px;">產物與事件</h3>
            <div class="row compact">
              <span>產物數</span>
              <span class="tag">{{ selectedNode.artifacts.length }}</span>
            </div>
            <div class="row compact">
              <span>事件數</span>
              <span class="tag">{{ selectedNode.events.length }}</span>
            </div>
            <div v-if="selectedNodeArtifactGroups.length !== 0" class="artifact-groups">
              <section
                v-for="group in selectedNodeArtifactGroups"
                :key="`${selectedNode.id}:${group.label}`"
                class="artifact-group"
              >
                <div class="row compact">
                  <span>{{ group.label }}</span>
                  <span class="tag">{{ group.items.length }}</span>
                </div>
                <div class="artifact-list">
                  <RouterLink
                    v-for="artifact in group.items"
                    :key="artifact.id"
                    :to="{ name: 'artifact', params: { id: artifact.id }, query: backQuery }"
                    class="artifact-link"
                  >
                    <span>{{ artifact.label }}</span>
                    <span class="mono">{{ artifact.id }}</span>
                  </RouterLink>
                </div>
              </section>
            </div>
            <p v-else class="muted">此節點目前沒有可讀產物。</p>

            <div v-if="selectedNodeEventGroups.length !== 0" class="event-groups">
              <section
                v-for="group in selectedNodeEventGroups"
                :key="`${selectedNode.id}:${group.type}`"
                class="event-group"
              >
                <div class="row compact">
                  <span>{{ group.type }}</span>
                  <span class="tag">{{ group.count }}</span>
                </div>
                <div class="muted">最近時間 {{ group.latestAt || '未提供' }}</div>
              </section>
            </div>
            <ol v-if="selectedNodeRecentEvents.length !== 0" class="timeline">
              <li
                v-for="event in selectedNodeRecentEvents"
                :key="event.event_id || `${event.stream_scope}:${event.sequence}`"
              >
                <span class="mono">#{{ event.sequence }}</span>
                <span>{{ event.event_type }}</span>
                <span class="mono">{{ event.occurred_at }}</span>
                <span class="record-value">{{ summarizeNodePayload(event.payload) }}</span>
              </li>
            </ol>
            <p v-else class="muted">此節點目前沒有可讀事件。</p>

            <div class="note" style="margin-top: 16px;">
              {{ blindEvaluation.detail }}
            </div>
          </template>
        </section>
      </div>

    <p v-if="error" class="bad" style="margin-top: 16px;">{{ error }}</p>
    <p v-if="notice" class="good" style="margin-top: 16px;">{{ notice }}</p>
  </section>
</template>

<style scoped>
.branch {
  width: 100%;
  text-align: left;
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 12px;
  background: #0e2036;
}

.branch.active {
  border-color: #2b6bd0;
  background: #153255;
}

.stage-list {
  margin-top: 18px;
}

.compact {
  padding: 10px 0;
}

.record-list {
  display: flex;
  flex-direction: column;
}

.flow-filters {
  margin-top: 12px;
}

.focus-workspace {
  border: 1px solid #26405f;
  border-radius: 12px;
  padding: 14px;
  margin-bottom: 12px;
  background: #0b1829;
}

.focus-workspace-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
  margin-bottom: 12px;
}

.focus-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.focus-card {
  border: 1px solid #26405f;
  border-radius: 12px;
  padding: 12px;
  background: #0d1d31;
}

.focus-missing {
  margin-top: 12px;
}

.focus-detail-workspace {
  border: 1px solid #26405f;
  border-radius: 12px;
  padding: 14px;
  margin-bottom: 16px;
  background: #0b1829;
}

.focus-detail-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
  margin-bottom: 12px;
}

.focus-detail-summary {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 14px;
  margin-bottom: 12px;
}

.focus-item-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.focus-item-card {
  display: flex;
  flex-direction: column;
  gap: 6px;
  align-items: flex-start;
  width: 100%;
  text-align: left;
  border: 1px solid #26405f;
  border-radius: 10px;
  padding: 12px;
  background: #0d1d31;
}

.focus-item-card.active {
  border-color: #3673c7;
  background: #132842;
}

.focus-digest {
  margin-top: 18px;
  border-top: 1px solid #26405f;
  padding-top: 14px;
}

.digest-heading {
  margin: 16px 0 8px;
}

.focus-member-stats {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.focus-member-row {
  display: grid;
  grid-template-columns: minmax(120px, 1fr) minmax(120px, 2fr) 90px 90px minmax(120px, 1.4fr);
  gap: 10px;
  align-items: center;
  width: 100%;
  text-align: left;
  border: 1px solid #26405f;
  border-radius: 10px;
  padding: 10px 12px;
  background: #0d1d31;
}

.focus-member-row.active {
  border-color: #3673c7;
  background: #132842;
}

.compact-timeline {
  grid-template-columns: 60px 130px 165px 1fr;
}

.focus-item-main,
.focus-item-meta {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  width: 100%;
}

.candidate-actions {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-bottom: 12px;
}

.candidate-action-link {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  border: 1px solid #26405f;
  border-radius: 10px;
  padding: 12px;
  background: #0d1d31;
}

.wrap {
  flex-wrap: wrap;
}

.record-value {
  max-width: 58%;
  text-align: right;
  overflow-wrap: anywhere;
}

.artifact-groups,
.event-groups {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-top: 14px;
}

.artifact-group,
.event-group {
  border: 1px solid #26405f;
  border-radius: 10px;
  padding: 12px;
  background: #0d1d31;
}

.artifact-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-top: 10px;
}

.artifact-link {
  display: flex;
  flex-direction: column;
  gap: 4px;
  border: 1px solid #26405f;
  border-radius: 10px;
  padding: 12px;
  background: #0d1d31;
}

.timeline {
  margin: 14px 0 0;
  padding-left: 18px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.timeline li {
  display: grid;
  grid-template-columns: 70px 140px 170px 1fr;
  gap: 10px;
}

@media (max-width: 1200px) {
  .focus-grid,
  .focus-detail-summary {
    grid-template-columns: 1fr;
  }
}
</style>
