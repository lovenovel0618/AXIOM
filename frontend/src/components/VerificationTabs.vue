<script setup lang="ts">
/**
 * 驗證模組頁籤（SSOT 22–26）：五個頁面共用同一條導覽，避免各自重繪入口。
 * 頁籤只做導覽，不帶任何研究狀態；深連結與返回由各頁自行處理。
 */
import { RouterLink } from 'vue-router'

interface VerificationTab {
  name: 'verification' | 'verification-falsify' | 'verification-inverse' | 'verification-proof' | 'verification-graph'
  screen: string
  label: string
  task: string
}

const VERIFICATION_TABS: VerificationTab[] = [
  { name: 'verification', screen: '第 22 頁', label: '驗證中心', task: '多面向證據矩陣與驗證任務' },
  { name: 'verification-falsify', screen: '第 23 頁', label: '反例搜尋', task: '反例空間、邊界條件與失效案例' },
  { name: 'verification-inverse', screen: '第 24 頁', label: '逆向推導', task: '參數恢復、逆問題及多解集合' },
  { name: 'verification-proof', screen: '第 25 頁', label: '形式化證明', task: '命題、前提、證明目標及證明狀態' },
  { name: 'verification-graph', screen: '第 26 頁', label: '證據關聯圖', task: '證據共享依賴與獨立性評估' },
]
</script>

<template>
  <nav class="verification-tabs" aria-label="驗證模組頁面">
    <RouterLink v-for="tab in VERIFICATION_TABS" :key="tab.name" :to="{ name: tab.name }" class="verification-tab">
      <span class="screen mono">{{ tab.screen }}</span>
      <span class="label">{{ tab.label }}</span>
      <span class="muted">{{ tab.task }}</span>
    </RouterLink>
  </nav>
</template>

<style scoped>
.verification-tabs {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 10px;
  margin-bottom: 18px;
}

.verification-tab {
  display: flex;
  flex-direction: column;
  gap: 4px;
  border: 1px solid var(--border);
  border-radius: 11px;
  padding: 12px 14px;
  background: var(--surface-2);
  min-width: 0;
}

.verification-tab .screen {
  font-size: 11px;
  color: #54aaff;
}

.verification-tab .label {
  font-weight: 650;
}

.verification-tab.router-link-active {
  border-color: #3673c7;
  background: #132842;
}

.verification-tab.router-link-active .label {
  color: #6fb5ff;
}

@media (max-width: 1200px) {
  .verification-tabs {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

@media (max-width: 720px) {
  .verification-tabs {
    grid-template-columns: 1fr;
  }
}
</style>
