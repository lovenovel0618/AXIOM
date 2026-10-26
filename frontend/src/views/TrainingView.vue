<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { filterModuleList } from '../lib/modulePageUtils'
import { readQueryString, replaceQueryState } from '../lib/queryState'
import { useModulePage } from '../lib/useModulePage'

const route = useRoute()
const router = useRouter()
const { dashboard, loading, error, load } = useModulePage('training')
const keyword = ref(readQueryString(route.query, 'q'))
const sourceFilter = ref<'ALL' | 'READY'>(readQueryString(route.query, 'filter') === 'READY' ? 'READY' : 'ALL')

const sources = computed(() => {
  const list = dashboard.value?.lists[2] ?? null
  if (list === null) return null
  const filtered = filterModuleList(list, keyword.value)
  return {
    ...filtered,
    items:
      sourceFilter.value === 'READY'
        ? filtered.items.filter((item) => item.badge.includes('READY'))
        : filtered.items,
  }
})
const topLists = computed(() =>
  (dashboard.value?.lists.slice(0, 2) ?? []).map((list) => filterModuleList(list, keyword.value)),
)

onMounted(load)

watch(keyword, async (value) => {
  await replaceQueryState(router, route, { q: value })
})

watch(sourceFilter, async (value) => {
  await replaceQueryState(router, route, { filter: value === 'ALL' ? undefined : value })
})

watch(
  () => route.query,
  () => {
    keyword.value = readQueryString(route.query, 'q')
    sourceFilter.value = readQueryString(route.query, 'filter') === 'READY' ? 'READY' : 'ALL'
  },
)
</script>

<template>
  <section>
    <div v-if="dashboard !== null" class="head">
      <div>
        <div class="eyebrow">{{ dashboard.section }} / TRAINING</div>
        <h1>{{ dashboard.title }}</h1>
        <p class="muted">{{ dashboard.summary }}</p>
      </div>
      <div class="actions">
        <input v-model="keyword" class="search" placeholder="搜尋資料集 / 版本 / 產物">
        <select v-model="sourceFilter" class="filter">
          <option value="ALL">全部來源</option>
          <option value="READY">只看可分析</option>
        </select>
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

      <div class="layout training-grid">
        <div class="top-stack">
          <section v-for="list in topLists" :key="list.title" class="card">
            <h3>{{ list.title }}</h3>
            <p v-if="list.items.length === 0" class="muted">{{ list.empty }}</p>
            <div v-else class="list-rows">
              <RouterLink
                v-for="item in list.items"
                :key="`${list.title}:${item.title}:${item.subtitle}`"
                :to="item.to ?? { name: 'training' }"
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

        <section v-if="sources !== null" class="card source-card">
          <h3>{{ sources.title }}</h3>
          <p v-if="sources.items.length === 0" class="muted">{{ sources.empty }}</p>
          <table v-else>
            <thead>
              <tr>
                <th>來源</th>
                <th>識別碼</th>
                <th>狀態</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in sources.items" :key="`${sources.title}:${item.title}:${item.subtitle}`">
                <td>
                  <RouterLink :to="item.to ?? { name: 'training' }">{{ item.title }}</RouterLink>
                </td>
                <td class="mono">{{ item.subtitle }}</td>
                <td><span class="tag">{{ item.badge }}</span></td>
              </tr>
            </tbody>
          </table>
        </section>
      </div>

      <section class="card note-card">
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

.training-grid {
  grid-template-columns: minmax(0, 1fr) minmax(0, 1.15fr);
}

.top-stack,
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

.search {
  min-width: 240px;
}

.filter {
  min-width: 150px;
}

.note-card {
  margin-top: 16px;
}

@media (max-width: 1200px) {
  .metric-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .training-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 900px) {
  .metric-grid {
    grid-template-columns: 1fr;
  }
}
</style>
