<script setup lang="ts">
/**
 * 候選公式工作區：單一候選的公式、參數、擬合與驗證閱讀入口。
 * 後端未提供單筆候選讀取，因此以 SEARCH 任務的候選分頁為來源，並用 ?run= 帶入來源任務。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { getEquationVersion, getFitRun, listRunCandidates, type Candidate, type EquationVersion, type FitRun, type ValidationStatus } from '../api/candidates'
import { getValidationRun } from '../api/evaluations'
import {
  buildCandidatePeerRows,
  buildCandidateReading,
  findCandidate,
  orderedFits,
  PEER_LIMIT,
} from '../lib/candidateDetail'
import { OUTCOME_LABELS, parseValidationRun, refusalReasons, type ValidationRun } from '../lib/evaluation'
import { describeError } from '../lib/messages'
import { readBackRef, withBackRef } from '../lib/navigationState'
import { readQueryString, replaceQueryState } from '../lib/queryState'
import { client } from '../lib/session'

const route = useRoute()
const router = useRouter()

/** 一次讀取候選分頁的上限；後端以簽章游標分頁，這裡只取第一頁。 */
const CANDIDATE_PAGE_LIMIT = 100

const candidateId = computed(() => (typeof route.params.id === 'string' ? route.params.id : ''))
const runId = ref(readQueryString(route.query, 'run'))
const backRef = computed(() => readBackRef(route.query))

const candidates = ref<Candidate[]>([])
const equations = ref<Record<string, EquationVersion>>({})
const fits = ref<Record<string, FitRun>>({})
const validations = ref<Record<string, ValidationRun | undefined>>({})

const loading = ref(false)
const error = ref('')

const statusLabels: Record<ValidationStatus, string> = {
  NOT_RUN: '尚未執行',
  PENDING: '進行中',
  FINISHED: '已完成',
  INVALID: '無效',
}

const candidate = computed<Candidate | null>(() => findCandidate(candidates.value, candidateId.value))
const reading = computed(() =>
  candidate.value === null
    ? null
    : buildCandidateReading(
        candidate.value,
        equations.value[candidate.value.equation_version_id] ?? null,
        orderedFits(candidate.value, fits.value),
        validations.value as Record<string, ValidationRun>,
      ),
)
const peers = computed(() => buildCandidatePeerRows(candidates.value, equations.value, fits.value, candidateId.value))
const backQuery = computed<Record<string, string>>(() => withBackRef(route.fullPath))
const runQuery = computed<Record<string, string>>(() => withBackRef(route.fullPath))

function unique(ids: string[]): string[] {
  return [...new Set(ids)]
}

async function loadEquations(ids: string[]): Promise<void> {
  const missing = ids.filter((id) => equations.value[id] === undefined)
  const loaded = await Promise.all(
    missing.map(async (id) => {
      try {
        return [id, await getEquationVersion(client, id)] as const
      } catch {
        return null
      }
    }),
  )
  const next = { ...equations.value }
  for (const entry of loaded) {
    if (entry !== null) next[entry[0]] = entry[1]
  }
  equations.value = next
}

async function loadFits(ids: string[]): Promise<void> {
  const missing = ids.filter((id) => fits.value[id] === undefined)
  const loaded = await Promise.all(
    missing.map(async (id) => {
      try {
        return [id, await getFitRun(client, id)] as const
      } catch {
        return null
      }
    }),
  )
  const next = { ...fits.value }
  for (const entry of loaded) {
    if (entry !== null) next[entry[0]] = entry[1]
  }
  fits.value = next
}

async function loadValidations(ids: string[]): Promise<void> {
  const missing = ids.filter((id) => validations.value[id] === undefined)
  const loaded = await Promise.all(
    missing.map(async (id) => {
      try {
        return [id, parseValidationRun(await getValidationRun(client, id)) ?? undefined] as const
      } catch {
        return [id, undefined] as const
      }
    }),
  )
  const next = { ...validations.value }
  for (const entry of loaded) {
    next[entry[0]] = entry[1]
  }
  validations.value = next
}

async function load(): Promise<void> {
  if (runId.value === '') {
    candidates.value = []
    error.value = ''
    return
  }
  loading.value = true
  error.value = ''
  try {
    const page = await listRunCandidates(client, runId.value, { limit: CANDIDATE_PAGE_LIMIT })
    candidates.value = page.items
    const current = findCandidate(page.items, candidateId.value)
    const peerIds = page.items.slice(0, PEER_LIMIT).map((row) => row.equation_version_id)
    await loadEquations(unique([...peerIds, ...(current === null ? [] : [current.equation_version_id])]))
    await loadFits(
      unique([
        ...page.items.slice(0, PEER_LIMIT).flatMap((row) => row.fit_run_ids.slice(0, 1)),
        ...(current === null ? [] : current.fit_run_ids),
      ]),
    )
    if (current !== null) {
      await loadValidations(current.validation_run_ids)
    }
  } catch (cause) {
    candidates.value = []
    error.value = describeError(cause)
  } finally {
    loading.value = false
  }
}

