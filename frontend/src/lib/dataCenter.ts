/**
 * 數據模組（SSOT SCREEN 11–17）的純推導邏輯：只依後端已揭露的資料集、資料集版本欄位與結構預覽產物計算。
 *
 * 後端沒有品質統計、前處理管線、投影座標與版本血緣端點；這些欄位一律回報「未取得」，
 * 不以推測補值，符合 Fail-Closed 原則。
 */
import type { Dataset, DatasetVersion, DatasetVersionStatus, RunRecord, UploadFormat } from '../api/datasets'
import {
  buildDatasetDigest,
  buildQualityChecks,
  compareVersions,
  summarizeStructure,
  type DatasetDigest,
  type QualityCheck,
  type QualityStatus,
  type StructureSummary,
  type VersionDiff,
} from './datasetWorkbench'
import type { SourceMetadata } from './semantics'

export const DATA_UNKNOWN = '未取得'
export const DATASETS_READ = 12
export const VERSIONS_PER_DATASET = 8

export const FORMAT_LABELS: Record<UploadFormat, string> = {
  CSV: 'CSV',
  JSON: 'JSON',
  PARQUET: 'Parquet',
}

export const DATASET_VERSION_STATUS_LABELS: Record<DatasetVersionStatus, string> = {
  AVAILABLE: '可用',
  UNAVAILABLE: '不可用',
}

/** 推導層沿用檢核狀態三值：通過／未通過／未取得。 */
export type StepStatus = QualityStatus

export function stepStatusLabel(status: StepStatus): string {
  if (status === 'PASS') return '通過'
  if (status === 'FAIL') return '未通過'
  return DATA_UNKNOWN
}

export interface DatasetPageLike {
  items: Dataset[]
  next_cursor: string | null
}

export interface VersionPageLike {
  items: DatasetVersion[]
  next_cursor: string | null
}

export interface DataCenter {
  datasets: Dataset[]
  versionsByDataset: Record<string, DatasetVersion[]>
  datasetTruncated: boolean
  versionTruncated: string[]
  scope: { datasetsRead: number; versionsRead: number }
}

export interface DataDeps {
  listDatasets(limit: number): Promise<DatasetPageLike>
  listVersions(datasetId: string, limit: number): Promise<VersionPageLike>
}

/** 只讀取頁面實際需要的資料集與版本；後端仍有下一頁時以旗標標示，不假稱全量。 */
export async function loadDataCenter(deps: DataDeps): Promise<DataCenter> {
  const page = await deps.listDatasets(DATASETS_READ)
  const datasets = page.items.slice(0, DATASETS_READ)
  const datasetTruncated = page.next_cursor !== null || page.items.length > DATASETS_READ
  const versionsByDataset: Record<string, DatasetVersion[]> = {}
  const versionTruncated: string[] = []
  let versionsRead = 0

  for (const dataset of datasets) {
    let versions: DatasetVersion[] = []
    try {
      const versionPage = await deps.listVersions(dataset.id, VERSIONS_PER_DATASET + 1)
      if (versionPage.next_cursor !== null || versionPage.items.length > VERSIONS_PER_DATASET) {
        versionTruncated.push(dataset.id)
      }
      versions = versionPage.items.slice(0, VERSIONS_PER_DATASET)
    } catch {
      versions = []
    }
    versionsByDataset[dataset.id] = versions
    versionsRead += versions.length
  }

  return {
    datasets,
    versionsByDataset,
    datasetTruncated,
    versionTruncated,
    scope: { datasetsRead: datasets.length, versionsRead },
  }
}

/** 最新一個可用且具結構預覽的版本；沒有就不回傳，讓呼叫端顯示禁用原因。 */
export function latestAnalyzableVersion(versions: DatasetVersion[]): DatasetVersion | null {
  return (
    [...versions]
      .sort((left, right) => (left.created_at < right.created_at ? 1 : -1))
      .find((row) => row.status === 'AVAILABLE' && row.structure_preview_artifact_id !== null) ?? null
  )
}

/** 由 URL 承接的版本識別碼只在確實存在於已讀取版本時才採用，否則退回第一筆。 */
export function resolveVersionId(versions: DatasetVersion[], requested: string): string {
  if (requested !== '' && versions.some((row) => row.id === requested)) return requested
  return versions[0]?.id ?? ''
}

export function metadataForVersion(
  metadataByArtifact: Record<string, SourceMetadata | null>,
  version: DatasetVersion | null,
): SourceMetadata | null {
  if (version === null || version.structure_preview_artifact_id === null) return null
  return metadataByArtifact[version.structure_preview_artifact_id] ?? null
}

