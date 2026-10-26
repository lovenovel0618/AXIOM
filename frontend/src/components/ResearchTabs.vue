<script setup lang="ts">
/**
 * 研究模組頁籤（SSOT 08–10）：研究詳情、研究分支圖與研究任務紀錄共用同一條導覽。
 * 三頁都以研究識別碼為必要路徑參數；未帶識別碼時頁籤只顯示說明而不可點。
 */
import { computed } from 'vue'
import { RouterLink } from 'vue-router'

type ResearchRouteName = 'research-detail' | 'research-graph' | 'research-timeline'

interface ResearchTab {
  name: ResearchRouteName
  screen: string
  label: string
  task: string
}

const props = defineProps<{ researchId?: string }>()

const RESEARCH_TABS: ResearchTab[] = [
  { name: 'research-detail', screen: '第 8 頁', label: '研究詳情', task: '目標、執行快照、成果與版本' },
  { name: 'research-graph', screen: '第 9 頁', label: '研究分支圖', task: '研究依賴圖、分支與重試標記' },
  { name: 'research-timeline', screen: '第 10 頁', label: '研究任務紀錄', task: '執行排程、重試、失敗與事件重播' },
]

interface LinkedTab {
  tab: ResearchTab
  to: { name: ResearchRouteName; params: Record<string, string> } | null
}

const links = computed<LinkedTab[]>(() =>
  RESEARCH_TABS.map((tab): LinkedTab =>
    props.researchId === undefined || props.researchId === ''
      ? { tab, to: null }
      : { tab, to: { name: tab.name, params: { id: props.researchId } } },
  ),
)
</script>

<template>
  <nav class="research-tabs" aria-label="研究模組頁面">
    <template v-for="item in links" :key="item.tab.name">
      <RouterLink v-if="item.to !== null" :to="item.to" class="research-tab">
        <span class="screen mono">{{ item.tab.screen }}</span>
        <span class="label">{{ item.tab.label }}</span>
        <span class="muted">{{ item.tab.task }}</span>
      </RouterLink>
      <span v-else class="research-tab disabled" :title="`請先從研究清單選擇研究，才能開啟「${item.tab.label}」`">
        <span class="screen mono">{{ item.tab.screen }}</span>
        <span class="label">{{ item.tab.label }}</span>
        <span class="muted">需先選定研究</span>
      </span>
    </template>
  </nav>
</template>

<style scoped>
.research-tabs {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  margin-bottom: 18px;
}

.research-tab {
  display: flex;
  flex-direction: column;
  gap: 4px;
  border: 1px solid var(--border);
  border-radius: 11px;
  padding: 12px 14px;
  background: var(--surface-2);
  min-width: 0;
}

.research-tab .screen {
  font-size: 11px;
  color: #54aaff;
}

.research-tab .label {
  font-weight: 650;
}

.research-tab.router-link-active {
  border-color: #3673c7;
  background: #132842;
}

.research-tab.router-link-active .label {
  color: #6fb5ff;
}

.research-tab.disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

@media (max-width: 900px) {
  .research-tabs {
    grid-template-columns: 1fr;
  }
}
</style>
