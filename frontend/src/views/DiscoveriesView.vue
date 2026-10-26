<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import CandidateComparison from '../components/CandidateComparison.vue'
import { getEquationVersion, getFitRun } from '../api/candidates'
import { listResearchVersionRuns, listResearchVersions, listResearches } from '../api/research'
import { loadCandidateDetails, loadDiscoveriesCenter, type CandidateDetailBundle, type DiscoveriesCenter } from '../lib/discoveries'
import { describeError } from '../lib/messages'
import { readBackRef, withBackRef } from '../lib/navigationState'
import { readQueryList, readQueryString, replaceQueryState } from '../lib/queryState'
import { client } from '../lib/session'
import { listRunCandidates } from '../api/candidates'
import { buildDiscoveriesHandoffSummary } from '../lib/workflowHandoff'

const route = useRoute()
const router = useRouter()
const center = ref<DiscoveriesCenter | null>(null)
const loading = ref(false)
const detailsLoading = ref(false)
const error = ref('')
const selectedRunId = ref(readQueryString(route.query, 'run'))
const pinned = ref<string[]>(readQueryList(route.query, 'pins'))
const details = ref<CandidateDetailBundle>({ equations: {}, fits: {} })

const backRef = computed(() => readBackRef(route.query))
const selectedRun = computed(() => center.value?.searchRuns.find((row) => row.run.id === selectedRunId.value) ?? null)
const selectedCandidates = computed(() => selectedRun.value?.candidates ?? [])
const backQuery = computed<Record<string, string>>(() => withBackRef(route.fullPath))
const handoffSummary = computed(() => buildDiscoveriesHandoffSummary(selectedRun.value, pinned.value))
const workbenchCandidateQuery = computed<Record<string, string> | null>(() => {
  const summary = handoffSummary.value
  if (summary === null || summary.researchId === null || summary.versionId === null || summary.focusIds.length === 0) return null
  return withBackRef(route.fullPath, {
    version: summary.versionId,
    flowkind: 'CANDIDATE',
    focuscandidates: summary.focusIds.join(','),
    node: summary.focusIds[0] === undefined ? undefined : `candidate:${summary.focusIds[0]}`,
  })
})
const allCandidatesWorkbenchQuery = computed<Record<string, string> | null>(() => {
  const summary = handoffSummary.value
  if (summary === null || summary.researchId === null || summary.versionId === null || summary.candidates.length === 0) return null
  const ids = summary.candidates.map((candidate) => candidate.id)
  return withBackRef(route.fullPath, {
    version: summary.versionId,
    flowkind: 'CANDIDATE',
    focuscandidates: ids.join(','),
    node: ids[0] === undefined ? undefined : `candidate:${ids[0]}`,
  })
})
const previewCandidates = computed(() => {
  const summary = handoffSummary.value
  if (summary === null) return []
  const previewIds = summary.pinnedIds.length === 0 ? summary.suggestedPinnedIds : summary.pinnedIds
  return previewIds
    .map((id) => summary.candidates.find((candidate) => candidate.id === id))
    .filter((candidate): candidate is NonNullable<typeof candidate> => candidate !== undefined)
})

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    center.value = await loadDiscoveriesCenter({
      listResearches: (limit) => listResearches(client, limit),
      listResearchVersions: (researchId, limit) => listResearchVersions(client, researchId, limit),
      listResearchVersionRuns: (versionId, limit) => listResearchVersionRuns(client, versionId, limit),
      listRunCandidates: (runId, limit) => listRunCandidates(client, runId, { limit }),
      getEquationVersion: (id) => getEquationVersion(client, id),
      getFitRun: (id) => getFitRun(client, id),
    })
    const first = center.value.searchRuns[0]
    if (first !== undefined && !center.value.searchRuns.some((row) => row.run.id === selectedRunId.value)) {
      selectedRunId.value = first.run.id
    }
  } catch (cause) {
    center.value = null
    error.value = describeError(cause)
  } finally {
    loading.value = false
  }
}

function togglePinned(id: string): void {
  pinned.value = pinned.value.includes(id) ? pinned.value.filter((row) => row !== id) : [...pinned.value, id]
}

function pinSuggestedCandidates(): void {
  pinned.value = handoffSummary.value?.suggestedPinnedIds ?? []
}

function clearPinnedCandidates(): void {
  pinned.value = []
}

onMounted(load)

watch(selectedRunId, () => {
  pinned.value = []
})

watch(
  selectedRunId,
  async (value) => {
    await replaceQueryState(router, route, { run: value, pins: undefined })
  },
)

watch(
  pinned,
  async (value) => {
    await replaceQueryState(router, route, { pins: value.length === 0 ? undefined : value.join(',') })
  },
  { deep: true },
)

watch(
  () => route.query,
  () => {
    selectedRunId.value = readQueryString(route.query, 'run')
    pinned.value = readQueryList(route.query, 'pins')
  },
)

