/** 路由驅動導覽：未登入一律導向登入頁，沿用 AX-23 的資訊架構順序。 */
import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { sessionStatus } from './lib/session'
import ArtifactView from './views/ArtifactView.vue'
import DiscoveriesView from './views/DiscoveriesView.vue'
import LoginView from './views/LoginView.vue'
import MemoryView from './views/MemoryView.vue'
import ModelView from './views/ModelView.vue'
import OverviewView from './views/OverviewView.vue'
import RunView from './views/RunView.vue'
import DatasetsView from './views/DatasetsView.vue'
import ResearchView from './views/ResearchView.vue'
import SettingsView from './views/SettingsView.vue'
import TrainingView from './views/TrainingView.vue'
import VerificationView from './views/VerificationView.vue'

const routes: RouteRecordRaw[] = [
  { path: '/', redirect: { name: 'overview' } },
  { path: '/login', name: 'login', component: LoginView },
  { path: '/overview', name: 'overview', component: OverviewView },
  { path: '/datasets', name: 'datasets', component: DatasetsView },
  { path: '/researches/:id?', name: 'researches', component: ResearchView },
  { path: '/discoveries', name: 'discoveries', component: DiscoveriesView },
  { path: '/verification', name: 'verification', component: VerificationView },
  { path: '/memory', name: 'memory', component: MemoryView },
  { path: '/models', name: 'model', component: ModelView },
  { path: '/training', name: 'training', component: TrainingView },
  { path: '/settings', name: 'settings', component: SettingsView },
  { path: '/runs/:id', name: 'run', component: RunView },
  { path: '/artifacts/:id', name: 'artifact', component: ArtifactView },
]

export const router = createRouter({ history: createWebHistory(), routes })

router.beforeEach((to) => {
  if (to.name !== 'login' && sessionStatus.value === 'signed-out') return { name: 'login' }
  if (to.name === 'login' && sessionStatus.value === 'signed-in') return { name: 'datasets' }
  return true
})
