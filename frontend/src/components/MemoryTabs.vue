<script setup lang="ts">
/**
 * 記憶模組頁籤（SSOT 27–31）：五個頁面共用同一條導覽，避免各自重繪入口。
 * 頁籤只做導覽，不帶任何研究狀態；深連結與返回由各頁自行處理。
 */
import { RouterLink } from 'vue-router'

interface MemoryTab {
  name: 'memory' | 'memory-experience' | 'memory-failure' | 'memory-recovery' | 'memory-evolution'
  screen: string
  label: string
  task: string
}

const MEMORY_TABS: MemoryTab[] = [
  { name: 'memory', screen: 'SCREEN 27', label: '知識庫', task: '已驗證結論、來源與檢索' },
  { name: 'memory-experience', screen: 'SCREEN 28', label: '研究經驗', task: '策略成功與失敗經驗及條件' },
  { name: 'memory-failure', screen: 'SCREEN 29', label: '失敗案例', task: '否定證據、數值失敗與修復可能' },
  { name: 'memory-recovery', screen: 'SCREEN 30', label: '假設恢復', task: '恢復條件、重新評估與候選佇列' },
  { name: 'memory-evolution', screen: 'SCREEN 31', label: '知識演化', task: '版本、修正、撤回與證據更新' },
]
</script>

<template>
  <nav class="memory-tabs" aria-label="記憶模組頁面">
    <RouterLink v-for="tab in MEMORY_TABS" :key="tab.name" :to="{ name: tab.name }" class="memory-tab">
      <span class="screen mono">{{ tab.screen }}</span>
      <span class="label">{{ tab.label }}</span>
      <span class="muted">{{ tab.task }}</span>
    </RouterLink>
  </nav>
</template>

<style scoped>
.memory-tabs {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 10px;
  margin-bottom: 18px;
}

.memory-tab {
  display: flex;
  flex-direction: column;
  gap: 4px;
  border: 1px solid var(--border);
  border-radius: 11px;
  padding: 12px 14px;
  background: var(--surface-2);
  min-width: 0;
}

.memory-tab .screen {
  font-size: 11px;
  color: #54aaff;
}

.memory-tab .label {
  font-weight: 650;
}

.memory-tab.router-link-active {
  border-color: #3673c7;
  background: #132842;
}

.memory-tab.router-link-active .label {
  color: #6fb5ff;
}

@media (max-width: 1200px) {
  .memory-tabs {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

@media (max-width: 720px) {
  .memory-tabs {
    grid-template-columns: 1fr;
  }
}
</style>
