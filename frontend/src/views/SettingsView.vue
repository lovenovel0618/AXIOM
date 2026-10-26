<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { filterModuleList, flattenModuleLists, type ModuleListSelection, sameSelection } from '../lib/modulePageUtils'
import { readQueryString, replaceQueryState, selectionKey } from '../lib/queryState'
import { useModulePage } from '../lib/useModulePage'

const route = useRoute()
const router = useRouter()
const { dashboard, loading, error, load } = useModulePage('settings')
const keyword = ref(readQueryString(route.query, 'q'))
const selected = ref<ModuleListSelection | null>(null)
const systemSignals = computed(() => {
  const list = dashboard.value?.lists[0] ?? null
  return list === null ? null : filterModuleList(list, keyword.value)
})
const auditLists = computed(() =>
  (dashboard.value?.lists.slice(1) ?? []).map((list) => filterModuleList(list, keyword.value)),
)
const visibleItems = computed(() =>
  flattenModuleLists([...(systemSignals.value === null ? [] : [systemSignals.value]), ...auditLists.value]),
)

function resolveSelected(items: ModuleListSelection[]): ModuleListSelection | null {
  const focus = readQueryString(route.query, 'focus')
  const fromQuery = items.find((item) => selectionKey(item.listTitle, item.item.subtitle) === focus) ?? null
  const current = items.find((item) => sameSelection(item, selected.value)) ?? null
  return fromQuery ?? current ?? items[0] ?? null
}

onMounted(load)

watch(visibleItems, (items) => {
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
    selected.value = resolveSelected(visibleItems.value)
  },
)
</script>

<template>
  <section>
    <div v-if="dashboard !== null" class="head">
      <div>
        <div class="eyebrow">{{ dashboard.section }} / SETTINGS</div>
        <h1>{{ dashboard.title }}</h1>
        <p class="muted">{{ dashboard.summary }}</p>
      </div>
      <div class="actions">
        <input v-model="keyword" class="search" placeholder="搜尋系統訊號 / 任務 / 版本">
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

      <div class="layout settings-grid">
        <section v-if="systemSignals !== null" class="card">
          <h3>{{ systemSignals.title }}</h3>
          <p v-if="systemSignals.items.length === 0" class="muted">{{ systemSignals.empty }}</p>
          <div v-else class="signal-list">
            <button
              v-for="item in systemSignals.items"
              :key="`${systemSignals.title}:${item.title}:${item.subtitle}`"
              class="signal-item"
              type="button"
              :class="{ active: sameSelection({ listTitle: systemSignals.title, item }, selected) }"
              @click="selected = { listTitle: systemSignals.title, item }"
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
          <section v-for="list in auditLists" :key="list.title" class="card">
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
        <h3>訊號詳情</h3>
        <p v-if="selected === null" class="muted">目前沒有符合條件的系統訊號。</p>
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
            <RouterLink v-if="selected.item.to !== undefined" :to="selected.item.to">
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

.settings-grid {
  grid-template-columns: minmax(0, 1.3fr) 360px;
}

.signal-list,
.side-stack,
.list-rows {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.signal-item,
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

.signal-item.active,
.module-link.active {
  border-color: #3673c7;
  background: #132842;
}

.module-link:hover {
  border-color: #3673c7;
  background: #132842;
}

.signal-item:hover {
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

  .settings-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 900px) {
  .metric-grid {
    grid-template-columns: 1fr;
  }
}
</style>
