<script setup lang="ts">
/**
 * 模型能力評估（SSOT SCREEN 34）：數學任務基準、延遲與成本。
 *
 * 基準分數、基準資料集與評分門檻需要後端基準端點，一律標示「未取得」；延遲與成本由任務已揭露的
 * 預算用量推導，因此本頁以「延遲與成本」為主要比較面，不把用量當成能力分數。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import ModelTabs from '../components/ModelTabs.vue'
import { readBackRef } from '../lib/navigationState'
import { readQueryString, replaceQueryState } from '../lib/queryState'
import { useModelCenter } from '../lib/useModelCenter'
import {
  MODEL_UNKNOWN,
  buildCapabilityRows,
  summarizeCapability,
  type CapabilityRow,
} from '../lib/modelCenter'

const route = useRoute()
const router = useRouter()
const { center, loading, error, load } = useModelCenter()

const selectedClass = ref(readQueryString(route.query, 'class'))

const rows = computed<CapabilityRow[]>(() => (center.value === null ? [] : buildCapabilityRows(center.value)))
const summary = computed(() => summarizeCapability(rows.value))
const selectedRow = computed<CapabilityRow | null>(
  () => rows.value.find((row) => row.taskClass === selectedClass.value) ?? null,
)
const backRef = computed(() => readBackRef(route.query))

function numberText(value: number | null): string {
  return value === null ? MODEL_UNKNOWN : String(value)
}

function secondsText(value: number | null): string {
  return value === null ? MODEL_UNKNOWN : `${value.toFixed(2)} s`
}

function selectRow(row: CapabilityRow): void {
  selectedClass.value = row.taskClass
}

onMounted(async () => {
  await load()
  if (selectedClass.value === '' && rows.value.length > 0) selectedClass.value = rows.value[0]?.taskClass ?? ''
})

watch(selectedClass, async (value) => {
  await replaceQueryState(router, route, { class: value === '' ? undefined : value })
})

watch(
  () => route.query.class,
  () => {
    selectedClass.value = readQueryString(route.query, 'class')
  },
)

watch(rows, (value) => {
  if (value.length === 0) {
    selectedClass.value = ''
    return
  }
  if (value.some((row) => row.taskClass === selectedClass.value)) return
  selectedClass.value = value[0]?.taskClass ?? ''
})
</script>

<template>
  <section>
    <ModelTabs />

    <div class="head">
      <div>
        <div class="eyebrow">模型 / SCREEN 34</div>
        <h1>模型能力評估</h1>
        <p class="muted">
          專屬任務畫面設計｜數學任務基準、延遲與成本：基準分數需後端基準端點，一律「未取得」；本頁只比較已揭露的延遲與 Token 成本。
        </p>
      </div>
      <div class="actions">
        <button v-if="backRef !== ''" type="button" @click="router.push(backRef)">返回來源頁</button>
        <button type="button" @click="load">重新載入</button>
        <RouterLink :to="{ name: 'model-storage' }">
          <button type="button" class="primary">前往 Token 與儲存</button>
        </RouterLink>
      </div>
    </div>

    <p v-if="loading && center === null" class="muted">載入中…</p>
    <p v-else-if="error !== ''" class="bad">{{ error }}</p>
    <template v-else-if="center !== null">
      <div class="layout metric-grid">
        <section class="card metric-card">
          <div class="eyebrow">評估任務類別</div>
          <div class="metric-value">{{ summary.classes }}</div>
          <p>實際讀到任務的類別數；沒有任務的類別不列入評估。</p>
        </section>
        <section class="card metric-card">
          <div class="eyebrow">樣本數（任務）</div>
          <div class="metric-value">{{ summary.samples }}</div>
          <p>可比較的任務樣本數，代表延遲與成本的觀測筆數。</p>
        </section>
        <section class="card metric-card">
          <div class="eyebrow">成功任務</div>
          <div class="metric-value" :class="summary.successes > 0 ? 'good' : 'warn'">{{ summary.successes }}</div>
          <p>狀態為已完成的任務數；未完成不計入成本可比較樣本。</p>
        </section>
        <section class="card metric-card">
          <div class="eyebrow">Token 成本合計</div>
          <div class="metric-value">{{ numberText(summary.tokens) }}</div>
          <p>只加總已揭露的 Token；全部未揭露時顯示「未取得」。</p>
        </section>
      </div>

      <div class="layout unknown-grid">
        <section class="card unknown-card">
          <div class="eyebrow">基準分數</div>
          <p class="unknown-value">{{ MODEL_UNKNOWN }}</p>
        </section>
        <section class="card unknown-card">
          <div class="eyebrow">基準題庫與資料集</div>
          <p class="unknown-value">{{ MODEL_UNKNOWN }}</p>
        </section>
        <section class="card unknown-card">
          <div class="eyebrow">評分門檻與排名</div>
          <p class="unknown-value">{{ MODEL_UNKNOWN }}</p>
        </section>
      </div>

      <div class="layout compare-grid">
        <section class="card">
          <h3>延遲與成本比較</h3>
          <p class="muted">以任務類別為列；延遲與 Token 只由已揭露用量推導，基準分數欄位不在此表。</p>
          <p v-if="rows.length === 0" class="muted">目前沒有可比較的任務樣本，評估表會保持空白而不是顯示推測分數。</p>
          <table v-else>
            <thead>
              <tr>
                <th>任務類別</th>
                <th>樣本</th>
                <th>成功</th>
                <th>基準分數</th>
                <th>平均延遲</th>
                <th>最大延遲</th>
                <th>Token</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="row in rows"
                :key="row.taskClass"
                :class="{ active: row.taskClass === selectedClass }"
                @click="selectRow(row)"
              >
                <td>
                  <div>{{ row.label }}</div>
                  <div class="muted mono">{{ row.taskClass }}</div>
                </td>
                <td>{{ row.sampleCount }}</td>
                <td>{{ row.successCount }}</td>
                <td class="muted">{{ row.benchmarkScore }}</td>
                <td>{{ secondsText(row.averageWallSeconds) }}</td>
                <td>{{ secondsText(row.maxWallSeconds) }}</td>
                <td>{{ numberText(row.tokens) }}</td>
              </tr>
            </tbody>
          </table>
        </section>

        <section class="card detail-card">
          <h3>選定類別評估</h3>
          <p v-if="selectedRow === null" class="muted">請從左側比較表選擇一個任務類別。</p>
          <template v-else>
            <div class="row compact">
              <span>任務類別</span>
              <span class="tag">{{ selectedRow.label }}</span>
            </div>
            <div class="row compact">
              <span>基準分數</span>
              <span class="muted">{{ selectedRow.benchmarkScore }}</span>
            </div>
            <div class="row compact">
              <span>候選模型</span>
              <span class="muted">{{ selectedRow.candidateModel }}</span>
            </div>
            <div class="row compact">
              <span>樣本 / 成功</span>
              <span>{{ selectedRow.sampleCount }} / {{ selectedRow.successCount }}</span>
            </div>
            <div class="row compact">
              <span>平均延遲</span>
              <span>{{ secondsText(selectedRow.averageWallSeconds) }}</span>
            </div>
            <div class="row compact">
              <span>最大延遲</span>
              <span>{{ secondsText(selectedRow.maxWallSeconds) }}</span>
            </div>
            <div class="row compact">
              <span>Token 成本（合計）</span>
              <span>{{ numberText(selectedRow.tokens) }}</span>
            </div>
            <div class="note" style="margin-top: 12px;">
              這一頁不宣告任何模型能力優劣：後端沒有基準分數，能力結論一律「未取得」，延遲與成本僅為用量觀測。
            </div>
          </template>
        </section>
      </div>

      <section class="card note-card">
        <h3>目前邊界</h3>
        <p>
          後端沒有基準測試、評分或模型排名端點，因此基準分數與評分門檻一律「未取得」；本頁只比較由任務預算用量推導的延遲與 Token 成本，不以推測值補上能力差異。
        </p>
      </section>
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
  font-size: 28px;
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

.compare-grid {
  grid-template-columns: 1.4fr 1fr;
}

.note-card {
  margin-top: 16px;
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

@media (max-width: 1200px) {
  .metric-grid,
  .unknown-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .compare-grid {
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
