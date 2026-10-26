<script setup lang="ts">
/**
 * 模型模組頁籤（SSOT 32–35）：四個頁面共用同一條導覽，避免各自重繪入口。
 * 頁籤只做導覽，不帶任何研究狀態；深連結與返回由各頁自行處理。
 */
import { RouterLink } from 'vue-router'

interface ModelTab {
  name: 'model' | 'model-routing' | 'model-evaluation' | 'model-storage'
  screen: string
  label: string
  task: string
}

const MODEL_TABS: ModelTab[] = [
  { name: 'model', screen: 'SCREEN 32', label: 'Ollama 模型管理', task: '模型載入、上下文、版本與資源' },
  { name: 'model-routing', screen: 'SCREEN 33', label: '模型路由', task: '任務分類、候選模型與路由策略' },
  { name: 'model-evaluation', screen: 'SCREEN 34', label: '模型能力評估', task: '數學任務基準、延遲與成本' },
  { name: 'model-storage', screen: 'SCREEN 35', label: 'Token 與儲存', task: '事件保存、壓縮、留存及成本' },
]
</script>

<template>
  <nav class="model-tabs" aria-label="模型模組頁面">
    <RouterLink v-for="tab in MODEL_TABS" :key="tab.name" :to="{ name: tab.name }" class="model-tab">
      <span class="screen mono">{{ tab.screen }}</span>
      <span class="label">{{ tab.label }}</span>
      <span class="muted">{{ tab.task }}</span>
    </RouterLink>
  </nav>
</template>

<style scoped>
.model-tabs {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  margin-bottom: 18px;
}

.model-tab {
  display: flex;
  flex-direction: column;
  gap: 4px;
  border: 1px solid var(--border);
  border-radius: 11px;
  padding: 12px 14px;
  background: var(--surface-2);
  min-width: 0;
}

.model-tab .screen {
  font-size: 11px;
  color: #54aaff;
}

.model-tab .label {
  font-weight: 650;
}

.model-tab.router-link-active {
  border-color: #3673c7;
  background: #132842;
}

.model-tab.router-link-active .label {
  color: #6fb5ff;
}

@media (max-width: 1200px) {
  .model-tabs {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 720px) {
  .model-tabs {
    grid-template-columns: 1fr;
  }
}
</style>
