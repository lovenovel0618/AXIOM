<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { getArtifactContent } from '../api/artifacts'
import { getFinalEvaluation, getValidationRun } from '../api/evaluations'
import {
  createResearch,
  createSearchRun,
  fetchResearchEventBatch,
  getResearchVersion,
  listResearchVersionRuns,
  listResearchVersions,
  listResearches,
  type Research,
  type ResearchVersion,
  type ResearchVersionStatus,
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
  buildNodeActionLinks,
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
const researchStatuses = ref<Record<string, ResearchVersionStatus | 'NONE'>>({})
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
const submitting = ref(false)
const startingSearch = ref(false)
const error = ref('')
const notice = ref('')
const search = ref('')
const statusFilter = ref<'ALL' | ResearchVersionStatus | 'NONE'>('ALL')
const name = ref('')
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

const mode = computed<'list' | 'create' | 'workbench'>(() => {
  const id = typeof route.params.id === 'string' ? route.params.id : ''
  if (id === 'new') return 'create'
  if (id !== '') return 'workbench'
  return 'list'
})

const filteredResearches = computed<Research[]>(() => {
  const keyword = search.value.trim().toLowerCase()
  return researches.value.filter((row) => {
    const matched =
      keyword === '' || row.name.toLowerCase().includes(keyword) || row.id.toLowerCase().includes(keyword)
    if (!matched) return false
    if (statusFilter.value === 'ALL') return true
    return researchStatuses.value[row.id] === statusFilter.value
  })
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
    : buildNodeActionLinks(selectedNode.value, (extra) => withBackRef(route.fullPath, extra)),
)
const visibleCandidateCollections = computed(() =>
  displayGraph.value === null ? [] : collectCandidateCollectionLinks(displayGraph.value.nodes),
)
const visibleSubmissionCollection = computed(() =>
  displayGraph.value === null ? null : collectSubmissionCollectionLink(displayGraph.value.nodes),
)
const focusedCandidateNodeIds = computed(() =>
  displayGraph.value === null ? [] : findNodeIdsByRecordValues(displayGraph.value.nodes, '候選識別碼', focusCandidateIds.value),
)
const focusedSubmissionNodeIds = computed(() =>
  displayGraph.value === null ? [] : findNodeIdsByRecordValues(displayGraph.value.nodes, '提交識別碼', focusSubmissionIds.value),
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

async function loadResearchStatuses(items: Research[]): Promise<void> {
  const next: Record<string, ResearchVersionStatus | 'NONE'> = {}
  await Promise.all(
    items.map(async (row) => {
      try {
        const page = await listResearchVersions(client, row.id, 1)
        next[row.id] = page.items[0]?.status ?? 'NONE'
      } catch {
        next[row.id] = 'NONE'
      }
    }),
  )
  researchStatuses.value = next
}

async function loadResearches(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const page = await listResearches(client)
    researches.value = page.items
    await loadResearchStatuses(page.items)
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

async function submitResearch(): Promise<void> {
  if (name.value.trim() === '' || submitting.value) return
  submitting.value = true
  error.value = ''
  notice.value = ''
  try {
    const created = await createResearch(client, name.value.trim())
    notice.value = `已建立研究「${created.name}」。`
    name.value = ''
    await loadResearches()
    await router.push({ name: 'researches', params: { id: created.id } })
  } catch (cause) {
    error.value = describeError(cause)
  } finally {
    submitting.value = false
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

function openResearch(row: Research): void {
  void router.push({ name: 'researches', params: { id: row.id } })
}

function selectNode(id: string): void {
  selectedNodeId.value = id
}

function summarizeNodePayload(payload: Record<string, unknown>): string {
  return summarizeEventPayload(payload)
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
    if (mode.value !== 'workbench') return
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
    if (mode.value !== 'workbench') return
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
    if (mode.value !== 'workbench') return
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
        <div class="eyebrow">研究 / SCREEN</div>
        <h1>{{ mode === 'list' ? '研究清單' : mode === 'create' ? '新建研究' : '研究工作台' }}</h1>
        <p class="muted">
          {{
            mode === 'list'
              ? '查找、篩選與管理研究入口。'
              : mode === 'create'
                ? '建立真正的 Research 容器，後續由資料集分析銜接版本。'
                : '以真實研究版本、任務、候選與事件重建工作流。'
          }}
        </p>
      </div>
      <div class="actions">
        <button v-if="backRef !== ''" type="button" @click="router.push(backRef)">返回來源頁</button>
        <button type="button" @click="loadResearches">重新載入</button>
        <button
          v-if="mode === 'workbench'"
          type="button"
          :disabled="selectedVersionId === '' || refreshingWorkbench"
          @click="loadWorkbench(selectedVersionId)"
        >
          {{ refreshingWorkbench ? '同步中…' : '同步工作台' }}
        </button>
        <button
          v-if="mode === 'workbench'"
          type="button"
          class="primary"
          :disabled="workbenchVersion === null || startingSearch"
          @click="startSearch"
        >
          {{ startingSearch ? '建立中…' : '啟動 SEARCH' }}
        </button>
        <button
          v-if="mode !== 'create'"
          type="button"
          class="primary"
          @click="router.push({ name: 'researches', params: { id: 'new' } })"
        >
          新增 / 執行
        </button>
        <button v-else type="button" @click="router.push({ name: 'researches' })">返回</button>
      </div>
    </div>

    <template v-if="mode === 'list'">
      <div class="layout">
        <section class="card">
          <h3>搜尋與篩選</h3>
          <div class="formgrid">
            <div class="field">
              <label>搜尋名稱 / ID</label>
              <input v-model="search" placeholder="請輸入搜尋名稱 / ID">
            </div>
            <div class="field">
              <label>最新版本狀態</label>
              <select v-model="statusFilter">
                <option value="ALL">全部</option>
                <option value="NONE">尚無版本</option>
                <option value="DRAFT">草稿</option>
                <option value="VALIDATING">預檢中</option>
                <option value="READY">就緒</option>
                <option value="QUEUED">排隊中</option>
                <option value="RUNNING">執行中</option>
                <option value="FAILED">失敗</option>
                <option value="CANCELLED">已取消</option>
              </select>
            </div>
          </div>
          <div class="actions">
            <button type="button" class="primary" @click="router.push({ name: 'researches', params: { id: 'new' } })">
              建立新項目
            </button>
            <button type="button" @click="search = ''; statusFilter = 'ALL'">清空篩選</button>
          </div>
        </section>

        <section class="card">
          <h3>項目清單</h3>
          <p v-if="loading" class="muted">載入中…</p>
          <p v-else-if="filteredResearches.length === 0" class="muted">目前沒有符合條件的研究。</p>
          <table v-else>
            <thead>
              <tr>
                <th>編號</th>
                <th>名稱</th>
                <th>最新狀態</th>
                <th>建立時間</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in filteredResearches" :key="row.id">
                <td class="mono">{{ row.id }}</td>
                <td>{{ row.name }}</td>
                <td><span class="tag">{{ researchStatuses[row.id] ?? 'NONE' }}</span></td>
                <td>{{ row.created_at }}</td>
                <td><button type="button" @click="openResearch(row)">進入工作台</button></td>
              </tr>
            </tbody>
          </table>
        </section>
      </div>
    </template>

    <template v-else-if="mode === 'create'">
      <section class="card">
        <h3>建立研究容器</h3>
        <div class="formgrid">
          <div class="field">
            <label>研究名稱</label>
            <input v-model="name" placeholder="例如：週期結構研究">
          </div>
          <div class="field">
            <label>研究類型</label>
            <select disabled>
              <option>自動研究</option>
            </select>
          </div>
          <div class="field">
            <label>研究目標</label>
            <input placeholder="建立版本時補入" disabled>
          </div>
          <div class="field">
            <label>數據來源</label>
            <input placeholder="由資料集分析流程自動接入" disabled>
          </div>
        </div>
        <div class="note">
          這一頁只建立 Research 容器。研究版本、語意、切分、預算與 PROFILE/SEARCH 任務，都由後續工作流依真實資料接續。
        </div>
        <div class="actions" style="margin-top: 16px;">
          <button type="button" @click="router.push({ name: 'researches' })">取消</button>
          <button type="button" class="primary" :disabled="submitting || name.trim() === ''" @click="submitResearch">
            建立研究
          </button>
        </div>
      </section>
    </template>

    <template v-else>
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
            <div v-if="focusCandidateIds.length !== 0" class="note" style="margin-bottom: 12px;">
              目前高亮從發現頁帶回的 {{ focusedCandidateNodeIds.length }} / {{ focusCandidateIds.length }} 個候選節點。
            </div>
            <div v-if="focusSubmissionIds.length !== 0" class="note" style="margin-bottom: 12px;">
              目前高亮從驗證頁帶回的 {{ focusedSubmissionNodeIds.length }} / {{ focusSubmissionIds.length }} 個提交節點。
            </div>
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
    </template>

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
</style>
