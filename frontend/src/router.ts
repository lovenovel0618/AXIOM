/** 路由驅動導覽：未登入一律導向登入頁，沿用 AX-23 的資訊架構順序。 */
import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { sessionStatus } from './lib/session'
import DatasetsView from './views/DatasetsView.vue'
import LoginView from './views/LoginView.vue'

const routes: RouteRecordRaw[] = [
  { path: '/', redirect: { name: 'datasets' } },
  { path: '/login', name: 'login', component: LoginView },
  { path: '/datasets', name: 'datasets', component: DatasetsView },
]

export const router = createRouter({ history: createWebHistory(), routes })

router.beforeEach((to) => {
  if (to.name !== 'login' && sessionStatus.value === 'signed-out') return { name: 'login' }
  if (to.name === 'login' && sessionStatus.value === 'signed-in') return { name: 'datasets' }
  return true
})
