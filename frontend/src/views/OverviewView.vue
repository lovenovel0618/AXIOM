<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { flattenModuleLists, type ModuleListSelection, sameSelection } from '../lib/modulePageUtils'
import { readQueryString, replaceQueryState, selectionKey } from '../lib/queryState'
import { useModulePage } from '../lib/useModulePage'

const route = useRoute()
const router = useRouter()
const { dashboard, loading, error, load } = useModulePage('overview')
const selected = ref<ModuleListSelection | null>(null)

const quickRoutes = [
  { label: '研究活動中心', route: { name: 'activity' as const }, tone: 'neutral' },
  { label: '待處理事件', route: { name: 'pending' as const }, tone: 'warn' },
  { label: '資源監控', route: { name: 'resources' as const }, tone: 'neutral' },
  { label: '研究清單', route: { name: 'research-list' as const }, tone: 'good' },
  { label: '資料集管理', route: { name: 'datasets' as const }, tone: 'neutral' },
  { label: '發現中心', route: { name: 'discoveries' as const }, tone: 'warn' },
  { label: '驗證中心', route: { name: 'verification' as const }, tone: 'neutral' },
]

const recentActivity = computed<ModuleListSelection[]>(() => {
  if (dashboard.value === null) return []
  return flattenModuleLists(dashboard.value.lists)
})

function resolveSelected(items: ModuleListSelection[]): ModuleListSelection | null {
  const focus = readQueryString(route.query, 'focus')
  const fromQuery = items.find((item) => selectionKey(item.listTitle, item.item.subtitle) === focus) ?? null
  const current = items.find((item) => sameSelection(item, selected.value)) ?? null
  return fromQuery ?? current ?? items[0] ?? null
}

onMounted(load)

watch(recentActivity, (items) => {
  selected.value = resolveSelected(items)
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
  () => route.query.focus,
  () => {
    selected.value = resolveSelected(recentActivity.value)
  },
)
</script>

<template>
  <section>
    <div v-if="dashboard !== null" class="head">
      <div>
        <div class="eyebrow">{{ dashboard.section }} / CONTROL</div>
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

      <div class="layout overview-grid">
        <section class="card launchpad">
          <h3>快速入口</h3>
          <div class="quick-grid">
            <RouterLink v-for="item in quickRoutes" :key="item.label" :to="item.route" class="quick-link">
              <span>{{ item.label }}</span>
              <span class="tag" :class="item.tone">{{ item.label === '研究工作台' ? '核心' : '入口' }}</span>
            </RouterLink>
          </div>
          <div class="note" style="margin-top: 16px;">
            這裡保留最常用的工作流跳轉，避免在總覽頁只看到統計數字卻還要再繞一層找入口。
          </div>
        </section>

        <section v-for="list in dashboard.lists" :key="list.title" class="card">
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

        <section class="card activity-card">
          <h3>活動詳情</h3>
          <p v-if="selected === null" class="muted">目前沒有可查看的活動項目。</p>
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
              <RouterLink :to="selected.item.to ?? { name: 'overview' }">
                <button type="button" class="primary">打開詳情</button>
              </RouterLink>
            </div>
          </template>
          <div v-if="recentActivity.length !== 0" class="activity-feed">
            <div v-for="entry in recentActivity.slice(0, 8)" :key="`${entry.listTitle}:${entry.item.title}:${entry.item.subtitle}`" class="feed-row">
              <span class="tag">{{ entry.listTitle }}</span>
              <span>{{ entry.item.title }}</span>
            </div>
          </div>
        </section>
      </div>

      <section class="card note-card">
        <h3>控制台邊界</h3>
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

.overview-grid {
  grid-template-columns: repeat(3, minmax(0, 1fr));
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

.quick-grid,
.activity-feed {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.quick-link,
.feed-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  border: 1px solid #27405d;
  border-radius: 10px;
  padding: 12px;
  background: #0e1e31;
}

.activity-card {
  grid-column: span 3;
}

.compact {
  padding: 10px 0;
}

.note-card {
  margin-top: 16px;
}

@media (max-width: 1200px) {
  .metric-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .overview-grid {
    grid-template-columns: 1fr 1fr;
  }

  .activity-card {
    grid-column: span 2;
  }
}

@media (max-width: 900px) {
  .metric-grid {
    grid-template-columns: 1fr;
  }

  .overview-grid {
    grid-template-columns: 1fr;
  }

  .activity-card {
    grid-column: span 1;
  }
}
</style>
