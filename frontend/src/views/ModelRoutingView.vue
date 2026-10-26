<script setup lang="ts">
/**
 * 模型路由（SSOT SCREEN 33）：任務分類、候選模型與路由策略。
 *
 * 任務分類由任務型別（INGEST／PROFILE／SEARCH／FIT／VALIDATE）對照，是後端已揭露的欄位；
 * 候選模型與路由策略沒有對應端點，一律標示「未取得」，不以任務型別冒充模型選擇結果。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import ModelTabs from '../components/ModelTabs.vue'
import { readBackRef, withBackRef } from '../lib/navigationState'
import { readQueryString, replaceQueryState } from '../lib/queryState'
import { useModelCenter } from '../lib/useModelCenter'
import {
  MODEL_UNKNOWN,
  RUN_STATUS_LABELS,
  TASK_CLASS_LABELS,
  buildModelLoads,
  buildTaskClasses,
  summarizeTaskClasses,
  type ModelLoadRow,
  type TaskClassRow,
} from '../lib/modelCenter'

const route = useRoute()
const router = useRouter()
const { center, loading, error, load } = useModelCenter()

const selectedClass = ref(readQueryString(route.query, 'class'))

const classes = computed<TaskClassRow[]>(() => (center.value === null ? [] : buildTaskClasses(center.value)))
const loads = computed<ModelLoadRow[]>(() => (center.value === null ? [] : buildModelLoads(center.value)))
const summary = computed(() => summarizeTaskClasses(classes.value))
const selectedRow = computed<TaskClassRow | null>(
  () => classes.value.find((row) => row.taskClass === selectedClass.value) ?? null,
)
const classRuns = computed<ModelLoadRow[]>(() => {
  const row = selectedRow.value
  if (row === null) return []
  return loads.value.filter((load) => load.taskClass === row.taskClass)
})
const backRef = computed(() => readBackRef(route.query))

function numberText(value: number | null): string {
  return value === null ? MODEL_UNKNOWN : String(value)
}

function secondsText(value: number | null): string {
  return value === null ? MODEL_UNKNOWN : `${String(value)} s`
}

function selectRow(row: TaskClassRow): void {
  selectedClass.value = row.taskClass
}

onMounted(async () => {
  await load()
  if (selectedClass.value === '' && classes.value.length > 0) selectedClass.value = classes.value[0]?.taskClass ?? ''
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

watch(classes, (value) => {
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
        <div class="eyebrow">模型 / SCREEN 33</div>
        <h1>模型路由</h1>
        <p class="muted">
          專屬任務畫面設計｜任務分類、候選模型與路由策略：任務分類只由已讀取任務的型別推導；候選模型與路由策略後端未揭露時一律「未取得」。
        </p>
      </div>
      <div class="actions">
        <button v-if="backRef !== ''" type="button" @click="router.push(backRef)">返回來源頁</button>
        <button type="button" @click="load">重新載入</button>
        <RouterLink :to="{ name: 'model' }">
          <button type="button" class="primary">前往模型管理</button>
        </RouterLink>
      </div>
    </div>

    <p v-if="loading && center === null" class="muted">載入中…</p>
    <p v-else-if="error !== ''" class="bad">{{ error }}</p>
    <template v-else-if="center !== null">
      <div class="layout metric-grid">
        <section class="card metric-card">
          <div class="eyebrow">任務類別</div>
          <div class="metric-value">{{ summary.classes }}</div>
          <p>只計算實際讀到任務的類別；沒有任務的類別不補造。</p>
        </section>
        <section class="card metric-card">
          <div class="eyebrow">已讀取任務</div>
          <div class="metric-value">{{ summary.runs }}</div>
          <p>本頁實際讀取到的任務數，後端仍有未讀取頁面時統計範圍以此為限。</p>
        </section>
        <section class="card metric-card">
          <div class="eyebrow">進行中</div>
          <div class="metric-value">{{ summary.active }}</div>
          <p>狀態為排隊中或執行中的任務數。</p>
        </section>
        <section class="card metric-card">
          <div class="eyebrow">失敗</div>
          <div class="metric-value" :class="summary.failed > 0 ? 'bad' : 'good'">{{ summary.failed }}</div>
          <p>狀態為失敗的任務數；停止理由未揭露時不推測原因。</p>
        </section>
      </div>

      <div class="layout unknown-grid">
        <section class="card unknown-card">
          <div class="eyebrow">候選模型</div>
          <p class="unknown-value">{{ MODEL_UNKNOWN }}</p>
        </section>
        <section class="card unknown-card">
          <div class="eyebrow">路由策略</div>
          <p class="unknown-value">{{ MODEL_UNKNOWN }}</p>
        </section>
        <section class="card unknown-card">
          <div class="eyebrow">任務 → 模型對應</div>
          <p class="unknown-value">{{ MODEL_UNKNOWN }}</p>
        </section>
      </div>

      <div class="layout routing-grid">
        <section class="card">
          <h3>任務分類</h3>
          <p class="muted">分類由任務型別對照；每個類別的資源用量只加總已揭露值。</p>
          <p v-if="classes.length === 0" class="muted">目前沒有可讀取的任務，路由分類會保持空白而不是顯示推測內容。</p>
          <table v-else>
            <thead>
              <tr>
                <th>任務類別</th>
                <th>任務數</th>
                <th>進行中</th>
                <th>失敗</th>
                <th>Token</th>
                <th>耗時</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="row in classes"
                :key="row.taskClass"
                :class="{ active: row.taskClass === selectedClass }"
                @click="selectRow(row)"
              >
                <td>
                  <div>{{ row.label }}</div>
                  <div class="muted mono">{{ row.taskClass }}</div>
                </td>
                <td>{{ row.runCount }}</td>
                <td>{{ row.activeCount }}</td>
                <td>
                  <span class="tag" :class="row.failedCount > 0 ? 'bad' : ''">{{ row.failedCount }}</span>
                </td>
                <td>{{ numberText(row.tokens) }}</td>
                <td>{{ secondsText(row.elapsedWallSeconds) }}</td>
              </tr>
            </tbody>
          </table>
        </section>

        <section class="card detail-card">
          <h3>選定任務類別</h3>
          <p v-if="selectedRow === null" class="muted">請從左側清單選擇一個任務類別。</p>
          <template v-else>
            <div class="row compact">
              <span>任務類別</span>
              <span class="tag">{{ selectedRow.label }}</span>
            </div>
            <div class="row compact">
              <span>任務數 / 進行中 / 失敗</span>
              <span>{{ selectedRow.runCount }} / {{ selectedRow.activeCount }} / {{ selectedRow.failedCount }}</span>
            </div>
            <div class="row compact">
              <span>候選模型</span>
              <span class="muted">{{ selectedRow.candidateModels }}</span>
            </div>
            <div class="row compact">
              <span>路由策略</span>
              <span class="muted">{{ selectedRow.routingStrategy }}</span>
            </div>
            <div class="row compact">
              <span>Token 合計</span>
              <span>{{ numberText(selectedRow.tokens) }}</span>
            </div>
            <div class="row compact">
              <span>耗時合計</span>
              <span>{{ secondsText(selectedRow.elapsedWallSeconds) }}</span>
            </div>

            <h3 style="margin-top: 18px;">此類別的任務</h3>
            <p v-if="classRuns.length === 0" class="muted">此類別目前沒有已讀取任務。</p>
            <div v-else class="run-rows">
              <div v-for="run in classRuns" :key="run.runId" class="run-row">
                <div>
                  <strong>{{ run.researchName }}</strong>
                  <div class="muted mono">{{ run.runId }}</div>
                </div>
                <div class="run-actions">
                  <span class="tag" :class="run.status === 'FAILED' ? 'bad' : run.status === 'SUCCEEDED' ? 'good' : ''">
                    {{ RUN_STATUS_LABELS[run.status] }}
                  </span>
                  <RouterLink
                    :to="{ name: 'run', params: { id: run.runId }, query: withBackRef(route.fullPath) }"
                  >
                    <button type="button">詳情</button>
                  </RouterLink>
                </div>
              </div>
            </div>
          </template>
        </section>
      </div>

      <section class="card note-card">
        <h3>目前邊界</h3>
        <p>
          後端沒有模型路由端點，也沒有候選模型清單，因此本頁只呈現任務分類與其已揭露用量；路由策略與任務到模型的對應一律「未取得」。任務類別標籤僅為對照，不代表後端已選擇特定模型。
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

.routing-grid {
  grid-template-columns: 1.3fr 1fr;
}

.note-card {
  margin-top: 16px;
}

.compact {
  padding: 8px 0;
}

.run-rows {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.run-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  border: 1px solid #27405d;
  border-radius: 10px;
  padding: 10px 12px;
  background: #0e1e31;
}

.run-actions {
  display: flex;
  align-items: center;
  gap: 8px;
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

  .routing-grid {
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
