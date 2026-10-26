<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { filterModuleList, flattenModuleLists, type ModuleListSelection, sameSelection } from '../lib/modulePageUtils'
import { useModulePage } from '../lib/useModulePage'

const { dashboard, loading, error, load } = useModulePage('memory')
const keyword = ref('')
const selected = ref<ModuleListSelection | null>(null)

const primary = computed(() => {
  const list = dashboard.value?.lists[0] ?? null
  return list === null ? null : filterModuleList(list, keyword.value)
})
const secondary = computed(() =>
  (dashboard.value?.lists.slice(1) ?? []).map((list) => filterModuleList(list, keyword.value)),
)
const visibleItems = computed<ModuleListSelection[]>(() =>
  flattenModuleLists([...(primary.value === null ? [] : [primary.value]), ...secondary.value]),
)

onMounted(load)

watch(visibleItems, (items) => {
  const next = items[0] ?? null
  const current = items.find((item) => sameSelection(item, selected.value)) ?? null
  selected.value = current ?? next
})
</script>

<template>
  <section>
    <div v-if="dashboard !== null" class="head">
      <div>
        <div class="eyebrow">{{ dashboard.section }} / MEMORY</div>
        <h1>{{ dashboard.title }}</h1>
        <p class="muted">{{ dashboard.summary }}</p>
      </div>
      <div class="actions">
        <input v-model="keyword" class="search" placeholder="搜尋研究 / 任務 / 證據 ID">
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

      <div class="layout memory-grid">
        <section v-if="primary !== null" class="card primary-card">
          <h3>{{ primary.title }}</h3>
          <p v-if="primary.items.length === 0" class="muted">{{ primary.empty }}</p>
          <div v-else class="list-rows">
            <button
              v-for="item in primary.items"
              :key="`${primary.title}:${item.title}:${item.subtitle}`"
              class="module-link"
              type="button"
              :class="{ active: sameSelection({ listTitle: primary.title, item }, selected) }"
              @click="selected = { listTitle: primary.title, item }"
            >
              <div>
                <strong>{{ item.title }}</strong>
                <div class="muted mono">{{ item.subtitle }}</div>
              </div>
              <span class="tag">{{ item.badge }}</span>
            </button>
          </div>
        </section>

        <div class="side-stack">
          <section v-for="list in secondary" :key="list.title" class="card">
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
        </div>
      </div>

      <section class="card detail-card">
        <h3>記錄詳情</h3>
        <p v-if="selected === null" class="muted">目前沒有符合條件的記錄。</p>
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
            <RouterLink :to="selected.item.to ?? { name: 'memory' }">
              <button type="button" class="primary">打開來源頁</button>
            </RouterLink>
          </div>
        </template>
      </section>

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

.memory-grid {
  grid-template-columns: minmax(0, 1.4fr) 360px;
}

.side-stack,
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

  .memory-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 900px) {
  .metric-grid {
    grid-template-columns: 1fr;
  }
}
</style>
