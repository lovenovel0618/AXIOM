<script setup lang="ts">
/**
 * 設定模組頁籤（SSOT 39–40）：兩個頁面共用同一條導覽。
 * 頁籤只做導覽，不帶任何研究狀態；深連結與返回由各頁自行處理。
 */
import { RouterLink } from 'vue-router'

interface SettingsTab {
  name: 'settings' | 'settings-research'
  screen: string
  label: string
  task: string
}

const SETTINGS_TABS: SettingsTab[] = [
  { name: 'settings', screen: 'SCREEN 39', label: '系統與安全設定', task: '角色與權限、金鑰與稽核留存' },
  { name: 'settings-research', screen: 'SCREEN 40', label: '研究策略設定', task: '評估政策、切分、預算與研究域' },
]
</script>

<template>
  <nav class="settings-tabs" aria-label="設定模組頁面">
    <RouterLink v-for="tab in SETTINGS_TABS" :key="tab.name" :to="{ name: tab.name }" class="settings-tab">
      <span class="screen mono">{{ tab.screen }}</span>
      <span class="label">{{ tab.label }}</span>
      <span class="muted">{{ tab.task }}</span>
    </RouterLink>
  </nav>
</template>

<style scoped>
.settings-tabs {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  margin-bottom: 18px;
}

.settings-tab {
  display: flex;
  flex-direction: column;
  gap: 4px;
  border: 1px solid var(--border);
  border-radius: 11px;
  padding: 12px 14px;
  background: var(--surface-2);
  min-width: 0;
}

.settings-tab .screen {
  font-size: 11px;
  color: #54aaff;
}

.settings-tab .label {
  font-weight: 650;
}

.settings-tab.router-link-active {
  border-color: #3673c7;
  background: #132842;
}

.settings-tab.router-link-active .label {
  color: #6fb5ff;
}

@media (max-width: 720px) {
  .settings-tabs {
    grid-template-columns: 1fr;
  }
}
</style>
