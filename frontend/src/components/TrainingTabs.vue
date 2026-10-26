<script setup lang="ts">
/**
 * 訓練模組頁籤（SSOT 36–38）：三個頁面共用同一條導覽，避免各自重繪入口。
 * 頁籤只做導覽，不帶任何研究狀態；深連結與返回由各頁自行處理。
 */
import { RouterLink } from 'vue-router'

interface TrainingTab {
  name: 'training' | 'training-finetune' | 'training-release'
  screen: string
  label: string
  task: string
}

const TRAINING_TABS: TrainingTab[] = [
  { name: 'training', screen: 'SCREEN 36', label: '訓練資料集', task: '已驗證經驗樣本、標籤與品質門檻' },
  { name: 'training-finetune', screen: 'SCREEN 37', label: '微調任務', task: 'LoRA 任務、資源配額及訓練監控' },
  { name: 'training-release', screen: 'SCREEN 38', label: '模型版本發布', task: '版本、發布渠道與回滾' },
]
</script>

<template>
  <nav class="training-tabs" aria-label="訓練模組頁面">
    <RouterLink v-for="tab in TRAINING_TABS" :key="tab.name" :to="{ name: tab.name }" class="training-tab">
      <span class="screen mono">{{ tab.screen }}</span>
      <span class="label">{{ tab.label }}</span>
      <span class="muted">{{ tab.task }}</span>
    </RouterLink>
  </nav>
</template>

<style scoped>
.training-tabs {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  margin-bottom: 18px;
}

.training-tab {
  display: flex;
  flex-direction: column;
  gap: 4px;
  border: 1px solid var(--border);
  border-radius: 11px;
  padding: 12px 14px;
  background: var(--surface-2);
  min-width: 0;
}

.training-tab .screen {
  font-size: 11px;
  color: #54aaff;
}

.training-tab .label {
  font-weight: 650;
}

.training-tab.router-link-active {
  border-color: #3673c7;
  background: #132842;
}

.training-tab.router-link-active .label {
  color: #6fb5ff;
}

@media (max-width: 1200px) {
  .training-tabs {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 720px) {
  .training-tabs {
    grid-template-columns: 1fr;
  }
}
</style>
