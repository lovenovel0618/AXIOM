<script setup lang="ts">
/**
 * 隱藏變數探索（SSOT SCREEN 20）：潛在狀態、內在維度及可識別性。
 *
 * 資料來源是 PROFILE 產出的結構評估產物（StructureAssessment）。後端目前一律回
 * `intrinsic_dimension_estimate: null` 與 `structure_candidates: ["UNKNOWN"]`，
 * 因此本頁只呈現已揭露的中介資料與形狀，不從中介資料推測可識別性。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import DiscoveryTabs from '../components/DiscoveryTabs.vue'
import { useLatentExploration } from '../lib/useLatentExploration'
import {
  ANALYSIS_SCOPE_LABELS,
  PERIODICITY_LABELS,
  STRUCTURE_CANDIDATE_LABELS,
  TIME_BASIS_LABELS,
  isStructureIdentified,
  type LatentRow,
  type StructureAssessment,
} from '../lib/structureAssessment'
import { DISCOVERY_UNKNOWN } from '../lib/discoveries'
import { readBackRef, withBackRef } from '../lib/navigationState'
import { readQueryString, replaceQueryState } from '../lib/queryState'

const route = useRoute()
const router = useRouter()
const { snapshot, loading, error, load } = useLatentExploration()

const selectedId = ref(readQueryString(route.query, 'version'))
const unknown = DISCOVERY_UNKNOWN

const rows = computed<LatentRow[]>(() => snapshot.value?.rows ?? [])
const summary = computed(() => snapshot.value?.summary ?? null)
const scope = computed(() => snapshot.value?.scope ?? null)
const selectedRow = computed<LatentRow | null>(() => rows.value.find((row) => row.versionId === selectedId.value) ?? null)
const backRef = computed(() => readBackRef(route.query))

function artifactLabel(row: LatentRow): string {
  if (row.parseFailed) return '解析失敗（契約不符）'
  if (row.assessment === null) return `未取得（${unknown}）`
  return isStructureIdentified(row.assessment) ? '已識別' : '僅中介資料'
}

function artifactTone(row: LatentRow): string {
  if (row.parseFailed) return 'bad'
  if (row.assessment === null) return 'warn'
  return isStructureIdentified(row.assessment) ? 'good' : 'neutral'
}

function candidateText(row: LatentRow): string {
  if (row.assessment === null) return unknown
  return candidateListText(row.assessment)
}

function candidateListText(assessment: StructureAssessment): string {
  return assessment.structureCandidates.map((candidate) => STRUCTURE_CANDIDATE_LABELS[candidate]).join('、')
}

function dimensionText(value: number | null): string {
  return value === null ? unknown : String(value)
}

function selectRow(row: LatentRow): void {
  selectedId.value = row.versionId
}

onMounted(async () => {
  await load()
  if (selectedId.value === '' && rows.value.length > 0) selectedId.value = rows.value[0]?.versionId ?? ''
})

watch(selectedId, async (value) => {
  await replaceQueryState(router, route, { version: value === '' ? undefined : value })
})

watch(
  () => route.query.version,
  () => {
    selectedId.value = readQueryString(route.query, 'version')
  },
)
</script>

<template>
  <section>
    <div class="head">
      <div>
        <div class="eyebrow">發現 / SCREEN 20</div>
        <h1>隱藏變數探索</h1>
        <p class="muted">潛在狀態、內在維度及可識別性 · 專屬任務畫面設計</p>
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

    <p v-if="loading && snapshot === null" class="muted">載入中…</p>
    <p v-else-if="error !== ''" class="bad">{{ error }}</p>
    <template v-else-if="snapshot !== null">
      <div class="layout metric-grid">
        <section class="card metric-card">
          <div class="eyebrow">已識別版本</div>
          <div class="metric-value" :class="(summary?.identified ?? 0) > 0 ? 'good' : 'warn'">{{ summary?.identified ?? 0 }}</div>
          <p>後端同時給出內在維度、且結構候選不僅為「未判定」的版本數。</p>
        </section>
        <section class="card metric-card">
          <div class="eyebrow">結構產物可讀</div>
          <div class="metric-value">{{ summary?.artifactBacked ?? 0 }}</div>
          <p>帶有結構評估產物且成功解析的版本數。</p>
        </section>
        <section class="card metric-card">
          <div class="eyebrow">未取得產物</div>
          <div class="metric-value" :class="(summary?.missing ?? 0) > 0 ? 'warn' : 'good'">{{ summary?.missing ?? 0 }}</div>
          <p>PROFILE 尚未產生結構評估，或後端未揭露。</p>
        </section>
        <section class="card metric-card">
          <div class="eyebrow">契約不符</div>
          <div class="metric-value" :class="(summary?.parseFailed ?? 0) > 0 ? 'bad' : 'good'">{{ summary?.parseFailed ?? 0 }}</div>
          <p>產物存在但形狀不符契約而無法解析的版本數。</p>
        </section>
      </div>

      <div class="note scope-note">
        <div class="row compact">
          <span>讀取範圍</span>
          <span class="tag">{{ scope?.researchesRead ?? 0 }} 研究 / {{ scope?.versionsRead ?? 0 }} 版本</span>
        </div>
        <div class="row compact">
          <span>後端分頁</span>
          <span class="tag" :class="scope?.truncated === true ? 'warn' : 'good'">
            {{ scope?.truncated === true ? '仍有未讀取頁面，統計僅涵蓋已讀取範圍' : '已讀取完畢' }}
          </span>
        </div>
      </div>

      <div class="layout latent-grid">
        <section class="card">
          <h3>研究版本與結構評估</h3>
          <p v-if="rows.length === 0" class="muted">
            目前沒有可讀取的研究版本。請先建立研究版本並執行資料剖析（PROFILE），結構評估才會產生。
          </p>
          <table v-else>
            <thead>
              <tr>
                <th>研究 / 版本</th>
                <th>內在維度</th>
                <th>結構候選</th>
                <th>產物狀態</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="row in rows"
                :key="row.versionId"
                :class="{ active: row.versionId === selectedId }"
                @click="selectRow(row)"
              >
                <td>
                  <div>{{ row.researchName }}</div>
                  <div class="muted mono">{{ row.versionId }}</div>
                  <div class="muted">{{ row.versionStatus }}</div>
                </td>
                <td>{{ dimensionText(row.assessment?.intrinsicDimensionEstimate ?? null) }}</td>
                <td>{{ candidateText(row) }}</td>
                <td>
                  <span class="tag" :class="artifactTone(row)">{{ artifactLabel(row) }}</span>
                </td>
              </tr>
            </tbody>
          </table>
        </section>

        <section class="card">
          <h3>選定版本的結構評估</h3>
          <p v-if="selectedRow === null" class="muted">請從左側清單選擇一個研究版本。</p>
          <template v-else-if="selectedRow.assessment === null">
            <p class="muted">
              {{ selectedRow.parseFailed ? '結構評估產物存在，但形狀不符契約，無法解析。' : `此版本尚未取得結構評估產物（${unknown}）。` }}
            </p>
            <div class="row compact"><span>研究</span><span>{{ selectedRow.researchName }}</span></div>
            <div class="row compact"><span>研究版本</span><span class="mono">{{ selectedRow.versionId }}</span></div>
            <div class="row compact"><span>版本狀態</span><span class="tag">{{ selectedRow.versionStatus }}</span></div>
            <div class="row compact">
              <span>結構評估產物</span>
              <span class="mono">{{ selectedRow.artifactId ?? unknown }}</span>
            </div>
            <div class="note" style="margin-top: 12px;">
              內在維度與可識別性只能由結構評估產物推得；產物未取得或契約不符時，本頁不提供替代數字。
            </div>
          </template>
          <template v-else>
            <div class="row compact">
              <span>內在維度估計</span>
              <span class="tag" :class="isStructureIdentified(selectedRow.assessment) ? 'good' : 'warn'">
                {{ dimensionText(selectedRow.assessment.intrinsicDimensionEstimate) }}
              </span>
            </div>
            <div class="row compact">
              <span>結構候選</span>
              <span class="tag">
                {{ candidateListText(selectedRow.assessment) }}
              </span>
            </div>
            <div class="row compact">
              <span>時間基準</span>
              <span class="tag">{{ TIME_BASIS_LABELS[selectedRow.assessment.timeBasis] }}</span>
            </div>
            <div class="row compact">
              <span>週期性</span>
              <span class="tag">{{ PERIODICITY_LABELS[selectedRow.assessment.periodicity] }}</span>
            </div>
            <div class="row compact">
              <span>分析範圍</span>
              <span class="tag">{{ ANALYSIS_SCOPE_LABELS[selectedRow.assessment.analysisScope] }}</span>
            </div>
            <div class="row compact">
              <span>觀測維度 / 座標維度</span>
              <span class="tag">
                {{ selectedRow.assessment.observationDimension }} / {{ dimensionText(selectedRow.assessment.coordinateDimension) }}
              </span>
            </div>
            <div class="row compact">
              <span>表徵維度</span>
              <span class="tag">{{ selectedRow.assessment.representationDimension }}</span>
            </div>
            <div class="row compact">
              <span>存取等級</span>
              <span class="tag">{{ selectedRow.assessment.accessClass }}</span>
            </div>
            <div class="row compact">
              <span>方法清單</span>
              <span class="mono">{{ selectedRow.assessment.methodManifestId }}</span>
            </div>
            <div class="row compact">
              <span>fit 列集合雜湊</span>
              <span class="mono">{{ selectedRow.assessment.fitRowsHash ?? unknown }}</span>
            </div>
            <div class="row compact">
              <span>來源列數</span>
              <span class="tag">{{ selectedRow.assessment.sourceRowCount === null ? unknown : String(selectedRow.assessment.sourceRowCount) }}</span>
            </div>
            <div class="row compact">
              <span>不確定性理由</span>
              <span class="record-value">{{ selectedRow.assessment.uncertaintyReason }}</span>
            </div>

            <h3 style="margin-top: 18px;">來源欄位</h3>
            <p v-if="selectedRow.assessment.sourceColumns.length === 0" class="muted">後端未提供來源欄位（{{ unknown }}）。</p>
            <table v-else>
              <thead>
                <tr>
                  <th>欄位</th>
                  <th>物理型別</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="column in selectedRow.assessment.sourceColumns" :key="column.name">
                  <td class="mono">{{ column.name }}</td>
                  <td>{{ column.physicalType }}</td>
                </tr>
              </tbody>
            </table>

            <div class="actions" style="margin-top: 14px;">
              <RouterLink
                :to="{ name: 'research-workbench', params: { id: selectedRow.researchId }, query: withBackRef(route.fullPath, { version: selectedRow.versionId }) }"
              >
                <button type="button">打開研究工作台</button>
              </RouterLink>
            </div>
            <div class="note" style="margin-top: 12px;">
              後端目前一律回報內在維度為 null 與結構候選為「未判定」，代表尚未完成可識別性判定，並不代表資料為低維。
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

.scope-note {
  margin-bottom: 16px;
}

.latent-grid {
  grid-template-columns: 1.2fr 1fr;
}

.compact {
  padding: 8px 0;
}

tbody tr.active td {
  background: #132842;
}

.record-value {
  max-width: 62%;
  text-align: right;
  overflow-wrap: anywhere;
}

@media (max-width: 1200px) {
  .metric-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .latent-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 900px) {
  .metric-grid {
    grid-template-columns: 1fr;
  }
}
</style>
