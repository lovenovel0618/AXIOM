<script setup lang="ts">
/**
 * 公式比較（SSOT SCREEN 19）：模型誤差、複雜度與泛化比較。
 *
 * 只呈現後端已揭露的欄位：公式 AST、擬合參數、驗證狀態與任務計數。
 * 樣本外誤差（final_test）在凍結前不揭露，一律標示「尚未評估」，不以推測值或 0 代替。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import CandidateComparison from '../components/CandidateComparison.vue'
import DiscoveryTabs from '../components/DiscoveryTabs.vue'
import { MAX_COMPARISON, getEquationVersion, getFitRun, listRunCandidates } from '../api/candidates'
import { listResearchVersionRuns, listResearchVersions, listResearches } from '../api/research'
import {
  buildComparisonContextRows,
  buildDiscoveryCatalogCsv,
  buildDiscoveryCatalogRows,
  buildFairComparisonRows,
  DISCOVERY_UNKNOWN,
  loadCandidateDetails,
  VALIDATION_STATUS_LABELS,
  type CandidateDetailBundle,
  type DiscoveryCatalogRow,
} from '../lib/discoveries'
import { readBackRef, withBackRef } from '../lib/navigationState'
import { readQueryList, readQueryString, replaceQueryState } from '../lib/queryState'
import { client } from '../lib/session'
import { useDiscoveryCatalog } from '../lib/useDiscoveryCatalog'

const route = useRoute()
const router = useRouter()
const { center, equations, loading, error, load } = useDiscoveryCatalog()

const selectedRunId = ref(readQueryString(route.query, 'run'))
const pinned = ref<string[]>(readQueryList(route.query, 'pins'))
const details = ref<CandidateDetailBundle>({ equations: {}, fits: {} })
const detailsLoading = ref(false)
const notice = ref('')

const backRef = computed(() => readBackRef(route.query))
const unknown = DISCOVERY_UNKNOWN

const selectedRun = computed(() => center.value?.searchRuns.find((row) => row.run.id === selectedRunId.value) ?? null)
const selectedCandidates = computed(() => selectedRun.value?.candidates ?? [])
const catalogRows = computed<DiscoveryCatalogRow[]>(() =>
  center.value === null ? [] : buildDiscoveryCatalogRows(center.value, equations.value),
)
const pinnedRows = computed<DiscoveryCatalogRow[]>(() => {
  const ids = new Set(selectedCandidates.value.map((row) => row.id))
  return pinned.value
    .map((id) => catalogRows.value.find((row) => row.candidateId === id && ids.has(row.candidateId)))
    .filter((row): row is DiscoveryCatalogRow => row !== undefined)
})
const mergedEquations = computed(() => ({ ...equations.value, ...details.value.equations }))
const mergedFits = computed(() => ({ ...details.value.fits }))
const contextRows = computed(() => buildComparisonContextRows(selectedRun.value?.version ?? null))
const policyRows = computed(() => buildFairComparisonRows(selectedRun.value?.version ?? null))

function text(value: string | number | null): string {
  return value === null ? unknown : String(value)
}

function statusTone(status: DiscoveryCatalogRow['validationStatus']): string {
  if (status === 'FINISHED') return 'good'
  if (status === 'INVALID') return 'bad'
  if (status === 'PENDING') return 'warn'
  return ''
}

function togglePinned(id: string): void {
  pinned.value = pinned.value.includes(id) ? pinned.value.filter((row) => row !== id) : [...pinned.value, id]
}

function download(name: string, content: string): void {
  const blob = new Blob([content], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = name
  anchor.click()
  URL.revokeObjectURL(url)
}

function exportComparison(): void {
  if (pinnedRows.value.length === 0) return
  notice.value = `已匯出目前並排的 ${String(pinnedRows.value.length)} 條候選（僅含後端已揭露欄位）。`
  download('axiom-discovery-comparison.csv', buildDiscoveryCatalogCsv(pinnedRows.value))
}

async function loadPinnedDetails(): Promise<void> {
  const run = selectedRun.value
  if (run === null || pinned.value.length === 0) return
  detailsLoading.value = true
  try {
    const rows = run.candidates.filter((candidate) => pinned.value.includes(candidate.id))
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
}

onMounted(async () => {
  await load()
  if (selectedRunId.value === '') selectedRunId.value = center.value?.searchRuns[0]?.run.id ?? ''
  await loadPinnedDetails()
})

watch(selectedRunId, async (value) => {
  pinned.value = []
  details.value = { equations: {}, fits: {} }
  await replaceQueryState(router, route, { run: value === '' ? undefined : value, pins: undefined })
})

watch(pinned, async (value) => {
  await replaceQueryState(router, route, { pins: value.length === 0 ? undefined : value.join(',') })
})

watch(
  [pinned, selectedRun],
  async () => {
    await loadPinnedDetails()
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
</script>

<template>
  <section>
    <div class="head">
      <div>
        <div class="eyebrow">發現 / SCREEN 19</div>
        <h1>公式比較</h1>
        <p class="muted">模型誤差、複雜度與泛化比較 · 專屬任務畫面設計</p>
      </div>
      <div class="actions">
        <button v-if="backRef !== ''" type="button" @click="router.push(backRef)">返回來源頁</button>
        <button type="button" @click="load">重新載入</button>
        <RouterLink :to="{ name: 'discoveries' }">
          <button type="button" class="primary">前往候選公式庫</button>
        </RouterLink>
      </div>
    </div>

    <DiscoveryTabs />

    <p v-if="loading && center === null" class="muted">載入中…</p>
    <p v-else-if="error !== ''" class="bad">{{ error }}</p>
    <template v-else-if="center !== null">
      <p v-if="center.searchRuns.length === 0" class="muted">
        目前沒有可讀取的 SEARCH 任務。請先建立研究版本並啟動公式搜尋，候選才會出現在這裡。
      </p>
      <template v-else>
        <div class="layout compare-grid">
          <section class="card">
            <h3>SEARCH 任務</h3>
            <div class="list-rows">
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
                </div>
                <div class="stack">
                  <span class="tag">{{ row.run.status }}</span>
                  <span class="tag">{{ row.candidates.length }} 候選</span>
                </div>
              </button>
            </div>
          </section>

          <section class="card">
            <h3>公平比較前提</h3>
            <p v-if="selectedRun === null" class="muted">請先選擇一個 SEARCH 任務。</p>
            <template v-else>
              <div class="row compact">
                <span>研究版本</span>
                <span class="mono">{{ selectedRun.version?.id ?? unknown }}</span>
              </div>
              <p v-if="contextRows.length === 0" class="muted">研究版本未載入，無法確認切分前提。</p>
              <template v-else>
                <div class="row compact"><span>資料集版本</span><span class="mono">{{ contextRows[0]?.value }}</span></div>
                <div class="row compact"><span>切分方式</span><span class="tag">{{ contextRows[1]?.value }}</span></div>
                <div class="row compact">
                  <span>切分列數（fit / development / final_test）</span>
                  <span class="tag">{{ contextRows[2]?.value }} / {{ contextRows[3]?.value }} / {{ contextRows[4]?.value }}</span>
                </div>
                <div class="row compact"><span>封存 final_test</span><span class="tag">{{ contextRows[5]?.value }}</span></div>
                <div class="row compact"><span>列集合雜湊</span><span class="mono record-value">{{ contextRows[6]?.value }}</span></div>
                <div class="row compact"><span>切分器版本</span><span>{{ contextRows[7]?.value }}</span></div>
              </template>

              <h3 style="margin-top: 18px;">評估政策</h3>
              <p v-if="policyRows.length === 0" class="muted">未載入評估政策。</p>
              <template v-else>
                <div v-for="fact in policyRows" :key="fact.label" class="row compact">
                  <span>{{ fact.label }}</span>
                  <span class="record-value mono">{{ fact.value }}</span>
                </div>
              </template>
              <div class="note" style="margin-top: 12px;">
                只有切分、指標版本與評估政策一致時，兩條候選的差異才可歸因於模型本身；不一致的前提不得相互比較。
              </div>
            </template>
          </section>
        </div>

        <section class="card" style="margin-top: 16px;">
          <h3>候選並排比較</h3>
          <p v-if="selectedRun === null" class="muted">請先選擇一個 SEARCH 任務。</p>
          <CandidateComparison
            v-else
            :candidates="selectedCandidates"
            :pinned="pinned"
            :equations="mergedEquations"
            :fits="mergedFits"
            :details-loading="detailsLoading"
            :run-id="selectedRun.run.id"
            @toggle="togglePinned"
          />
        </section>

        <section class="card" style="margin-top: 16px;">
          <h3>誤差與泛化指標對照</h3>
          <p class="muted">
            同屏最多並排 {{ MAX_COMPARISON }} 條候選；樣本外誤差在凍結前不揭露，泛化判定需等最終評估完成。
          </p>
          <p v-if="pinnedRows.length === 0" class="muted">請先在上方勾選候選以建立對照表。</p>
          <div v-else class="scroll">
            <table class="matrix">
              <thead>
                <tr>
                  <th scope="col">指標</th>
                  <th v-for="row in pinnedRows" :key="row.candidateId" scope="col">
                    #{{ row.developmentRank ?? unknown }}
                    <span class="mono block">{{ row.candidateId }}</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <th scope="row">候選公式</th>
                  <td v-for="row in pinnedRows" :key="row.candidateId" class="mono formula">{{ row.formula ?? unknown }}</td>
                </tr>
                <tr>
                  <th scope="row">來源</th>
                  <td v-for="row in pinnedRows" :key="row.candidateId">{{ row.source }}</td>
                </tr>
                <tr>
                  <th scope="row">模型複雜度</th>
                  <td v-for="row in pinnedRows" :key="row.candidateId">{{ text(row.complexity) }}</td>
                </tr>
                <tr>
                  <th scope="row">變數 / 參數數</th>
                  <td v-for="row in pinnedRows" :key="row.candidateId">{{ text(row.variableCount) }} / {{ text(row.parameterCount) }}</td>
                </tr>
                <tr>
                  <th scope="row">定義域</th>
                  <td v-for="row in pinnedRows" :key="row.candidateId" class="mono">{{ text(row.domain) }}</td>
                </tr>
                <tr>
                  <th scope="row">擬合任務數</th>
                  <td v-for="row in pinnedRows" :key="row.candidateId">{{ row.fitRunCount }}</td>
                </tr>
                <tr>
                  <th scope="row">驗證任務數</th>
                  <td v-for="row in pinnedRows" :key="row.candidateId">{{ row.validationRunCount }}</td>
                </tr>
                <tr>
                  <th scope="row">驗證狀態</th>
                  <td v-for="row in pinnedRows" :key="row.candidateId">
                    <span class="tag" :class="statusTone(row.validationStatus)">
                      {{ VALIDATION_STATUS_LABELS[row.validationStatus] }}
                    </span>
                  </td>
                </tr>
                <tr>
                  <th scope="row">樣本外誤差（final_test）</th>
                  <td v-for="row in pinnedRows" :key="row.candidateId" class="muted">尚未評估（凍結前不揭露）</td>
                </tr>
                <tr>
                  <th scope="row">泛化判定</th>
                  <td v-for="row in pinnedRows" :key="row.candidateId" class="muted">{{ unknown }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <div class="actions" style="margin-top: 12px;">
            <button type="button" :disabled="pinnedRows.length === 0" @click="exportComparison">匯出目前比較清單</button>
            <RouterLink
              v-if="selectedRun !== null"
              :to="{ name: 'run', params: { id: selectedRun.run.id }, query: withBackRef(route.fullPath) }"
            >
              <button type="button">查看 SEARCH 任務</button>
            </RouterLink>
          </div>
          <p v-if="notice !== ''" class="note">{{ notice }}</p>
        </section>
      </template>
    </template>
  </section>
</template>

<style scoped>
.compare-grid {
  grid-template-columns: 1fr 1.4fr;
}

.list-rows {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.run-button {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  border: 1px solid #27405d;
  border-radius: 10px;
  padding: 12px;
  background: #0e1e31;
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
  padding: 8px 0;
}

.record-value {
  max-width: 62%;
  text-align: right;
  overflow-wrap: anywhere;
}

.scroll {
  overflow-x: auto;
}

.matrix {
  border-collapse: collapse;
  width: 100%;
  min-width: 44rem;
}

.matrix th,
.matrix td {
  border: 1px solid var(--border);
  padding: 10px 12px;
  vertical-align: top;
  text-align: left;
}

.matrix thead th {
  background: var(--surface-muted);
}

.matrix tbody th {
  color: var(--text-muted);
  white-space: nowrap;
}

.block {
  display: block;
}

.formula {
  white-space: pre-wrap;
}

@media (max-width: 1200px) {
  .compare-grid {
    grid-template-columns: 1fr;
  }
}
</style>