watch(
  [selectedRun, pinned],
  async ([run, ids]) => {
    if (run === null || ids.length === 0) return
    detailsLoading.value = true
    try {
      const rows = run.candidates.filter((candidate) => ids.includes(candidate.id))
      details.value = await loadCandidateDetails(
        {
          listResearches: async () => ({ items: [], next_cursor: null }),
          listResearchVersions: async () => ({ items: [], next_cursor: null }),
          listResearchVersionRuns: async () => ({ items: [], next_cursor: null }),
          listRunCandidates: async () => ({ items: [], next_cursor: null }),
          getEquationVersion: (id) => getEquationVersion(client, id),
          getFitRun: (id) => getFitRun(client, id),
        },
        rows,
        details.value,
      )
    } finally {
      detailsLoading.value = false
    }
  },
  { deep: true },
)
</script>

<template>
  <section>
    <div class="head">
      <div>
        <div class="eyebrow">發現 / WORKBENCH</div>
        <h1>發現中心</h1>
        <p class="muted">從最近 SEARCH 任務與候選分支，直接查看目前的假設生成與比較結果。</p>
      </div>
      <div class="actions">
        <button v-if="backRef !== ''" type="button" @click="router.push(backRef)">返回來源頁</button>
        <button type="button" @click="load">重新載入</button>
        <RouterLink :to="{ name: 'researches' }">
          <button type="button" class="primary">前往研究</button>
        </RouterLink>
      </div>
    </div>

    <p v-if="loading && center === null" class="muted">載入中…</p>
    <p v-else-if="error !== ''" class="bad">{{ error }}</p>
    <template v-else-if="center !== null">
      <div class="layout metric-grid">
        <section v-for="metric in center.metrics" :key="metric.label" class="card metric-card">
          <div class="eyebrow">{{ metric.label }}</div>
          <div class="metric-value" :class="metric.tone">{{ metric.value }}</div>
          <p>{{ metric.detail }}</p>
        </section>
      </div>

      <div class="layout discovery-grid">
        <section class="card">
          <h3>SEARCH 任務</h3>
          <p v-if="center.searchRuns.length === 0" class="muted">最近沒有可讀取的 SEARCH 任務。</p>
          <div v-else class="list-rows">
            <button
              v-for="row in center.searchRuns"
              :key="row.run.id"
              type="button"
              class="run-button"
              :class="{ active: selectedRunId === row.run.id }"
              @click="selectedRunId = row.run.id"
            >
              <div>
                <strong>{{ row.research?.name ?? '未命名研究' }}</strong>
                <div class="muted mono">{{ row.run.id }}</div>
                <div class="muted">{{ row.run.created_at }}</div>
              </div>
              <div class="stack">
                <span class="tag">{{ row.run.status }}</span>
                <span class="tag">{{ row.candidates.length }} 候選</span>
              </div>
            </button>
          </div>
        </section>

        <section class="card">
          <h3>候選比較</h3>
          <p v-if="selectedRun === null" class="muted">請先選擇一個 SEARCH 任務。</p>
          <template v-else>
            <section v-if="handoffSummary !== null" class="handoff-workspace">
              <div class="handoff-head">
                <div>
                  <strong>分支接力工作區</strong>
                  <p class="muted">在發現頁完成比較後，可直接把目前候選集合送回研究工作台，或恢復整個 SEARCH 分支。</p>
                </div>
                <span class="tag">{{ handoffSummary.totalCandidates }} 候選</span>
              </div>
              <div class="handoff-grid">
                <div class="row compact">
                  <span>研究</span>
                  <span>{{ handoffSummary.researchName }}</span>
                </div>
                <div class="row compact">
                  <span>研究版本</span>
                  <span class="mono">{{ handoffSummary.versionId ?? '未取得' }}</span>
                </div>
                <div class="row compact">
                  <span>已選比較</span>
                  <span class="tag">{{ handoffSummary.pinnedIds.length }}</span>
                </div>
                <div class="row compact">
                  <span>剩餘槽位</span>
                  <span class="tag">{{ handoffSummary.availableSlots }}</span>
                </div>
                <div class="row compact">
                  <span>已完成驗證</span>
                  <span class="tag">{{ handoffSummary.statusCounts.FINISHED }}</span>
                </div>
                <div class="row compact">
                  <span>驗證進行中</span>
                  <span class="tag">{{ handoffSummary.statusCounts.PENDING }}</span>
                </div>
              </div>
              <div class="actions wrap" style="margin: 12px 0;">
                <button
                  type="button"
                  :disabled="handoffSummary.suggestedPinnedIds.length === 0 || handoffSummary.pinnedIds.length === handoffSummary.suggestedPinnedIds.length"
                  @click="pinSuggestedCandidates"
                >
                  挑選前四候選
                </button>
                <button type="button" :disabled="pinned.length === 0" @click="clearPinnedCandidates">清空比較</button>
                <RouterLink
                  v-if="handoffSummary.researchId !== null && workbenchCandidateQuery !== null"
                  :to="{ name: 'researches', params: { id: handoffSummary.researchId }, query: workbenchCandidateQuery }"
                >
                  <button type="button">用目前比較集打開工作台</button>
                </RouterLink>
                <RouterLink
                  v-if="handoffSummary.researchId !== null && allCandidatesWorkbenchQuery !== null && handoffSummary.focusIds.length !== handoffSummary.totalCandidates"
                  :to="{ name: 'researches', params: { id: handoffSummary.researchId }, query: allCandidatesWorkbenchQuery }"
                >
                  <button type="button">在工作台看全部候選</button>
                </RouterLink>
              </div>
              <div v-if="previewCandidates.length !== 0" class="preview-list">
                <div v-for="candidate in previewCandidates" :key="candidate.id" class="preview-card">
                  <strong>#{{ candidate.developmentRank ?? '—' }}</strong>
                  <span>{{ candidate.source }}</span>
                  <span class="tag">{{ candidate.validationStatus }}</span>
                  <span class="mono">{{ candidate.id }}</span>
                </div>
              </div>
            </section>
            <div class="row compact">
              <span>研究版本</span>
              <span class="mono">{{ selectedRun.version?.id ?? '未取得' }}</span>
            </div>
            <div class="row compact">
              <span>研究入口</span>
              <RouterLink
                v-if="selectedRun.research !== null"
                :to="{
                  name: 'researches',
                  params: { id: selectedRun.research.id },
                  query: workbenchCandidateQuery ?? withBackRef(route.fullPath, { version: selectedRun.version?.id ?? '' }),
                }"
              >
                <span class="tag">打開工作台</span>
              </RouterLink>
              <span v-else class="muted">未取得</span>
            </div>
            <div class="actions" style="margin-bottom: 14px;">
              <RouterLink v-if="selectedRun !== null" :to="{ name: 'run', params: { id: selectedRun.run.id }, query: backQuery }">
                <button type="button">查看任務詳情</button>
              </RouterLink>
            </div>
            <CandidateComparison
              :candidates="selectedCandidates"
              :pinned="pinned"
              :equations="details.equations"
              :fits="details.fits"
              :details-loading="detailsLoading"
              :run-id="selectedRun.run.id"
              @toggle="togglePinned"
            />
          </template>
        </section>

        <section class="card">
          <h3>最近研究版本</h3>
          <p v-if="center.recentVersions.length === 0" class="muted">最近沒有研究版本。</p>
          <div v-else class="list-rows">
            <RouterLink
              v-for="version in center.recentVersions"
              :key="version.id"
              :to="{ name: 'researches', params: { id: version.research_id }, query: { version: version.id } }"
              class="module-link"
            >
              <div>
                <strong>{{ version.purpose }} / {{ version.status }}</strong>
                <div class="muted mono">{{ version.id }}</div>
              </div>
              <span class="tag">{{ version.frozen_submission_ids.length }} 凍結</span>
            </RouterLink>
          </div>
          <div class="note" style="margin-top: 16px;">
            發現頁目前聚焦最近 SEARCH 與候選比較；更完整的全域公式庫與多版本關聯圖，會再往下接。
          </div>
        </section>
      </div>
    </template>
  </section>
