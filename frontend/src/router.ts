/** 路由驅動導覽：未登入一律導向登入頁，沿用 AX-23 的資訊架構順序。 */
import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { sessionStatus } from './lib/session'
import ArtifactView from './views/ArtifactView.vue'
import LoginView from './views/LoginView.vue'
import ModuleView from './views/ModuleView.vue'
import RunView from './views/RunView.vue'
import DatasetsView from './views/DatasetsView.vue'
import ResearchView from './views/ResearchView.vue'

const routes: RouteRecordRaw[] = [
  { path: '/', redirect: { name: 'overview' } },
  { path: '/login', name: 'login', component: LoginView },
  { path: '/overview', name: 'overview', component: ModuleView },
  { path: '/datasets', name: 'datasets', component: DatasetsView },
  { path: '/researches/:id?', name: 'researches', component: ResearchView },
  { path: '/discoveries', name: 'discoveries', component: ModuleView },
  { path: '/verification', name: 'verification', component: ModuleView },
  { path: '/memory', name: 'memory', component: ModuleView },
  { path: '/models', name: 'model', component: ModuleView },
  { path: '/training', name: 'training', component: ModuleView },
  { path: '/settings', name: 'settings', component: ModuleView },
  { path: '/runs/:id', name: 'run', component: RunView },
  { path: '/artifacts/:id', name: 'artifact', component: ArtifactView },
]

export const router = createRouter({ history: createWebHistory(), routes })

router.beforeEach((to) => {
  if (to.name !== 'login' && sessionStatus.value === 'signed-out') return { name: 'login' }
  if (to.name === 'login' && sessionStatus.value === 'signed-in') return { name: 'datasets' }
  return true
})
