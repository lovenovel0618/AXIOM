<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { getFinalEvaluation, getValidationRun } from '../api/evaluations'
import { listResearchVersionRuns, listResearchVersions, listResearches } from '../api/research'
import { parseValidationRun } from '../lib/evaluation'
import { parseFinalEvaluation } from '../lib/finalEvaluation'
import { describeError } from '../lib/messages'
import { readBackRef, withBackRef } from '../lib/navigationState'
import { readQueryList, readQueryString, replaceQueryState } from '../lib/queryState'
import { client } from '../lib/session'
import { loadVerificationCenter, type VerificationCenter } from '../lib/verificationCenter'
import { buildVerificationHandoffSummary } from '../lib/workflowHandoff'

const route = useRoute()
const router = useRouter()
const center = ref<VerificationCenter | null>(null)
const loading = ref(false)
const error = ref('')
const filteredSubmissionIds = ref<string[]>(readQueryList(route.query, 'submissions'))
const selectedSubmissionId = ref(readQueryString(route.query, 'submission'))

const backRef = computed(() => readBackRef(route.query))
const visibleSubmissionRows = computed(() => {
  const rows = center.value?.submissionRows ?? []
  if (filteredSubmissionIds.value.length === 0) return rows
  const allowed = new Set(filteredSubmissionIds.value)
  return rows.filter((row) => allowed.has(row.submissionId))
})
const handoffSummary = computed(() =>
  buildVerificationHandoffSummary(center.value?.submissionRows ?? [], filteredSubmissionIds.value, selectedSubmissionId.value),
)

const selectedSubmission = computed(
  () => visibleSubmissionRows.value.find((row) => row.submissionId === selectedSubmissionId.value) ?? null,
)
const backQuery = computed<Record<string, string>>(() => withBackRef(route.fullPath))
const selectedVersionGroup = computed(() =>
  handoffSummary.value.groups.find((group) => group.submissionIds.includes(selectedSubmissionId.value)) ??
  handoffSummary.value.groups[0] ??
  null,
)
const selectedVersionWorkbenchQuery = computed<Record<string, string> | null>(() => {
  const group = selectedVersionGroup.value
  if (group === null) return null
  const focusIds = group.submissionIds
  const nodeId = group.selectedSubmissionId ?? focusIds[0]
  return withBackRef(route.fullPath, {
    version: group.versionId,
    flowkind: 'SUBMISSION',
    focussubmissions: focusIds.join(','),
    node: nodeId === undefined ? undefined : `submission:${nodeId}`,
  })
})
const currentSubmissionWorkbenchQuery = computed<Record<string, string> | null>(() => {
  const row = selectedSubmission.value
  if (row === null) return null
  return withBackRef(route.fullPath, {
    version: row.version.id,
    flowkind: 'SUBMISSION',
    focussubmissions: row.submissionId,
    node: `submission:${row.submissionId}`,
  })
})

function showAllSubmissions(): void {
  filteredSubmissionIds.value = []
}

function showOnlySubmissionIds(ids: string[]): void {
  filteredSubmissionIds.value = ids
}

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    center.value = await loadVerificationCenter({
      listResearches: (limit) => listResearches(client, limit),
      listResearchVersions: (researchId, limit) => listResearchVersions(client, researchId, limit),
      listResearchVersionRuns: (versionId, limit) => listResearchVersionRuns(client, versionId, limit),
      getFinalEvaluation: async (submissionId) => {
        try {
          return parseFinalEvaluation(await getFinalEvaluation(client, submissionId))
        } catch {
          return null
        }
      },
      getValidationRun: async (validationId) => {
        try {
          return parseValidationRun(await getValidationRun(client, validationId))
        } catch {
          return null
        }
      },
    })
    const first = visibleSubmissionRows.value[0] ?? center.value.submissionRows[0]
    if (first !== undefined && visibleSubmissionRows.value.every((row) => row.submissionId !== selectedSubmissionId.value)) {
      selectedSubmissionId.value = first.submissionId
    }
  } catch (cause) {
    center.value = null
    error.value = describeError(cause)
  } finally {
    loading.value = false
  }
}

onMounted(load)

watch(
  selectedSubmissionId,
  async (value) => {
    await replaceQueryState(router, route, { submission: value })
  },
)

watch(
  filteredSubmissionIds,
  async (value) => {
    await replaceQueryState(router, route, { submissions: value.length === 0 ? undefined : value.join(',') })
  },
  { deep: true },
)

watch(
  () => route.query,
  () => {
    filteredSubmissionIds.value = readQueryList(route.query, 'submissions')
    selectedSubmissionId.value = readQueryString(route.query, 'submission')
  },
)

watch(visibleSubmissionRows, (rows) => {
  if (rows.length === 0) return
  if (rows.some((row) => row.submissionId === selectedSubmissionId.value)) return
  selectedSubmissionId.value = rows[0]?.submissionId ?? ''
})
</script>