/** SCREEN 11：資料集清單一列的摘要。 */
export interface CatalogRow {
  dataset: Dataset
  digest: DatasetDigest
  analyzeVersionId: string | null
  versionTruncated: boolean
}

export function buildCatalogRows(center: DataCenter): CatalogRow[] {
  return center.datasets.map((dataset) => {
    const versions = center.versionsByDataset[dataset.id] ?? []
    return {
      dataset,
      digest: buildDatasetDigest(versions),
      analyzeVersionId: latestAnalyzableVersion(versions)?.id ?? null,
      versionTruncated: center.versionTruncated.includes(dataset.id),
    }
  })
}

export interface CatalogSummary {
  datasets: number
  versions: number
  rows: number
  unavailable: number
  analyzable: number
}

export function summarizeCatalog(rows: CatalogRow[]): CatalogSummary {
  return {
    datasets: rows.length,
    versions: rows.reduce((sum, row) => sum + row.digest.versionCount, 0),
    rows: rows.reduce((sum, row) => sum + row.digest.totalRows, 0),
    unavailable: rows.reduce((sum, row) => sum + row.digest.unavailableCount, 0),
    analyzable: rows.filter((row) => row.analyzeVersionId !== null).length,
  }
}

export function filterCatalogRows(rows: CatalogRow[], keyword: string): CatalogRow[] {
  const needle = keyword.trim().toLowerCase()
  if (needle === '') return rows
  return rows.filter(
    (row) => row.dataset.name.toLowerCase().includes(needle) || row.dataset.id.toLowerCase().includes(needle),
  )
}

/** SCREEN 12：資料上傳精靈的四道程序，逐項依後端已揭露狀態判定。 */
export type WizardStepKey = 'INGEST' | 'MAPPING' | 'CHECK' | 'SNAPSHOT'

export interface WizardStep {
  key: WizardStepKey
  label: string
  status: StepStatus
  detail: string
}

function ingestStep(version: DatasetVersion | null, runs: RunRecord[]): WizardStep {
  if (version !== null) {
    return {
      key: 'INGEST',
      label: '匯入與不可變登記',
      status: 'PASS',
      detail: `後端已建立版本 ${version.id}（${FORMAT_LABELS[version.format]}）。`,
    }
  }
  const latest = runs.find((run) => run.type === 'INGEST') ?? null
  if (latest === null) {
    return { key: 'INGEST', label: '匯入與不可變登記', status: 'UNKNOWN', detail: '尚未取得匯入任務或版本。' }
  }
  return {
    key: 'INGEST',
    label: '匯入與不可變登記',
    status: 'FAIL',
    detail: `最新匯入任務 ${latest.id} 狀態為 ${latest.status}，尚未產生版本。`,
  }
}

function mappingStep(version: DatasetVersion | null, metadata: SourceMetadata | null): WizardStep {
  const structure = summarizeStructure(metadata)
  if (version === null || structure === null) {
    return {
      key: 'MAPPING',
      label: '欄位映射',
      status: 'UNKNOWN',
      detail: '未取得可解析的結構預覽，無法判定欄位映射；語意對應仍待人工確認。',
    }
  }
  if (structure.columns.length === 0) {
    return { key: 'MAPPING', label: '欄位映射', status: 'FAIL', detail: '結構預覽未揭露任何欄位。' }
  }
  const names = structure.columns.map((column) => column.name).slice(0, 6)
  return {
    key: 'MAPPING',
    label: '欄位映射',
    status: structure.duplicateNames.length === 0 ? 'PASS' : 'FAIL',
    detail:
      structure.duplicateNames.length === 0
        ? `後端揭露 ${structure.columns.length} 個欄位：${names.join('、')}${structure.columns.length > names.length ? '…' : ''}；語意角色仍需人工確認。`
        : `欄位名稱重複：${structure.duplicateNames.join('、')}`,
  }
}

function checkStep(version: DatasetVersion | null, metadata: SourceMetadata | null): WizardStep {
  if (version === null) {
    return { key: 'CHECK', label: '完整性檢核', status: 'UNKNOWN', detail: '尚未選定版本，無法檢核。' }
  }
  const checks = buildQualityChecks(version, metadata)
  const failed = checks.filter((check) => check.status === 'FAIL')
  const unknown = checks.filter((check) => check.status === 'UNKNOWN')
  if (failed.length > 0) {
    return {
      key: 'CHECK',
      label: '完整性檢核',
      status: 'FAIL',
      detail: `未通過項目：${failed.map((check) => check.label).join('、')}`,
    }
  }
  if (unknown.length > 0) {
    return {
      key: 'CHECK',
      label: '完整性檢核',
      status: 'UNKNOWN',
      detail: `可判定項目皆通過，仍有 ${unknown.length} 項因未取得結構預覽而無法判定。`,
    }
  }
  return { key: 'CHECK', label: '完整性檢核', status: 'PASS', detail: '既有可判定檢核全數通過。' }
}

