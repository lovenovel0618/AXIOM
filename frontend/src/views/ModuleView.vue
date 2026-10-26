<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { listRunCandidates } from '../api/candidates'
import { listDatasets, listVersions } from '../api/datasets'
import { listResearchVersionRuns, listResearchVersions, listResearches } from '../api/research'
import { checkReadiness } from '../health'
import { loadModuleDashboard, type ModuleDashboard, type ModuleName } from '../lib/moduleDashboard'
import { describeError } from '../lib/messages'
import { client } from '../lib/session'

const route = useRoute()
const dashboard = ref<ModuleDashboard | null>(null)
const loading = ref(false)
const error = ref('')

const moduleName = computed<ModuleName>(() => {
  const name = typeof route.name === 'string' ? route.name : 'overview'
  switch (name) {
    case 'overview':
    case 'discoveries':
    case 'verification':
    case 'memory':
    case 'model':
    case 'training':
    case 'settings':
      return name
    default:
      return 'overview'
  }
})

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    dashboard.value = await loadModuleDashboard(moduleName.value, {
      checkReadiness: () => checkReadiness(),
      listResearches: (limit) => listResearches(client, limit),
      listResearchVersions: (researchId, limit) => listResearchVersions(client, researchId, limit),
      listResearchVersionRuns: (versionId, limit) => listResearchVersionRuns(client, versionId, limit),
      listDatasets: (limit) => listDatasets(client, '', limit),
      listVersions: (datasetId, limit) => listVersions(client, datasetId, limit),
      listRunCandidates: (runId, limit) => listRunCandidates(client, runId, { limit }),
    })
  } catch (cause) {
    dashboard.value = null
    error.value = describeError(cause)
  } finally {
    loading.value = false
  }
}

onMounted(load)
watch(moduleName, async () => {
  await load()
})
</script>

<template>
  <section>
    <div v-if="dashboard !== null" class="head">
      <div>
        <div class="eyebrow">{{ dashboard.section }} / MODULE</div>
        <h1>{{ dashboard.title }}</h1>
        <p class="muted">{{ dashboard.summary }}</p>
      </div>
      <div class="actions">
        <button type="button" @click="load">重新載入</button>
        <RouterLink v-for="action in dashboard.actions" :key="action.label" :to="action.to">
          <button type="button" class="primary">{{ action.label }}</button>
        </RouterLink>
      </div>
    </div>

    <p v-if="loading && dashboard === null" class="muted">載入中…</p>
    <p v-else-if="error !== ''" class="bad">{{ error }}</p>
    <template v-else-if="dashboard !== null">
      <div class="layout metric-grid">
        <section v-for="metric in dashboard.metrics" :key="metric.label" class="card metric-card">
          <div class="eyebrow">{{ metric.label }}</div>
          <div class="metric-value" :class="metric.tone">{{ metric.value }}</div>
          <p>{{ metric.detail }}</p>
        </section>
      </div>

      <div class="layout cols3">
        <section v-for="list in dashboard.lists" :key="list.title" class="card">
          <h3>{{ list.title }}</h3>
          <p v-if="list.items.length === 0" class="muted">{{ list.empty }}</p>
          <div v-else class="list-rows">
            <RouterLink
              v-for="item in list.items"
              :key="`${list.title}:${item.title}:${item.subtitle}`"
              :to="item.to ?? { name: moduleName }"
              class="module-link"
            >
              <div>
                <strong>{{ item.title }}</strong>
                <div class="muted mono">{{ item.subtitle }}</div>
              </div>
              <span class="tag">{{ item.badge }}</span>
            </RouterLink>
          </div>
        </section>
      </div>

      <section class="card module-note">
        <h3>目前邊界</h3>
        <p>{{ dashboard.note }}</p>
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
  min-height: 158px;
}

.metric-value {
  font-size: 30px;
  font-weight: 700;
  margin: 10px 0 8px;
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

.module-link:hover {
  border-color: #3673c7;
  background: #132842;
}

.module-note {
  margin-top: 16px;
}

@media (max-width: 1200px) {
  .metric-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 900px) {
  .metric-grid {
    grid-template-columns: 1fr;
  }
}
</style>
