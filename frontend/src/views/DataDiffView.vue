<script setup lang="ts">
/**
 * 資料版本比較（SSOT SCREEN 17，diff）：版本差異、血緣、回復與影響。
 *
 * 差異只依兩個不可變版本的已揭露欄位與結構預覽計算；血緣只取已讀取版本的時間序，父版本關聯、
 * 回復流程與下游影響沒有後端端點，一律標示「未取得」。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import DataTabs from '../components/DataTabs.vue'
import {
  DATA_UNKNOWN,
  buildDiffRows,
  buildVersionLineage,
  latestAnalyzableVersion,
  metadataForVersion,
} from '../lib/dataCenter'
import { recentVersions } from '../lib/datasetWorkbench'
import { readQueryString, replaceQueryState } from '../lib/queryState'
import { useDatasetWorkspace } from '../lib/useDataCenter'

const route = useRoute()
const router = useRouter()
const datasetId = computed(() => (typeof route.params.id === 'string' ? route.params.id : ''))
const { workspace, loading, error, load } = useDatasetWorkspace(() => datasetId.value)

const baseId = ref(readQueryString(route.query, 'base'))
const targetId = ref(readQueryString(route.query, 'target'))

const versions = computed(() => workspace.value?.versions ?? [])
const options = computed(() => recentVersions(versions.value))
const baseVersion = computed(() => versions.value.find((row) => row.id === baseId.value) ?? null)
const targetVersion = computed(() => versions.value.find((row) => row.id === targetId.value) ?? null)
const outcome = computed(() => {
  const base = baseVersion.value
  const target = targetVersion.value
  if (base === null || target === null) return null
  const cache = workspace.value?.metadataByArtifact ?? {}
  return buildDiffRows(base, target, metadataForVersion(cache, base), metadataForVersion(cache, target))
})
const lineage = computed(() => buildVersionLineage(versions.value))
const backRef = readQueryString(route.query, 'ref')

function pickDefaults(): void {
  const latest = latestAnalyzableVersion(versions.value)
  const fallback = versions.value.find((row) => row.id !== latest?.id) ?? null
  if (baseId.value === '' || !versions.value.some((row) => row.id === baseId.value)) {
    baseId.value = fallback?.id ?? ''
  }
  if (targetId.value === '' || !versions.value.some((row) => row.id === targetId.value)) {
    targetId.value = latest?.id ?? ''
  }
}

onMounted(async () => {
  await load()
  const queryBase = readQueryString(route.query, 'base')
  const queryTarget = readQueryString(route.query, 'target')
  const latest = latestAnalyzableVersion(versions.value)
  baseId.value = versions.value.some((row) => row.id === queryBase) ? queryBase : (versions.value.find((row) => row.id !== latest?.id)?.id ?? '')
  targetId.value = versions.value.some((row) => row.id === queryTarget) ? queryTarget : (latest?.id ?? '')
})

watch(
  () => route.params.id,
  async () => {
    if (route.name !== 'data-diff') return
    await load()
    pickDefaults()
  },
)

watch(baseId, async (value) => {
  await replaceQueryState(router, route, { base: value })
})

watch(targetId, async (value) => {
  await replaceQueryState(router, route, { target: value })
})
</script>

<template>
  <section>
    <DataTabs :dataset-id="datasetId" />

    <div class="head">
      <div>
        <div class="eyebrow">數據 / SCREEN 17</div>
        <h1>資料版本比較</h1>
        <p class="muted">
          版本差異、血緣、回復與影響｜差異只比較兩個不可變版本的已揭露欄位；血緣、回復流程與下游影響未揭露時標示「未取得」。
        </p>
      </div>
      <div class="actions">
        <RouterLink :to="{ name: 'datasets' }"><button type="button">返回資料集清單</button></RouterLink>
        <button v-if="backRef !== ''" type="button" @click="router.push(backRef)">返回來源頁</button>
        <button type="button" @click="load">重新載入</button>
      </div>
    </div>

    <p v-if="loading && workspace === null" class="muted">載入中…</p>
    <p v-else-if="workspace === null" class="bad">{{ error === '' ? '未取得此資料集。' : error }}</p>
    <template v-else>
      <section class="card">
        <h3>比較對象</h3>
        <div class="formgrid">
          <div class="field">
            <label for="data-diff-base">基準版本（base）</label>
            <select id="data-diff-base" v-model="baseId">
              <option value="">未選擇</option>
              <option v-for="row in options" :key="`base:${row.id}`" :value="row.id">
                {{ row.created_at }} · {{ row.format }} · {{ row.row_count }} 列
              </option>
            </select>
          </div>
          <div class="field">
            <label for="data-diff-target">對照版本（target）</label>
            <select id="data-diff-target" v-model="targetId">
              <option value="">未選擇</option>
              <option v-for="row in options" :key="`target:${row.id}`" :value="row.id">
                {{ row.created_at }} · {{ row.format }} · {{ row.row_count }} 列
              </option>
            </select>
          </div>
        </div>
        <p v-if="options.length < 2" class="muted">需要至少兩個版本才能比較差異。</p>
      </section>

      <div class="layout cols2" style="margin-top: 16px;">
        <section class="card">
          <h3>版本差異</h3>
          <p v-if="outcome === null" class="muted">請選擇兩個版本以顯示差異。</p>
          <template v-else>
            <div class="row compact">
              <span>變更項目</span>
              <span class="tag" :class="outcome.changedCount > 0 ? 'warn' : 'good'">{{ outcome.changedCount }} / {{ outcome.rows.length }}</span>
            </div>
            <table>
              <thead>
                <tr><th>項目</th><th>基準</th><th>對照</th><th>變更</th></tr>
              </thead>
              <tbody>
                <tr v-for="row in outcome.rows" :key="row.label">
                  <td>{{ row.label }}</td>
                  <td class="mono record-value">{{ row.base }}</td>
                  <td class="mono record-value">{{ row.target }}</td>
                  <td>
                    <span class="tag" :class="row.changed ? 'warn' : 'good'">{{ row.changed ? '有變更' : '未變更' }}</span>
                  </td>
                </tr>
              </tbody>
            </table>
            <div class="row compact" style="margin-top: 10px;">
              <span>列數差異（對照 − 基準）</span>
              <span :class="outcome.diff.rowDelta === 0 ? '' : outcome.diff.rowDelta > 0 ? 'good' : 'bad'">
                {{ outcome.diff.rowDelta > 0 ? '+' : '' }}{{ outcome.diff.rowDelta }}
              </span>
            </div>
          </template>
        </section>

        <section class="card">
          <h3>血緣與回復</h3>
          <p class="muted">血緣只取已讀取版本的時間序；父版本關聯與回復流程沒有後端端點。</p>
          <ol v-if="lineage.length > 0" class="lineage-list">
            <li v-for="entry in lineage" :key="entry.versionId">
              <span class="mono record-value">{{ entry.versionId }}</span>
              <div class="muted">{{ entry.label }}</div>
            </li>
          </ol>
          <p v-else class="muted">此資料集尚無版本，無法推導血緣。</p>

          <div class="unknown-list" style="margin-top: 14px;">
            <div class="row compact">
              <span>父版本與派生關係</span>
              <span class="muted">{{ DATA_UNKNOWN }}</span>
            </div>
            <div class="row compact">
              <span>回復流程與還原點</span>
              <span class="muted">{{ DATA_UNKNOWN }}</span>
            </div>
            <div class="row compact">
              <span>下游研究影響範圍</span>
              <span class="muted">{{ DATA_UNKNOWN }}</span>
            </div>
          </div>
        </section>
      </div>

      <p v-if="error !== ''" class="bad" style="margin-top: 16px;">{{ error }}</p>
    </template>
  </section>
</template>

<style scoped>
.compact {
  padding: 9px 0;
}

.record-value {
  max-width: 100%;
  overflow-wrap: anywhere;
}

.lineage-list {
  margin: 0;
  padding-left: 18px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
</style>