</template>

<style scoped>
.metric-grid {
  grid-template-columns: repeat(4, minmax(0, 1fr));
  margin-bottom: 16px;
}

.metric-card {
  min-height: 158px;
}

.metric-value {
  font-size: 30px;
  font-weight: 700;
  margin: 10px 0 8px;
}

.discovery-grid {
  grid-template-columns: 320px minmax(0, 1.6fr) 340px;
}

.list-rows {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.run-button,
.module-link {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  border: 1px solid #27405d;
  border-radius: 10px;
  padding: 12px;
  background: #0e1e31;
}

.run-button {
  text-align: left;
  width: 100%;
}

.run-button.active {
  border-color: #3673c7;
  background: #132842;
}

.stack {
  display: flex;
  flex-direction: column;
  gap: 6px;
  align-items: flex-end;
}

.compact {
  padding: 10px 0;
}

.handoff-workspace {
  border: 1px solid #27405d;
  border-radius: 12px;
  padding: 14px;
  margin-bottom: 14px;
  background: #0b1829;
}

.handoff-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
  margin-bottom: 12px;
}

.handoff-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 16px;
}

.preview-list {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 10px;
}

.preview-card {
  display: flex;
  flex-direction: column;
  gap: 6px;
  border: 1px solid #27405d;
  border-radius: 10px;
  padding: 12px;
  background: #0e1e31;
}

@media (max-width: 1200px) {
  .metric-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .discovery-grid {
    grid-template-columns: 1fr;
  }

  .handoff-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 900px) {
  .metric-grid {
    grid-template-columns: 1fr;
  }
}
</style>
