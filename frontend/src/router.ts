/** 路由驅動導覽：未登入一律導向登入頁，沿用 AX-23 的資訊架構順序。 */
import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { sessionStatus } from './lib/session'
import ActivityCenterView from './views/ActivityCenterView.vue'
import ArtifactView from './views/ArtifactView.vue'
import CandidateDetailView from './views/CandidateDetailView.vue'
import DiscoveryCatalogView from './views/DiscoveryCatalogView.vue'
import DiscoveryCompareView from './views/DiscoveryCompareView.vue'
import DiscoveryDerivationView from './views/DiscoveryDerivationView.vue'
import DiscoveryLatentView from './views/DiscoveryLatentView.vue'
import LoginView from './views/LoginView.vue'
import MemoryView from './views/MemoryView.vue'
import ModelView from './views/ModelView.vue'
import OverviewView from './views/OverviewView.vue'
import PendingEventsView from './views/PendingEventsView.vue'
import ResourceMonitorView from './views/ResourceMonitorView.vue'
import RunView from './views/RunView.vue'
import DatasetDetailView from './views/DatasetDetailView.vue'
import DatasetsView from './views/DatasetsView.vue'
import ResearchCreateView from './views/ResearchCreateView.vue'
import ResearchListView from './views/ResearchListView.vue'
import ResearchView from './views/ResearchView.vue'
import SettingsView from './views/SettingsView.vue'
import TrainingView from './views/TrainingView.vue'
import VerificationFalsifyView from './views/VerificationFalsifyView.vue'
import VerificationGraphView from './views/VerificationGraphView.vue'
import VerificationInverseView from './views/VerificationInverseView.vue'
import VerificationProofView from './views/VerificationProofView.vue'
import VerificationView from './views/VerificationView.vue'

const routes: RouteRecordRaw[] = [
  { path: '/', redirect: { name: 'overview' } },
  { path: '/login', name: 'login', component: LoginView },
  { path: '/overview', name: 'overview', component: OverviewView },
  { path: '/activity', name: 'activity', component: ActivityCenterView },
  { path: '/pending', name: 'pending', component: PendingEventsView },
  { path: '/resources', name: 'resources', component: ResourceMonitorView },
  { path: '/datasets', name: 'datasets', component: DatasetsView },
  { path: '/datasets/:id', name: 'dataset', component: DatasetDetailView },
  { path: '/researches', name: 'research-list', component: ResearchListView },
  { path: '/researches/new', name: 'research-create', component: ResearchCreateView },
  { path: '/researches/:id', name: 'research-workbench', component: ResearchView },
  { path: '/discoveries', name: 'discoveries', component: DiscoveryCatalogView },
  { path: '/discoveries/compare', name: 'discovery-compare', component: DiscoveryCompareView },
  { path: '/discoveries/latent', name: 'discovery-latent', component: DiscoveryLatentView },
  { path: '/discoveries/derivation', name: 'discovery-derivation', component: DiscoveryDerivationView },
  { path: '/candidates/:id', name: 'candidate', component: CandidateDetailView },
  { path: '/verification', name: 'verification', component: VerificationView },
  { path: '/verification/falsify', name: 'verification-falsify', component: VerificationFalsifyView },
  { path: '/verification/inverse', name: 'verification-inverse', component: VerificationInverseView },
  { path: '/verification/proof', name: 'verification-proof', component: VerificationProofView },
  { path: '/verification/graph', name: 'verification-graph', component: VerificationGraphView },
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