onMounted(load)

watch(
  [() => route.params.id, () => route.query.run],
  async () => {
    if (route.name !== 'candidate') return
    runId.value = readQueryString(route.query, 'run')
    await load()
  },
)

watch(runId, async (value) => {
  await replaceQueryState(router, route, { run: value })
})
</script>

<template>
  <section>
    <div class="head">
      <div>
        <div class="eyebrow">發現 / CANDIDATE</div>
        <h1>候選公式</h1>
        <p class="muted">公式、參數、擬合與驗證結果，全部取自後端已揭露欄位。</p>
      </div>
      <div class="actions">
        <RouterLink v-if="backRef !== ''" :to="backRef"><button type="button">返回來源頁</button></RouterLink>
        <button type="button" :disabled="loading" @click="load">重新載入</button>
      </div>
    </div>

    <p v-if="loading && candidate === null" class="muted">載入中…</p>
    <p v-else-if="runId === ''" class="bad">
      此頁需要來源 SEARCH 任務。請從發現中心或任務詳情的候選清單進入，或於網址加上 <span class="mono">?run=&lt;searchRunId&gt;</span>。
    </p>
    <p v-else-if="error !== ''" class="bad">{{ error }}</p>
    <p v-else-if="candidate === null" class="bad">此任務的候選分頁中未取得該候選，可能已被移除或不在可見範圍內。</p>

    <template v-else-if="reading !== null">
      <div class="layout cols2">
        <section class="card">
          <div class="row">
            <div>
              <strong>候選 #{{ reading.rank ?? '—' }}</strong>
              <div class="mono">{{ reading.id }}</div>
            </div>
            <span class="tag">{{ statusLabels[reading.validationStatus] }}</span>
          </div>
          <dl class="facts">
            <dt>來源</dt>
            <dd>{{ reading.source }}</dd>
            <dt>公式版本</dt>
            <dd class="mono">{{ reading.equationVersionId }}</dd>
            <dt>身分雜湊</dt>
            <dd class="mono">{{ reading.identityHash ?? '未取得' }}</dd>
            <dt>模型複雜度</dt>
            <dd>{{ reading.complexity ?? '未取得' }}</dd>
            <dt>擬合參數有效位數</dt>
            <dd>{{ reading.fitPrecisionBits ?? '未取得' }}</dd>
            <dt>所屬 SEARCH 任務</dt>
            <dd>
              <RouterLink :to="{ name: 'run', params: { id: reading.searchRunId }, query: runQuery }">
                <span class="mono">{{ reading.searchRunId }}</span>
              </RouterLink>
            </dd>
          </dl>
          <div class="actions" style="margin-top: 12px;">
            <RouterLink :to="{ name: 'discoveries', query: withBackRef(route.fullPath, { run: reading.searchRunId, pins: reading.id }) }">
              <button type="button">在發現中心比較</button>
            </RouterLink>
          </div>
        </section>

        <section class="card">
          <h3>公式</h3>
          <p v-if="reading.formulaText === null" class="muted">未取得此候選的公式版本內容。</p>
          <template v-else>
            <pre class="formula"><code>{{ reading.formulaText }}</code></pre>
            <div class="row compact">
              <span>定義域</span>
              <span class="mono">{{ reading.domains === '' ? '未提供' : reading.domains }}</span>
            </div>
            <div class="row compact">
              <span>變數</span>
              <span class="mono">
                {{
                  reading.variables === null || reading.variables.length === 0
                    ? '未提供'
                    : reading.variables.map((variable) => `${variable.name}（${variable.unit}）`).join('、')
                }}
              </span>
            </div>
          </template>
        </section>
      </div>

      <div class="layout cols2" style="margin-top: 16px;">
        <section class="card">
          <h3>參數</h3>
          <p v-if="reading.parameters === null" class="muted">未取得公式版本，無法列出參數邊界。</p>
          <p v-else-if="reading.parameters.length === 0" class="muted">此公式沒有可調參數。</p>
          <table v-else>
            <thead><tr><th>參數</th><th>單位</th><th>下界</th><th>上界</th><th>擬合值</th></tr></thead>
            <tbody>
              <tr v-for="parameter in reading.parameters" :key="parameter.name">
                <td class="mono">{{ parameter.name }}</td>
                <td>{{ parameter.unit }}</td>
                <td class="mono">{{ parameter.lower }}</td>
                <td class="mono">{{ parameter.upper }}</td>
                <td class="mono">{{ parameter.fittedValue ?? '未取得' }}</td>
              </tr>
            </tbody>
          </table>
        </section>

        <section class="card">
          <h3>擬合執行</h3>
          <p v-if="reading.fits.length === 0" class="muted">此候選尚未連結擬合結果。</p>
          <table v-else>
            <thead>
              <tr><th>任務</th><th>優化器</th><th>切分角色</th><th>精度位元</th><th>參數數</th><th>擬合列數</th><th>表徵產物</th></tr>
            </thead>
            <tbody>
              <tr v-for="fit in reading.fits" :key="fit.id">
                <td class="mono">{{ fit.id }}</td>
                <td>{{ fit.optimizer }}</td>
                <td>{{ fit.splitRole }}</td>
                <td>{{ fit.precisionBits }}</td>
                <td>{{ fit.parameterCount }}</td>
                <td>{{ fit.fitRowCount }}</td>
                <td>
                  <RouterLink :to="{ name: 'artifact', params: { id: fit.representationArtifactId }, query: runQuery }">
                    <span class="mono">{{ fit.representationArtifactId }}</span>
                  </RouterLink>
                </td>
              </tr>
            </tbody>
          </table>
        </section>
      </div>

      <section class="card" style="margin-top: 16px;">
        <h3>驗證執行</h3>
        <p v-if="reading.validations.length === 0 && reading.missingValidationIds.length === 0" class="muted">
          此候選尚未連結驗證執行。
        </p>
        <template v-else>
          <div v-for="row in reading.validations" :key="row.id" class="validation-card">
            <div class="row">
              <div>
                <strong>{{ OUTCOME_LABELS[row.outcome] }}</strong>
                <div class="mono">{{ row.id }}</div>
              </div>
              <span class="tag">{{ row.splitRole }}</span>
            </div>
            <dl class="facts">
              <dt>經驗等級 / 證明等級</dt>
              <dd>{{ row.empiricalLevel }} / {{ row.proofLevel }}</dd>
              <dt>MAE / RMSE</dt>
              <dd class="mono">{{ row.mae ?? '未取得' }} / {{ row.rmse ?? '未取得' }}</dd>
              <dt>有效覆蓋率</dt>
              <dd>{{ row.validCoverage }}</dd>
              <dt>選取 / 有效 / 失敗</dt>
              <dd class="mono">{{ row.selectedCount }} / {{ row.validCount }} / {{ row.failedCount }}</dd>
              <dt>建立時間</dt>
              <dd class="mono">{{ row.createdAt }}</dd>
            </dl>
            <div v-if="refusalReasons(row).length !== 0" class="note">
              <div v-for="reason in refusalReasons(row)" :key="reason">{{ reason }}</div>
            </div>
          </div>
          <p v-if="reading.missingValidationIds.length !== 0" class="muted">
            未取得的驗證執行：<span class="mono">{{ reading.missingValidationIds.join('、') }}</span>
          </p>
        </template>
      </section>

      <section class="card" style="margin-top: 16px;">
        <h3>同任務候選</h3>
        <p class="muted">最多列出 {{ PEER_LIMIT }} 筆；只呈現已載入的欄位，未載入者標示「載入中」。</p>
        <table>
          <thead>
            <tr><th>名次</th><th>來源</th><th>驗證狀態</th><th>複雜度</th><th>參數數</th><th>有效位數</th><th>操作</th></tr>
          </thead>
          <tbody>
            <tr v-for="row in peers" :key="row.id" :class="{ active: row.active }">
              <td class="mono">#{{ row.rank ?? '—' }}</td>
              <td>{{ row.source }}</td>
              <td>{{ statusLabels[row.validationStatus] }}</td>
              <td>{{ row.complexity ?? '載入中' }}</td>
              <td>{{ row.parameterCount ?? '載入中' }}</td>
              <td>{{ row.precisionBits ?? '載入中' }}</td>
              <td>
                <RouterLink
                  :to="{ name: 'candidate', params: { id: row.id }, query: withBackRef(route.fullPath, { run: runId }) }"
                >
                  {{ row.active ? '目前檢視' : '檢視' }}
                </RouterLink>
              </td>
            </tr>
          </tbody>
        </table>
      </section>
    </template>
  </section>
</template>

<style scoped>
.facts {
  display: grid;
  grid-template-columns: minmax(10rem, auto) 1fr;
  gap: 8px 16px;
  margin: 12px 0 0;
}

.facts dt {
  color: #8fa6c0;
  font-size: 0.9rem;
}

.facts dd {
  margin: 0;
  word-break: break-all;
}

.formula {
  background: #0b1829;
  border: 1px solid #27405d;
  border-radius: 10px;
  padding: 12px;
  overflow-x: auto;
  white-space: pre-wrap;
  word-break: break-all;
}

.compact {
  padding: 10px 0;
}

.validation-card {
  border: 1px solid #27405d;
  border-radius: 12px;
  padding: 14px;
  background: #0b1829;
  margin-bottom: 12px;
}

tr.active {
  background: #132842;
}
</style>
