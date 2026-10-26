<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import CandidateComparison from '../components/CandidateComparison.vue'
import { getEquationVersion, getFitRun } from '../api/candidates'
import { listResearchVersionRuns, listResearchVersions, listResearches } from '../api/research'
import { loadCandidateDetails, loadDiscoveriesCenter, type CandidateDetailBundle, type DiscoveriesCenter } from '../lib/discoveries'
import { describeError } from '../lib/messages'
import { readQueryList, readQueryString, replaceQueryState } from '../lib/queryState'
import { client } from '../lib/session'
import { listRunCandidates } from '../api/candidates'

const route = useRoute()
const router = useRouter()
const center = ref<DiscoveriesCenter | null>(null)
const loading = ref(false)
const detailsLoading = ref(false)
const error = ref('')
const selectedRunId = ref(readQueryString(route.query, 'run'))
const pinned = ref<string[]>(readQueryList(route.query, 'pins'))
const details = ref<CandidateDetailBundle>({ equations: {}, fits: {} })

const selectedRun = computed(() => center.value?.searchRuns.find((row) => row.run.id === selectedRunId.value) ?? null)
const selectedCandidates = computed(() => selectedRun.value?.candidates ?? [])

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
            <div class="row compact">
              <span>研究版本</span>
              <span class="mono">{{ selectedRun.version?.id ?? '未取得' }}</span>
            </div>
            <div class="row compact">
              <span>研究入口</span>
              <RouterLink
                v-if="selectedRun.research !== null"
                :to="{ name: 'researches', params: { id: selectedRun.research.id }, query: { version: selectedRun.version?.id ?? '' } }"
              >
                <span class="tag">打開工作台</span>
              </RouterLink>
              <span v-else class="muted">未取得</span>
            </div>
            <CandidateComparison
              :candidates="selectedCandidates"
              :pinned="pinned"
              :equations="details.equations"
              :fits="details.fits"
              :details-loading="detailsLoading"
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

@media (max-width: 1200px) {
  .metric-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .discovery-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 900px) {
  .metric-grid {
    grid-template-columns: 1fr;
  }
}
</style>