function snapshotStep(version: DatasetVersion | null): WizardStep {
  if (version === null) {
    return { key: 'SNAPSHOT', label: '不可變快照', status: 'UNKNOWN', detail: '尚未取得版本，無法判定快照。' }
  }
  if (version.status !== 'AVAILABLE') {
    return {
      key: 'SNAPSHOT',
      label: '不可變快照',
      status: 'FAIL',
      detail: `後端回報版本狀態 ${DATASET_VERSION_STATUS_LABELS[version.status]}。`,
    }
  }
  return {
    key: 'SNAPSHOT',
    label: '不可變快照',
    status: 'PASS',
    detail: `版本 ${version.id} 指紋 ${version.sha256.slice(0, 12)}…，產物 ${version.artifact_id}。`,
  }
}

export function buildUploadSteps(
  version: DatasetVersion | null,
  metadata: SourceMetadata | null,
  runs: RunRecord[],
): WizardStep[] {
  return [ingestStep(version, runs), mappingStep(version, metadata), checkStep(version, metadata), snapshotStep(version)]
}

/** SCREEN 13：資料預覽的欄位與資料字典；取樣列後端未揭露，一律回報未取得。 */
export interface PreviewField {
  name: string
  physicalType: string
  duplicate: boolean
  missingType: boolean
}

export interface PreviewTable {
  versionId: string
  declaredRowCount: number
  previewRowCount: number | null
  fields: PreviewField[]
  sampleRows: null
  dictionaryEntryCount: number
}

export function buildPreviewTable(version: DatasetVersion, metadata: SourceMetadata | null): PreviewTable {
  const structure: StructureSummary | null = summarizeStructure(metadata)
  const fields: PreviewField[] =
    structure === null
      ? []
      : structure.columns.map((column) => ({
          name: column.name,
          physicalType: column.physical_type,
          duplicate: structure.duplicateNames.includes(column.name),
          missingType: structure.missingTypeNames.includes(column.name),
        }))
  return {
    versionId: version.id,
    declaredRowCount: version.row_count,
    previewRowCount: structure === null ? null : structure.rowCount,
    fields,
    sampleRows: null,
    dictionaryEntryCount: fields.length,
  }
}

export function filterPreviewFields(fields: PreviewField[], keyword: string): PreviewField[] {
  const needle = keyword.trim().toLowerCase()
  if (needle === '') return fields
  return fields.filter(
    (field) => field.name.toLowerCase().includes(needle) || field.physicalType.toLowerCase().includes(needle),
  )
}

/** SCREEN 14：資料品質四類面向，後端未揭露統計時一律未取得。 */
export type QualityDimensionKey = 'MISSING' | 'OUTLIER' | 'DRIFT' | 'LEAKAGE'

export interface QualityDimension {
  key: QualityDimensionKey
  label: string
  status: StepStatus
  detail: string
}

export const QUALITY_DIMENSION_LABELS: Record<QualityDimensionKey, string> = {
  MISSING: '缺失',
  OUTLIER: '異常值',
  DRIFT: '分布偏移',
  LEAKAGE: '洩漏風險',
}

export function buildQualityDimensions(version: DatasetVersion | null, metadata: SourceMetadata | null): QualityDimension[] {
  const structure = summarizeStructure(metadata)
  const declared = structure === null ? DATA_UNKNOWN : `後端已揭露 ${structure.columns.length} 個欄位`
  return [
    {
      key: 'MISSING',
      label: QUALITY_DIMENSION_LABELS.MISSING,
      status: 'UNKNOWN',
      detail: `後端未揭露缺失值計數（${declared}），不以推測補值。`,
    },
    {
      key: 'OUTLIER',
      label: QUALITY_DIMENSION_LABELS.OUTLIER,
      status: 'UNKNOWN',
      detail: '後端未揭露異常值統計與判定規則，無法定義離群門檻。',
    },
    {
      key: 'DRIFT',
      label: QUALITY_DIMENSION_LABELS.DRIFT,
      status: 'UNKNOWN',
      detail:
        version === null
          ? '尚未選定版本，無法比較分布。'
          : '後端未揭露分布摘要；跨版本偏移需以結構預覽以外的統計產物為準。',
    },
    {
      key: 'LEAKAGE',
      label: QUALITY_DIMENSION_LABELS.LEAKAGE,
      status: 'UNKNOWN',
      detail: '後端未揭露訓練／評估切分與欄位相關性，無法判定洩漏風險。',
    },
  ]
}