<template>
  <section>
    <div class="head">
      <div>
        <div class="eyebrow">驗證 / CENTER</div>
        <h1>驗證中心</h1>
        <p class="muted">集中檢視最近任務、證據版本與 frozen submission 的最終評估投影。</p>
      </div>
      <div class="actions">
        <button v-if="backRef !== ''" type="button" @click="router.push(backRef)">返回來源頁</button>
        <button type="button" @click="load">重新載入</button>
        <RouterLink :to="{ name: 'research-list' }">
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

      <div class="layout verification-grid">
        <section class="card">
          <h3>最近任務</h3>
          <p v-if="center.runs.length === 0" class="muted">最近沒有可讀取的任務。</p>
          <div v-else class="list-rows">
            <RouterLink
              v-for="run in center.runs"
              :key="run.id"
              :to="{ name: 'run', params: { id: run.id }, query: backQuery }"
              class="module-link"
            >
              <div>
                <strong>{{ run.type }} / {{ run.status }}</strong>
                <div class="muted mono">{{ run.id }}</div>
                <div class="muted">{{ run.created_at }}</div>
              </div>
              <span class="tag">{{ run.outcome_status ?? '未回報' }}</span>
            </RouterLink>
          </div>
        </section>

        <section class="card">
          <h3>證據版本</h3>
          <p v-if="center.evidenceRows.length === 0" class="muted">最近沒有掛上證據的研究版本。</p>
          <div v-else class="list-rows">
            <RouterLink
              v-for="row in center.evidenceRows"
              :key="row.version.id"
              :to="{ name: 'research-workbench', params: { id: row.version.research_id }, query: withBackRef(route.fullPath, { version: row.version.id }) }"
              class="module-link"
            >
              <div>
                <strong>{{ row.research?.name ?? '未命名研究' }}</strong>
                <div class="muted mono">{{ row.version.id }}</div>
              </div>
              <div class="stack">
                <span class="tag">{{ row.version.status }}</span>
                <span class="tag">
                  {{ row.version.quality_report_id === null ? row.version.evidence_bundle_ids.length + ' BUNDLE' : 'QUALITY' }}
                </span>
              </div>
            </RouterLink>
          </div>
        </section>

        <section class="card">
          <h3>最終評估</h3>
          <p v-if="center.submissionRows.length === 0" class="muted">最近沒有 frozen submission 的最終評估資料。</p>
          <div v-else class="submission-layout">
            <section class="handoff-workspace">
              <div class="handoff-head">
                <div>
                  <strong>提交接力工作區</strong>
                  <p class="muted">驗證中心會先按研究版本整理 submission 子集，再把同版本的集合送回研究工作台，避免跨版本混線。</p>
                </div>
                <span class="tag">{{ handoffSummary.visibleSubmissions }} / {{ handoffSummary.totalSubmissions }}</span>
              </div>
              <div class="handoff-grid">
                <div class="row compact">
                  <span>目前可見提交</span>
                  <span class="tag">{{ handoffSummary.visibleSubmissions }}</span>
                </div>
                <div class="row compact">
                  <span>已隱藏提交</span>
                  <span class="tag">{{ handoffSummary.hiddenSubmissions }}</span>
                </div>
                <div class="row compact">
                  <span>版本群組</span>
                  <span class="tag">{{ handoffSummary.groups.length }}</span>
                </div>
                <div class="row compact">
                  <span>目前選中</span>
                  <span class="mono">{{ handoffSummary.selectedSubmissionId || '未取得' }}</span>
                </div>
              </div>
              <div class="actions wrap" style="margin: 12px 0;">
                <button type="button" :disabled="handoffSummary.hiddenSubmissions === 0" @click="showAllSubmissions">
                  顯示全部提交
                </button>
                <button
                  type="button"
                  :disabled="selectedVersionGroup === null"
                  @click="showOnlySubmissionIds(selectedVersionGroup?.submissionIds ?? [])"
                >
                  僅看目前版本
                </button>
                <RouterLink
                  v-if="selectedVersionGroup !== null && selectedVersionWorkbenchQuery !== null"
                  :to="{
                    name: 'research-workbench',
                    params: { id: selectedVersionGroup.researchId },
                    query: selectedVersionWorkbenchQuery,
                  }"
                >
                  <button type="button">打開目前版本工作台</button>
                </RouterLink>
                <RouterLink
                  v-if="selectedSubmission !== null && currentSubmissionWorkbenchQuery !== null"
                  :to="{
                    name: 'research-workbench',
                    params: { id: selectedSubmission.version.research_id },
                    query: currentSubmissionWorkbenchQuery,
                  }"
                >
                  <button type="button">只聚焦這筆提交</button>
                </RouterLink>
              </div>
              <div v-if="handoffSummary.groups.length !== 0" class="group-list">
                <button
                  v-for="group in handoffSummary.groups"
                  :key="group.versionId"
                  type="button"
                  class="group-card"
                  :class="{ active: selectedVersionGroup?.versionId === group.versionId }"
                  @click="showOnlySubmissionIds(group.submissionIds)"
                >
                  <strong>{{ group.researchName }}</strong>
                  <span class="mono">{{ group.versionId }}</span>
                  <span class="tag">{{ group.submissionIds.length }} 提交</span>
                  <span class="muted">已評估 {{ group.evaluatedCount }} / 待補 {{ group.pendingCount }}</span>
                </button>
              </div>
            </section>
            <div v-if="filteredSubmissionIds.length !== 0" class="note" style="margin-bottom: 16px;">
              目前只顯示從工作台帶入的 {{ visibleSubmissionRows.length }} / {{ center.submissionRows.length }} 筆提交。
            </div>
            <div class="list-rows">
              <button
                v-for="row in visibleSubmissionRows"
                :key="row.submissionId"
                type="button"
                class="module-link selectable"
                :class="{ active: selectedSubmissionId === row.submissionId }"
                @click="selectedSubmissionId = row.submissionId"
              >
                <div>
                  <strong>{{ row.research?.name ?? '未命名研究' }}</strong>
                  <div class="muted mono">{{ row.submissionId }}</div>
                </div>
                <span class="tag">{{ row.finalEvaluation?.status ?? '未取得' }}</span>
              </button>
            </div>

            <div v-if="selectedSubmission !== null" class="submission-detail">
              <div class="row compact">
                <span>研究版本</span>
                <span class="mono">{{ selectedSubmission.version.id }}</span>
              </div>
              <div class="row compact">
                <span>評估狀態</span>
                <span class="tag">{{ selectedSubmission.finalEvaluation?.status ?? '未取得' }}</span>
              </div>
              <div class="row compact">
                <span>指標版本</span>
                <span>{{ selectedSubmission.finalEvaluation?.metricVersion ?? '未取得' }}</span>
              </div>
              <div class="row compact">
                <span>曝光預算</span>
                <span>
                  {{
                    selectedSubmission.finalEvaluation === null
                      ? '未取得'
                      : `${selectedSubmission.finalEvaluation.exposure.consumed} / ${selectedSubmission.finalEvaluation.exposure.budget}`
                  }}
                </span>
              </div>
              <div class="row compact">
                <span>槽位數</span>
                <span class="tag">{{ selectedSubmission.finalEvaluation?.slots.length ?? 0 }}</span>
              </div>
              <div class="actions wrap" style="margin: 12px 0 16px;">
                <RouterLink
                  :to="{
                    name: 'research-workbench',
                    params: { id: selectedSubmission.version.research_id },
                    query: selectedVersionWorkbenchQuery ?? withBackRef(route.fullPath, { version: selectedSubmission.version.id }),
                  }"
                >
                  <button type="button">打開目前版本工作台</button>
                </RouterLink>
                <RouterLink
                  v-if="currentSubmissionWorkbenchQuery !== null"
                  :to="{
                    name: 'research-workbench',
                    params: { id: selectedSubmission.version.research_id },
                    query: currentSubmissionWorkbenchQuery,
                  }"
                >
                  <button type="button">只看這筆提交</button>
                </RouterLink>
              </div>

              <h3 style="margin-top: 0;">Validation 結果</h3>
              <p v-if="selectedSubmission.validations.length === 0" class="muted">目前沒有可讀的 validation run 結果。</p>
              <table v-else>
                <thead>
                  <tr>
                    <th>結果</th>
                    <th>Split</th>
                    <th>MAE / RMSE</th>
                    <th>Coverage</th>
                    <th>建立時間</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="row in selectedSubmission.validations" :key="row.id">
                    <td>{{ row.outcome }}</td>
                    <td>{{ row.splitRole }}</td>
                    <td>{{ row.mae ?? 'NA' }} / {{ row.rmse ?? 'NA' }}</td>
                    <td>{{ row.validCoverage }}</td>
                    <td class="mono">{{ row.createdAt }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <p v-else class="muted">目前篩選條件下沒有可讀取的提交詳情。</p>
          </div>
          <div class="note" style="margin-top: 16px;">
            驗證頁目前聚焦最近 frozen submission 與 validation run 投影；更完整的全域證據關聯圖仍待後續接線。
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

.verification-grid {
  grid-template-columns: 320px 340px minmax(0, 1.3fr);
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

.stack {
  display: flex;
  flex-direction: column;
  gap: 6px;
  align-items: flex-end;
}

.submission-layout {
  display: grid;
  grid-template-columns: 280px minmax(0, 1fr);
  gap: 16px;
}

.handoff-workspace {
  grid-column: 1 / -1;
  border: 1px solid #27405d;
  border-radius: 12px;
  padding: 14px;
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

.group-list {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 10px;
}

.group-card {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 6px;
  border: 1px solid #27405d;
  border-radius: 10px;
  padding: 12px;
  background: #0e1e31;
  text-align: left;
}

.group-card.active {
  border-color: #3673c7;
  background: #132842;
}

.compact {
  padding: 10px 0;
}

@media (max-width: 1200px) {
  .metric-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .verification-grid,
  .submission-layout {
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
