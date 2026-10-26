<script setup lang="ts">
/**
 * 數據模組頁籤（SSOT 11–17）：七個頁面共用同一條導覽，避免各自重繪入口。
 * 資料集範圍的頁面需要資料集識別碼；清單頁沒有選定資料集時，這些頁籤只做說明不可點。
 */
import { computed } from 'vue'
import { RouterLink } from 'vue-router'

type DataRouteName =
  | 'datasets'
  | 'data-upload'
  | 'data-preview'
  | 'data-quality'
  | 'data-pipeline'
  | 'data-explore'
  | 'data-diff'

interface DataTab {
  name: DataRouteName
  screen: string
  label: string
  task: string
  scoped: boolean
}

const props = defineProps<{ datasetId?: string }>()

const DATA_TABS: DataTab[] = [
  { name: 'datasets', screen: '第 11 頁', label: '資料集清單', task: '資料來源、版本、權限與品質', scoped: false },
  { name: 'data-upload', screen: '第 12 頁', label: '資料上傳精靈', task: '匯入、映射、檢核與不可變快照', scoped: true },
  { name: 'data-preview', screen: '第 13 頁', label: '資料預覽', task: '欄位、取樣與資料字典', scoped: true },
  { name: 'data-quality', screen: '第 14 頁', label: '資料品質', task: '缺失、異常、偏移與洩漏風險', scoped: true },
  { name: 'data-pipeline', screen: '第 15 頁', label: '前處理管線', task: '轉換流程、參數與前後差異', scoped: true },
  { name: 'data-explore', screen: '第 16 頁', label: '多維探索', task: '時間、相空間、頻域與高維投影', scoped: true },
  { name: 'data-diff', screen: '第 17 頁', label: '資料版本比較', task: '版本差異、血緣與影響', scoped: true },
]

interface LinkedTab {
  tab: DataTab
  to: { name: DataRouteName; params: Record<string, string> } | null
}

const links = computed<LinkedTab[]>(() =>
  DATA_TABS.map((tab): LinkedTab => {
    if (!tab.scoped) return { tab, to: { name: tab.name, params: {} } }
    if (props.datasetId === undefined || props.datasetId === '') return { tab, to: null }
    return { tab, to: { name: tab.name, params: { id: props.datasetId } } }
  }),
)
</script>

<template>
  <nav class="data-tabs" aria-label="數據模組頁面">
    <template v-for="item in links" :key="item.tab.name">
      <RouterLink v-if="item.to !== null" :to="item.to" class="data-tab">
        <span class="screen mono">{{ item.tab.screen }}</span>
        <span class="label">{{ item.tab.label }}</span>
        <span class="muted">{{ item.tab.task }}</span>
      </RouterLink>
      <span v-else class="data-tab disabled" :title="`請先從資料集清單選擇資料集，才能開啟「${item.tab.label}」`">
        <span class="screen mono">{{ item.tab.screen }}</span>
        <span class="label">{{ item.tab.label }}</span>
        <span class="muted">需先選定資料集</span>
      </span>
    </template>
  </nav>
</template>

<style scoped>
.data-tabs {
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  gap: 10px;
  margin-bottom: 18px;
}

.data-tab {
  display: flex;
  flex-direction: column;
  gap: 4px;
  border: 1px solid var(--border);
  border-radius: 11px;
  padding: 12px 14px;
  background: var(--surface-2);
  min-width: 0;
}

.data-tab .screen {
  font-size: 11px;
  color: #54aaff;
}

.data-tab .label {
  font-weight: 650;
}

.data-tab.router-link-active {
  border-color: #3673c7;
  background: #132842;
}

.data-tab.router-link-active .label {
  color: #6fb5ff;
}

.data-tab.disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

@media (max-width: 1400px) {
  .data-tabs {
    grid-template-columns: repeat(4, minmax(0, 1fr));
  }
}

@media (max-width: 900px) {
  .data-tabs {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 640px) {
  .data-tabs {
    grid-template-columns: 1fr;
  }
}
</style>
