<script setup lang="ts">
/**
 * 逆向推導（SSOT SCREEN 24）：參數恢復、逆問題及多解集合。
 *
 * 逐 SEARCH 任務讀出其候選、公式 AST 與擬合參數，整理每個參數在多次擬合中的觀測值與相異值數。
 * 後端沒有可識別性檢查、逆問題求解與觀測量／未知參數端點，這些欄位一律固定顯示「未取得」。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import VerificationTabs from '../components/VerificationTabs.vue'
import { DISCOVERY_UNKNOWN, VALIDATION_STATUS_LABELS } from '../lib/discoveries'
import { readBackRef, withBackRef } from '../lib/navigationState'
import { readQueryString, replaceQueryState } from '../lib/queryState'
import { useInverseDerivation } from '../lib/useInverseDerivation'
import {
  IDENTIFIABILITY_UNKNOWN,
  INVERSE_OBSERVATION_UNKNOWN,
  INVERSE_SOLVER_UNKNOWN,
  type InverseDerivation,
  type InverseSolutionRow,
} from '../lib/verificationInverse'

const route = useRoute()
const router = useRouter()
const { center, loading, error, load, loadRunDetails, derive } = useInverseDerivation()

const runId = ref(readQueryString(route.query, 'run'))
const candidateId = ref(readQueryString(route.query, 'candidate'))

const unknown = DISCOVERY_UNKNOWN
const searchRuns = computed(() => center.value?.searchRuns ?? [])
const selectedRun = computed(() => searchRuns.value.find((entry) => entry.run.id === runId.value) ?? null)
const derivation = computed<InverseDerivation>(() => derive(selectedRun.value))
const solutions = computed<InverseSolutionRow[]>(() => derivation.value.solutions)
const selectedSolution = computed<InverseSolutionRow | null>(
  () => solutions.value.find((row) => row.candidateId === candidateId.value) ?? null,
)
const backRef = computed(() => readBackRef(route.query))
const multiValuedCount = computed(() => solutions.value.filter((row) => row.multiValuedParameters.length > 0).length)
const fitCount = computed(() => solutions.value.reduce((total, row) => total + row.fitCount, 0))
const workbenchQuery = computed<Record<string, string> | null>(() => {
  const entry = selectedRun.value
  if (entry === null || entry.version === null) return null
  return withBackRef(route.fullPath, { version: entry.version.id, flowkind: 'CANDIDATE' })
})

function statusTone(row: InverseSolutionRow): string {
  if (row.validationStatus === 'FINISHED') return 'good'
  if (row.validationStatus === 'INVALID') return 'bad'
  if (row.validationStatus === 'PENDING') return 'warn'
  return ''
}

function selectRun(id: string): void {
  runId.value = id
  candidateId.value = ''
}

function selectSolution(row: InverseSolutionRow): void {
  candidateId.value = row.candidateId
}

onMounted(async () => {
  await load()
  if (runId.value === '' && searchRuns.value.length > 0) runId.value = searchRuns.value[0]?.run.id ?? ''
  if (runId.value !== '' && !searchRuns.value.some((entry) => entry.run.id === runId.value)) runId.value = searchRuns.value[0]?.run.id ?? ''
  await loadRunDetails(selectedRun.value)
  if (candidateId.value === '' && solutions.value.length > 0) candidateId.value = solutions.value[0]?.candidateId ?? ''
})

watch(runId, async (value) => {
  await replaceQueryState(router, route, { run: value === '' ? undefined : value, candidate: undefined })
  candidateId.value = ''
  await loadRunDetails(selectedRun.value)
})

watch(candidateId, async (value) => {
  await replaceQueryState(router, route, { candidate: value === '' ? undefined : value })
})

watch(
  () => route.query.run,
  () => {
    runId.value = readQueryString(route.query, 'run')
  },
)

watch(
  () => route.query.candidate,
  () => {
    candidateId.value = readQueryString(route.query, 'candidate')
  },
)

watch(solutions, (value) => {
  if (value.length === 0) return
  if (value.some((row) => row.candidateId === candidateId.value)) return
  candidateId.value = value[0]?.candidateId ?? ''
})
</script>

<template>
  <section>
    <VerificationTabs />

    <div class="head">
      <div>
        <div class="eyebrow">驗證 / 第 24 頁</div>
        <h1>逆向推導</h1>
        <p class="muted">專屬任務畫面設計｜參數恢復、逆問題及多解集合：由候選公式與擬合參數整理恢復結果與多解跡象，不推測解集合。</p>
      </div>
      <div class="actions">
        <button v-if="backRef !== ''" type="button" @click="router.push(backRef)">返回來源頁</button>
        <button type="button" :disabled="runId === ''" @click="loadRunDetails(selectedRun)">重新載入擬合</button>
        <RouterLink :to="{ name: 'verification' }">
          <button type="button" class="primary">前往驗證中心</button>
        </RouterLink>
      </div>
    </div>

    <p v-if="loading && center === null" class="muted">載入中…</p>
    <p v-else-if="error !== ''" class="bad">{{ error }}</p>
    <template v-else>
      <div class="layout metric-grid">
        <section class="card metric-card">
          <div class="eyebrow">SEARCH 任務</div>
          <div class="metric-value" :class="searchRuns.length > 0 ? 'good' : 'warn'">{{ searchRuns.length }}</div>
          <p>最近研究版本中可讀取的 SEARCH 任務數量。</p>
        </section>
        <section class="card metric-card">
          <div class="eyebrow">候選解</div>
          <div class="metric-value">{{ solutions.length }}</div>
          <p>目前選定 SEARCH 任務下的候選數量。</p>
        </section>
        <section class="card metric-card">
          <div class="eyebrow">多解跡象</div>
          <div class="metric-value" :class="multiValuedCount > 0 ? 'warn' : 'good'">{{ multiValuedCount }}</div>
          <p>同一參數在不同擬合給出不同取值的候選數。</p>
        </section>
        <section class="card metric-card">
          <div class="eyebrow">可讀擬合</div>
          <div class="metric-value" :class="fitCount > 0 ? 'good' : 'warn'">{{ fitCount }}</div>
          <p>目前選定任務下已成功讀取參數的擬合總數。</p>
        </section>
      </div>

      <div class="layout unknown-grid">
        <section class="card unknown-card">
          <div class="eyebrow">可識別性檢查</div>
          <p class="unknown-value">{{ IDENTIFIABILITY_UNKNOWN }}</p>
        </section>
        <section class="card unknown-card">
          <div class="eyebrow">逆問題求解</div>
          <p class="unknown-value">{{ INVERSE_SOLVER_UNKNOWN }}</p>
        </section>
        <section class="card unknown-card">
          <div class="eyebrow">觀測量與未知參數</div>
          <p class="unknown-value">{{ INVERSE_OBSERVATION_UNKNOWN }}</p>
        </section>
      </div>

      <section class="card selector">
        <h3>選定正向模型與 SEARCH 任務</h3>
        <p v-if="searchRuns.length === 0" class="muted">
          目前沒有可讀取的 SEARCH 任務。請先建立研究版本並執行候選搜尋，才會產生可逆向推導的擬合。
        </p>
        <div v-else class="list-rows">
          <button
            v-for="entry in searchRuns"
            :key="entry.run.id"
            type="button"
            class="module-link selectable"
            :class="{ active: entry.run.id === runId }"
            @click="selectRun(entry.run.id)"
          >
            <div>
              <strong>{{ entry.research?.name ?? '未命名研究' }}</strong>
              <div class="muted mono">{{ entry.run.id }}</div>
              <div class="muted mono">{{ entry.version?.id ?? unknown }}</div>
            </div>
            <span class="tag">{{ entry.candidates.length }} 候選</span>
          </button>
        </div>
        <div v-if="selectedRun !== null" class="actions" style="margin-top: 12px;">
          <RouterLink
            v-if="workbenchQuery !== null"
            :to="{ name: 'research-workbench', params: { id: selectedRun.research?.id ?? '' }, query: workbenchQuery }"
          >
            <button type="button">打開研究工作台</button>
          </RouterLink>
          <RouterLink :to="{ name: 'run', params: { id: selectedRun.run.id }, query: withBackRef(route.fullPath) }">
            <button type="button">查看 SEARCH 任務</button>
          </RouterLink>
        </div>
      </section>

      <div class="layout inverse-grid">
        <section class="card">
          <h3>候選解與多解跡象</h3>
          <p v-if="solutions.length === 0" class="muted">目前選定任務沒有可讀取的候選，或尚未載入公式與擬合。</p>
          <table v-else>
            <thead>
              <tr>
                <th>候選</th>
                <th>公式</th>
                <th>狀態</th>
                <th>擬合</th>
                <th>多解參數</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="row in solutions"
                :key="row.candidateId"
                :class="{ active: row.candidateId === candidateId }"
                @click="selectSolution(row)"
              >
                <td>
                  <div class="mono">{{ row.candidateId }}</div>
                  <div class="muted">#{{ row.rank ?? unknown }}</div>
                </td>
                <td>
                  <div class="formula">{{ row.formula ?? unknown }}</div>
                  <div class="muted">{{ row.source }}</div>
                </td>
                <td>
                  <span class="tag" :class="statusTone(row)">{{ VALIDATION_STATUS_LABELS[row.validationStatus] }}</span>
                </td>
                <td>{{ row.fitCount }}</td>
                <td>
                  <span v-if="row.multiValuedParameters.length === 0" class="muted">無</span>
                  <span v-else class="tag warn">{{ row.multiValuedParameters.join('、') }}</span>
                </td>
              </tr>
            </tbody>
          </table>
        </section>

        <section class="card">
          <h3>參數恢復結果</h3>
          <p v-if="selectedSolution === null" class="muted">請從左側清單選擇一條候選解。</p>
          <template v-else>
            <div class="formula-hero">{{ selectedSolution.formula ?? unknown }}</div>
            <div class="row compact">
              <span>候選識別碼</span>
              <span class="mono record-value">{{ selectedSolution.candidateId }}</span>
            </div>
            <div class="row compact">
              <span>發展排名</span>
              <span class="tag">{{ selectedSolution.rank ?? unknown }}</span>
            </div>
            <div class="row compact">
              <span>來源</span>
              <span>{{ selectedSolution.source }}</span>
            </div>
            <div class="row compact">
              <span>驗證狀態</span>
              <span class="tag" :class="statusTone(selectedSolution)">
                {{ VALIDATION_STATUS_LABELS[selectedSolution.validationStatus] }}
              </span>
            </div>
            <div class="row compact">
              <span>模型複雜度</span>
              <span class="tag">{{ selectedSolution.complexity ?? unknown }}</span>
            </div>
            <div class="row compact">
              <span>定義域</span>
              <span class="record-value">{{ selectedSolution.domain ?? unknown }}</span>
            </div>
            <div class="row compact">
              <span>擬合數</span>
              <span class="tag">{{ selectedSolution.fitCount }}</span>
            </div>

            <h3 style="margin-top: 18px;">參數觀測</h3>
            <p v-if="selectedSolution.parameters.length === 0" class="muted">
              公式未取得或沒有可讀取的擬合參數（{{ unknown }}）。
            </p>
            <table v-else>
              <thead>
                <tr>
                  <th>參數</th>
                  <th>單位</th>
                  <th>上下界</th>
                  <th>觀測值</th>
                  <th>相異</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="parameter in selectedSolution.parameters" :key="parameter.name">
                  <td class="mono">{{ parameter.name }}</td>
                  <td>{{ parameter.unit }}</td>
                  <td class="muted">[{{ parameter.lower }}, {{ parameter.upper }}]</td>
                  <td>
                    <span v-if="parameter.observations.length === 0" class="muted">{{ unknown }}</span>
                    <span v-else class="mono">{{ parameter.observations.join(' / ') }}</span>
                  </td>
                  <td>
                    <span class="tag" :class="parameter.distinct > 1 ? 'warn' : ''">{{ parameter.distinct }}</span>
                  </td>
                </tr>
              </tbody>
            </table>

            <div class="note" style="margin-top: 12px;">
              相異值大於 1 代表同一參數在不同擬合給出不同取值，屬潛在多解的跡象，而非後端已判定的解集合。
            </div>
            <div class="note" style="margin-top: 8px;">
              可識別性、逆問題求解與觀測量設定需後端端點；本頁不由此推測參數是否唯一可識別。
            </div>
          </template>
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
  min-height: 150px;
}

.metric-value {
  font-size: 30px;
  font-weight: 700;
  margin: 10px 0 8px;
}

.unknown-grid {
  grid-template-columns: repeat(3, minmax(0, 1fr));
  margin-bottom: 16px;
}

.unknown-card {
  border-style: dashed;
}

.unknown-value {
  margin: 8px 0 0;
  color: #9fb3c8;
}

.selector {
  margin-bottom: 16px;
}

.list-rows {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

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

.selectable {
  width: 100%;
  text-align: left;
}

.selectable.active {
  border-color: #3673c7;
  background: #132842;
}

.inverse-grid {
  grid-template-columns: 1.2fr 1fr;
}

.compact {
  padding: 8px 0;
}

tbody tr {
  cursor: pointer;
}

tbody tr.active td {
  background: #132842;
}

.formula {
  font: 13px ui-monospace, SFMono-Regular, Menlo, monospace;
  overflow-wrap: anywhere;
}

.formula-hero {
  font: 18px ui-monospace, SFMono-Regular, Menlo, monospace;
  color: #a7e4d6;
  overflow-wrap: anywhere;
  padding: 12px 0;
}

.record-value {
  max-width: 62%;
  text-align: right;
  overflow-wrap: anywhere;
}

@media (max-width: 1200px) {
  .metric-grid,
  .unknown-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .inverse-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 900px) {
  .metric-grid,
  .unknown-grid {
    grid-template-columns: 1fr;
  }
}
</style>
