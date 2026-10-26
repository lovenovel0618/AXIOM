<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { filterModuleList, flattenModuleLists, type ModuleListSelection, sameSelection } from '../lib/modulePageUtils'
import { readQueryString, replaceQueryState, selectionKey } from '../lib/queryState'
import { useModulePage } from '../lib/useModulePage'

const route = useRoute()
const router = useRouter()
const { dashboard, loading, error, load } = useModulePage('model')
const keyword = ref(readQueryString(route.query, 'q'))
const selected = ref<ModuleListSelection | null>(null)

const filteredLists = computed(() =>
  (dashboard.value?.lists ?? []).map((list) => filterModuleList(list, keyword.value)),
)
const selectedItems = computed(() => flattenModuleLists(filteredLists.value))
const runTypeMetrics = computed(() => {
  const lists = filteredLists.value
  return [
    { label: 'PROFILE', count: lists[0]?.items.filter((item) => item.title.startsWith('PROFILE')).length ?? 0 },
    { label: 'SEARCH', count: lists[0]?.items.filter((item) => item.title.startsWith('SEARCH')).length ?? 0 },
    { label: 'VALIDATE', count: lists[0]?.items.filter((item) => item.title.startsWith('VALIDATE')).length ?? 0 },
  ]
})

function resolveSelected(items: ModuleListSelection[]): ModuleListSelection | null {
  const focus = readQueryString(route.query, 'focus')
  const fromQuery = items.find((item) => selectionKey(item.listTitle, item.item.subtitle) === focus) ?? null
  const current = items.find((item) => sameSelection(item, selected.value)) ?? null
  return fromQuery ?? current ?? items[0] ?? null
}

onMounted(load)

watch(selectedItems, (items) => {
  selected.value = resolveSelected(items)
})

watch(keyword, async (value) => {
  await replaceQueryState(router, route, { q: value })
})

watch(
  selected,
  async (value) => {
    await replaceQueryState(router, route, {
      focus: value === null ? undefined : selectionKey(value.listTitle, value.item.subtitle),
    })
  },
  { deep: true },
)

watch(
  () => route.query,
  () => {
    keyword.value = readQueryString(route.query, 'q')
    selected.value = resolveSelected(selectedItems.value)
  },
)
</script>

<template>
  <section>
    <div v-if="dashboard !== null" class="head">
      <div>
        <div class="eyebrow">{{ dashboard.section }} / MODEL</div>
        <h1>{{ dashboard.title }}</h1>
        <p class="muted">{{ dashboard.summary }}</p>
      </div>
      <div class="actions">
        <input v-model="keyword" class="search" placeholder="搜尋模型工作負載 / 研究版本">
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

      <div class="layout model-grid">
        <section class="card">
          <h3>工作負載分布</h3>
          <div class="load-grid">
            <div v-for="entry in runTypeMetrics" :key="entry.label" class="load-card">
              <div class="eyebrow">{{ entry.label }}</div>
              <strong class="load-value">{{ entry.count }}</strong>
            </div>
          </div>
          <div class="note" style="margin-top: 16px;">
            目前前台沒有獨立模型 registry，所以模型頁先把實際工作負載訊號拉出來看，而不是假造模型清單。
          </div>
        </section>

        <section v-for="list in filteredLists" :key="list.title" class="card">
          <h3>{{ list.title }}</h3>
          <p v-if="list.items.length === 0" class="muted">{{ list.empty }}</p>
          <div v-else class="list-rows">
            <button
              v-for="item in list.items"
              :key="`${list.title}:${item.title}:${item.subtitle}`"
              class="module-link"
              type="button"
              :class="{ active: sameSelection({ listTitle: list.title, item }, selected) }"
              @click="selected = { listTitle: list.title, item }"
            >
              <div>
                <strong>{{ item.title }}</strong>
                <div class="muted mono">{{ item.subtitle }}</div>
              </div>
              <span class="tag">{{ item.badge }}</span>
            </button>
          </div>
        </section>

        <section class="card detail-card">
          <h3>工作負載詳情</h3>
          <p v-if="selected === null" class="muted">目前沒有符合條件的工作負載。</p>
          <template v-else>
            <div class="row compact">
              <span>來源</span>
              <span class="tag">{{ selected.listTitle }}</span>
            </div>
            <div class="row compact">
              <span>標題</span>
              <span>{{ selected.item.title }}</span>
            </div>
            <div class="row compact">
              <span>識別碼</span>
              <span class="mono">{{ selected.item.subtitle }}</span>
            </div>
            <div class="row compact">
              <span>狀態</span>
              <span class="tag">{{ selected.item.badge }}</span>
            </div>
            <div class="actions" style="margin-top: 16px;">
              <RouterLink :to="selected.item.to ?? { name: 'model' }">
                <button type="button" class="primary">打開來源頁</button>
              </RouterLink>
            </div>
          </template>
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

.list-rows {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.model-grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
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
  text-align: left;
  width: 100%;
}

.module-link.active {
  border-color: #3673c7;
  background: #132842;
}

.module-link:hover {
  border-color: #3673c7;
  background: #132842;
}

.search {
  min-width: 240px;
}

.load-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.load-card {
  border: 1px solid #27405d;
  border-radius: 10px;
  padding: 14px;
  background: #0e1e31;
}

.load-value {
  font-size: 28px;
}

.detail-card,
.note-card {
  margin-top: 16px;
}

.compact {
  padding: 10px 0;
}

@media (max-width: 1200px) {
  .metric-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .load-grid,
  .model-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 900px) {
  .metric-grid {
    grid-template-columns: 1fr;
  }
}
</style>