export interface QualitySummary {
  pass: number
  fail: number
  unknown: number
}

export function summarizeQuality(checks: QualityCheck[]): QualitySummary {
  return {
    pass: checks.filter((check) => check.status === 'PASS').length,
    fail: checks.filter((check) => check.status === 'FAIL').length,
    unknown: checks.filter((check) => check.status === 'UNKNOWN').length,
  }
}

/** SCREEN 15：前處理管線的節點鏈與程序；後端沒有轉換 DAG 端點，轉換節點一律未取得。 */
export interface PipelineNode {
  kind: 'SNAPSHOT'
  versionId: string
  label: string
  detail: string
  status: StepStatus
}

export function buildPipelineNodes(versions: DatasetVersion[]): PipelineNode[] {
  return [...versions]
    .sort((left, right) => (left.created_at < right.created_at ? -1 : 1))
    .map((version) => ({
      kind: 'SNAPSHOT',
      versionId: version.id,
      label: `${FORMAT_LABELS[version.format]} · ${String(version.row_count)} 列`,
      detail: `${version.created_at}｜指紋 ${version.sha256.slice(0, 12)}…`,
      status: version.status === 'AVAILABLE' ? 'PASS' : 'FAIL',
    }))
}

export interface PipelineStage {
  key: string
  label: string
  status: StepStatus
  detail: string
}

export function buildPipelineStages(
  nodes: PipelineNode[],
  versions: DatasetVersion[],
  metadataByArtifact: Record<string, SourceMetadata | null>,
): PipelineStage[] {
  const latest = nodes.at(-1) ?? null
  const latestVersion = versions.find((row) => row.id === latest?.versionId) ?? null
  const parsedCount = versions.filter((row) => metadataForVersion(metadataByArtifact, row) !== null).length
  const checkStage = checkStep(latestVersion, metadataForVersion(metadataByArtifact, latestVersion))
  return [
    {
      key: 'SELECT',
      label: '選取資料版本',
      status: nodes.length === 0 ? 'UNKNOWN' : 'PASS',
      detail: nodes.length === 0 ? '此資料集尚無版本，請先上傳資料檔。' : `已讀取 ${nodes.length} 個不可變快照。`,
    },
    {
      key: 'DAG',
      label: '轉換節點 DAG',
      status: 'UNKNOWN',
      detail: '後端沒有前處理管線端點，無從取得轉換節點與順序。',
    },
    {
      key: 'PARAM',
      label: '參數與適用欄位',
      status: 'UNKNOWN',
      detail: '後端未揭露轉換參數與適用欄位，無法推導。',
    },
    {
      key: 'PREVIEW',
      label: '前後差異預覽',
      status: versions.length < 2 ? 'UNKNOWN' : parsedCount < 2 ? 'UNKNOWN' : 'PASS',
      detail:
        versions.length < 2
          ? '只有一個版本，無從比較前後差異。'
          : parsedCount < 2
            ? `僅 ${parsedCount} 個版本具可解析結構預覽，欄位層級差異未取得。`
            : '兩版以上結構預覽可解析，可於資料版本比較頁逐欄比較。',
    },
    { key: 'EXEC', label: '執行管線與品質檢查', status: checkStage.status, detail: checkStage.detail },
    {
      key: 'PUBLISH',
      label: '發布新資料版本',
      status: latestVersion === null ? 'UNKNOWN' : latestVersion.status === 'AVAILABLE' ? 'PASS' : 'FAIL',
      detail:
        latestVersion === null
          ? '尚未取得版本。'
          : latestVersion.status === 'AVAILABLE'
            ? `最新版本 ${latestVersion.id} 已可用，可作為研究輸入。`
            : `最新版本 ${latestVersion.id} 狀態為不可用，不得發布。`,
    },
  ]
}

/** SCREEN 16：多維探索的候選座標軸與投影；投影座標後端未揭露。 */
export type AxisKind = 'NUMERIC' | 'TEXT' | 'UNKNOWN'

export interface ExploreAxis {
  name: string
  physicalType: string
  kind: AxisKind
}

export function classifyAxis(physicalType: string): AxisKind {
  const type = physicalType.trim().toUpperCase()
  if (type === '') return 'UNKNOWN'
  if (/INT|DEC|NUMERIC|DOUBLE|REAL|FLOAT/.test(type)) return 'NUMERIC'
  if (/CHAR|TEXT|STRING|BOOL|DATE|TIME|JSON/.test(type)) return 'TEXT'
  return 'UNKNOWN'
}

