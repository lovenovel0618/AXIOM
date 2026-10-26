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
import MemoryEvolutionView from './views/MemoryEvolutionView.vue'
import MemoryExperienceView from './views/MemoryExperienceView.vue'
import MemoryFailureView from './views/MemoryFailureView.vue'
import MemoryKnowledgeView from './views/MemoryKnowledgeView.vue'
import MemoryRecoveryView from './views/MemoryRecoveryView.vue'
import ModelEvaluationView from './views/ModelEvaluationView.vue'
import ModelRoutingView from './views/ModelRoutingView.vue'
import ModelStorageView from './views/ModelStorageView.vue'
import ModelView from './views/ModelView.vue'
import OverviewView from './views/OverviewView.vue'
import PendingEventsView from './views/PendingEventsView.vue'
import ResourceMonitorView from './views/ResourceMonitorView.vue'
import RunView from './views/RunView.vue'
import DataCatalogView from './views/DataCatalogView.vue'
import DataDiffView from './views/DataDiffView.vue'
import DataExploreView from './views/DataExploreView.vue'
import DataPipelineView from './views/DataPipelineView.vue'
import DataPreviewView from './views/DataPreviewView.vue'
import DataQualityView from './views/DataQualityView.vue'
import DataUploadView from './views/DataUploadView.vue'
import ResearchCreateView from './views/ResearchCreateView.vue'
import ResearchGraphView from './views/ResearchGraphView.vue'
import ResearchListView from './views/ResearchListView.vue'
import ResearchProfileView from './views/ResearchProfileView.vue'
import ResearchTimelineView from './views/ResearchTimelineView.vue'
import ResearchView from './views/ResearchView.vue'
import SettingsResearchView from './views/SettingsResearchView.vue'
import SettingsSecurityView from './views/SettingsSecurityView.vue'
import TrainingDatasetView from './views/TrainingDatasetView.vue'
import TrainingFinetuneView from './views/TrainingFinetuneView.vue'
import TrainingReleaseView from './views/TrainingReleaseView.vue'
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
  { path: '/datasets', name: 'datasets', component: DataCatalogView },
  { path: '/datasets/:id/upload', name: 'data-upload', component: DataUploadView },
  { path: '/datasets/:id/preview', name: 'data-preview', component: DataPreviewView },
  { path: '/datasets/:id/quality', name: 'data-quality', component: DataQualityView },
  { path: '/datasets/:id/pipeline', name: 'data-pipeline', component: DataPipelineView },
  { path: '/datasets/:id/explore', name: 'data-explore', component: DataExploreView },
  { path: '/datasets/:id/diff', name: 'data-diff', component: DataDiffView },
  { path: '/researches', name: 'research-list', component: ResearchListView },
  { path: '/researches/new', name: 'research-create', component: ResearchCreateView },
  { path: '/researches/:id', name: 'research-workbench', component: ResearchView },
  { path: '/researches/:id/detail', name: 'research-detail', component: ResearchProfileView },
  { path: '/researches/:id/graph', name: 'research-graph', component: ResearchGraphView },
  { path: '/researches/:id/timeline', name: 'research-timeline', component: ResearchTimelineView },
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
  { path: '/memory', name: 'memory', component: MemoryKnowledgeView },
  { path: '/memory/experience', name: 'memory-experience', component: MemoryExperienceView },
  { path: '/memory/failure', name: 'memory-failure', component: MemoryFailureView },
  { path: '/memory/recovery', name: 'memory-recovery', component: MemoryRecoveryView },
  { path: '/memory/evolution', name: 'memory-evolution', component: MemoryEvolutionView },
  { path: '/models', name: 'model', component: ModelView },
  { path: '/models/routing', name: 'model-routing', component: ModelRoutingView },
  { path: '/models/evaluation', name: 'model-evaluation', component: ModelEvaluationView },
  { path: '/models/storage', name: 'model-storage', component: ModelStorageView },
  { path: '/training', name: 'training', component: TrainingDatasetView },
  { path: '/training/finetune', name: 'training-finetune', component: TrainingFinetuneView },
  { path: '/training/release', name: 'training-release', component: TrainingReleaseView },
  { path: '/settings', name: 'settings', component: SettingsSecurityView },
  { path: '/settings/research', name: 'settings-research', component: SettingsResearchView },
  { path: '/runs/:id', name: 'run', component: RunView },
  { path: '/artifacts/:id', name: 'artifact', component: ArtifactView },
]

export const router = createRouter({ history: createWebHistory(), routes })

router.beforeEach((to) => {
  if (to.name !== 'login' && sessionStatus.value === 'signed-out') return { name: 'login' }
  if (to.name === 'login' && sessionStatus.value === 'signed-in') return { name: 'datasets' }
  return true
})
