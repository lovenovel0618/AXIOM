<script setup lang="ts">
/**
 * 發現模組頁籤（SSOT 18–21）：四個頁面共用同一條導覽，避免各自重繪入口。
 * 頁籤只做導覽，不帶任何研究狀態；深連結與返回由各頁自行處理。
 */
import { RouterLink } from 'vue-router'

interface DiscoveryTab {
  name: 'discoveries' | 'discovery-compare' | 'discovery-latent' | 'discovery-derivation'
  screen: string
  label: string
  task: string
}

const DISCOVERY_TABS: DiscoveryTab[] = [
  { name: 'discoveries', screen: 'SCREEN 18', label: '候選公式庫', task: '候選公式排序、適用條件及證據' },
  { name: 'discovery-compare', screen: 'SCREEN 19', label: '公式比較', task: '模型誤差、複雜度與泛化比較' },
  { name: 'discovery-latent', screen: 'SCREEN 20', label: '隱藏變數探索', task: '潛在狀態、內在維度及可識別性' },
  { name: 'discovery-derivation', screen: 'SCREEN 21', label: '研究推演', task: '假設推導、依賴前提及回溯' },
]
</script>

<template>
  <nav class="discovery-tabs" aria-label="發現模組頁面">
    <RouterLink v-for="tab in DISCOVERY_TABS" :key="tab.name" :to="{ name: tab.name }" class="discovery-tab">
      <span class="screen mono">{{ tab.screen }}</span>
      <span class="label">{{ tab.label }}</span>
      <span class="muted">{{ tab.task }}</span>
    </RouterLink>
  </nav>
</template>

<style scoped>
.discovery-tabs {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  margin-bottom: 18px;
}

.discovery-tab {
  display: flex;
  flex-direction: column;
  gap: 4px;
  border: 1px solid var(--border);
  border-radius: 11px;
  padding: 12px 14px;
  background: var(--surface-2);
  min-width: 0;
}

.discovery-tab .screen {
  font-size: 11px;
  color: #54aaff;
}

.discovery-tab .label {
  font-weight: 650;
}

.discovery-tab.router-link-active {
  border-color: #3673c7;
  background: #132842;
}

.discovery-tab.router-link-active .label {
  color: #6fb5ff;
}

@media (max-width: 1100px) {
  .discovery-tabs {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 640px) {
  .discovery-tabs {
    grid-template-columns: 1fr;
  }
}
</style>