export function buildExploreAxes(metadata: SourceMetadata | null): ExploreAxis[] {
  if (metadata === null) return []
  return metadata.columns.map((column) => ({
    name: column.name,
    physicalType: column.physical_type,
    kind: classifyAxis(column.physical_type),
  }))
}

export type ProjectionKey = 'TIME' | 'PHASE' | 'FREQUENCY' | 'HIGH_DIM'

export interface ExploreProjection {
  key: ProjectionKey
  label: string
  status: StepStatus
  detail: string
}

export const PROJECTION_LABELS: Record<ProjectionKey, string> = {
  TIME: '時間序列',
  PHASE: '相空間',
  FREQUENCY: '頻域',
  HIGH_DIM: '高維投影',
}

const PROJECTION_REASON: Record<ProjectionKey, string> = {
  TIME: '後端未揭露時間欄位與取樣間隔，無法建立時間軸。',
  PHASE: '後端未揭露狀態變數配對與遲滯參數，無法建立相空間軌跡。',
  FREQUENCY: '後端未揭露頻譜估計與窗函數設定，無法繪製頻域。',
  HIGH_DIM: '後端未揭露降維座標，不以推測補值。',
}

export function buildExploreProjections(axes: ExploreAxis[]): ExploreProjection[] {
  const keys: ProjectionKey[] = ['TIME', 'PHASE', 'FREQUENCY', 'HIGH_DIM']
  return keys.map((key) => ({
    key,
    label: PROJECTION_LABELS[key],
    status: 'UNKNOWN',
    detail:
      key === 'HIGH_DIM' && axes.length > 0
        ? `${PROJECTION_REASON[key]}（已揭露 ${axes.length} 個候選座標軸）`
        : axes.length === 0
          ? '未取得結構預覽，無候選座標軸。'
          : PROJECTION_REASON[key],
  }))
}

/** SCREEN 17：資料版本比較；血緣與回復流程後端未揭露。 */
export interface DiffRow {
  label: string
  base: string
  target: string
  changed: boolean
}

export interface DiffOutcome {
  diff: VersionDiff
  rows: DiffRow[]
  changedCount: number
}

function joined(values: string[] | null, empty: string): string {
  if (values === null) return '未取得（需兩邊皆有結構預覽）'
  return values.length === 0 ? empty : values.join('、')
}

export function buildDiffRows(
  base: DatasetVersion,
  target: DatasetVersion,
  baseMetadata: SourceMetadata | null,
  targetMetadata: SourceMetadata | null,
): DiffOutcome {
  const diff = compareVersions(base, target, baseMetadata, targetMetadata)
  const rows: DiffRow[] = [
    {
      label: '列數',
      base: String(base.row_count),
      target: String(target.row_count),
      changed: diff.rowDelta !== 0,
    },
    { label: '格式', base: FORMAT_LABELS[base.format], target: FORMAT_LABELS[target.format], changed: diff.formatChanged },
    {
      label: '狀態',
      base: DATASET_VERSION_STATUS_LABELS[base.status],
      target: DATASET_VERSION_STATUS_LABELS[target.status],
      changed: diff.statusChanged,
    },
    { label: '檔案指紋', base: `${base.sha256.slice(0, 12)}…`, target: `${target.sha256.slice(0, 12)}…`, changed: !diff.sameFile },
    { label: '新增欄位', base: '—', target: joined(diff.columnsAdded, '無'), changed: (diff.columnsAdded?.length ?? 0) > 0 },
    { label: '移除欄位', base: '—', target: joined(diff.columnsRemoved, '無'), changed: (diff.columnsRemoved?.length ?? 0) > 0 },
    { label: '建立時間', base: base.created_at, target: target.created_at, changed: base.created_at !== target.created_at },
  ]
  return { diff, rows, changedCount: rows.filter((row) => row.changed).length }
}

export interface LineageEntry {
  versionId: string
  label: string
}

/** 血緣只取已讀取版本的時間序；父版本關聯後端未揭露，不得推測。 */
export function buildVersionLineage(versions: DatasetVersion[]): LineageEntry[] {
  return [...versions]
    .sort((left, right) => (left.created_at < right.created_at ? -1 : 1))
    .map((version) => ({
      versionId: version.id,
      label: `${version.created_at}｜${FORMAT_LABELS[version.format]}｜${String(version.row_count)} 列`,
    }))
}
