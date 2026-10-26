/**
 * SSOT 20「隱藏變數探索」的資料來源：PROFILE 產出的結構評估產物（StructureAssessment）。
 *
 * 契約只承認 `research-learning-v1.schema.json` 的白名單欄位；形狀不符一律回 null，畫面顯示「未取得」。
 * 內在維度與結構判斷目前後端一律回 null／UNKNOWN，本模組不補值、不從中介資料推測可識別性。
 */
import type { Research, ResearchVersion, ResearchVersionStatus } from '../api/research'

export type StructureCandidate =
  | 'INDEX_SEQUENCE'
  | 'TIME_SERIES'
  | 'MULTI_SERIES'
  | 'POINT_CLOUD'
  | 'SPATIAL_FIELD'
  | 'UNKNOWN'

export type TimeBasis = 'OBSERVED_TIMESTAMP' | 'INDEX_ONLY' | 'UNKNOWN'

export type Periodicity = 'FIXED' | 'DRIFTING' | 'MULTIPLE' | 'NOT_DETECTED' | 'UNKNOWN'

export type AnalysisScope = 'METADATA_ONLY' | 'FIT_ONLY'

export const STRUCTURE_CANDIDATE_LABELS: Record<StructureCandidate, string> = {
  INDEX_SEQUENCE: '索引序列',
  TIME_SERIES: '時間序列',
  MULTI_SERIES: '多序列',
  POINT_CLOUD: '點雲',
  SPATIAL_FIELD: '空間場',
  UNKNOWN: '未判定',
}

export const TIME_BASIS_LABELS: Record<TimeBasis, string> = {
  OBSERVED_TIMESTAMP: '觀測時間戳',
  INDEX_ONLY: '僅索引',
  UNKNOWN: '未判定',
}

export const PERIODICITY_LABELS: Record<Periodicity, string> = {
  FIXED: '固定週期',
  DRIFTING: '漂移週期',
  MULTIPLE: '多重週期',
  NOT_DETECTED: '未偵測到',
  UNKNOWN: '未判定',
}

export const ANALYSIS_SCOPE_LABELS: Record<AnalysisScope, string> = {
  METADATA_ONLY: '僅中介資料與形狀',
  FIT_ONLY: '僅擬合區段純量品質',
}

export interface SourceColumn {
  name: string
  physicalType: string
}

export interface StructureAssessment {
  id: string
  researchVersionId: string | null
  datasetVersionId: string
  createdAt: string
  accessClass: 'PROJECT' | 'SEALED_DETAIL'
  observationDimension: number
  coordinateDimension: number | null
  representationDimension: number
  intrinsicDimensionEstimate: number | null
  structureCandidates: StructureCandidate[]
  timeBasis: TimeBasis
  periodicity: Periodicity
  methodManifestId: string
  fitRowsHash: string | null
  uncertaintyReason: string
  analysisScope: AnalysisScope
  sourceRowCount: number | null
  sourceColumns: SourceColumn[]
}

const STRUCTURE_CANDIDATES: readonly StructureCandidate[] = [
  'INDEX_SEQUENCE',
  'TIME_SERIES',
  'MULTI_SERIES',
  'POINT_CLOUD',
  'SPATIAL_FIELD',
  'UNKNOWN',
]
const TIME_BASES: readonly TimeBasis[] = ['OBSERVED_TIMESTAMP', 'INDEX_ONLY', 'UNKNOWN']
const PERIODICITIES: readonly Periodicity[] = ['FIXED', 'DRIFTING', 'MULTIPLE', 'NOT_DETECTED', 'UNKNOWN']
const ANALYSIS_SCOPES: readonly AnalysisScope[] = ['METADATA_ONLY', 'FIT_ONLY']
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/iu
const SHA256 = /^[0-9a-f]{64}$/

function member<T extends string>(candidates: readonly T[], value: unknown): value is T {
  return typeof value === 'string' && (candidates as readonly string[]).includes(value)
}

function requiredString(source: Record<string, unknown>, key: string): string | null {
  const value = source[key]
  return typeof value === 'string' && value !== '' ? value : null
}

function positiveInteger(source: Record<string, unknown>, key: string): number | null {
  const value = source[key]
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < 1) return null
  return value
}

function optionalPositiveInteger(source: Record<string, unknown>, key: string): number | null {
  const value = source[key]
  if (value === null || value === undefined) return null
  return positiveInteger(source, key)
}

function optionalNonNegativeNumber(source: Record<string, unknown>, key: string): number | null {
  const value = source[key]
  if (value === null || value === undefined) return null
  if (typeof value !== 'number' || !Number.isFinite(value) || value < 0) return null
  return value
}

function parseSourceColumns(value: unknown): SourceColumn[] | null {
  if (value === undefined || value === null) return []
  if (typeof value !== 'object' || value === null) return null
  const columns: unknown = (value as Record<string, unknown>).columns
  if (columns === undefined || columns === null) return []
  if (!Array.isArray(columns)) return null
  const parsed: SourceColumn[] = []
  for (const column of columns) {
    if (typeof column !== 'object' || column === null) return null
    const record = column as Record<string, unknown>
    const name = requiredString(record, 'name')
    const physicalType = requiredString(record, 'physical_type')
    if (name === null || physicalType === null) return null
    parsed.push({ name, physicalType })
  }
  return parsed
}

/** 整份契約欄位皆須符合才接受；任一必要欄位不符即回 null，不以補值方式蒙混過關。 */
export function parseStructureAssessment(value: unknown): StructureAssessment | null {
  if (typeof value !== 'object' || value === null) return null
  const source = value as Record<string, unknown>

  if (source.kind !== 'StructureAssessment') return null
  const id = requiredString(source, 'id')
  const tenantId = requiredString(source, 'tenant_id')
  const datasetVersionId = requiredString(source, 'dataset_version_id')
  const methodManifestId = requiredString(source, 'method_manifest_id')
  const createdAt = requiredString(source, 'created_at')
  const uncertaintyReason = requiredString(source, 'uncertainty_reason')
  if (id === null || !UUID.test(id)) return null
  if (tenantId === null || !UUID.test(tenantId)) return null
  if (datasetVersionId === null || !UUID.test(datasetVersionId)) return null
  if (methodManifestId === null || !UUID.test(methodManifestId)) return null
  if (createdAt === null || uncertaintyReason === null) return null
  if (source.schema_version !== '1.0') return null
  if (source.artifact_access_class !== 'PROJECT' && source.artifact_access_class !== 'SEALED_DETAIL') return null
  if (!member(TIME_BASES, source.time_basis)) return null
  if (!member(PERIODICITIES, source.periodicity)) return null
  if (!member(ANALYSIS_SCOPES, source.analysis_scope)) return null

  const observationDimension = positiveInteger(source, 'observation_dimension')
  const representationDimension = positiveInteger(source, 'representation_dimension')
  if (observationDimension === null || representationDimension === null) return null

  const researchVersionValue: unknown = source.research_version_id
  if (researchVersionValue !== null && typeof researchVersionValue !== 'string') return null
  if (typeof researchVersionValue === 'string' && !UUID.test(researchVersionValue)) return null

  if (!Array.isArray(source.structure_candidates) || source.structure_candidates.length === 0) return null
  const structureCandidates: StructureCandidate[] = []
  for (const candidate of source.structure_candidates) {
    if (!member(STRUCTURE_CANDIDATES, candidate)) return null
    structureCandidates.push(candidate)
  }

  const sourceColumns = parseSourceColumns(source.source_metadata)
  if (sourceColumns === null) return null
  const rowCount = (() => {
    if (typeof source.source_metadata !== 'object' || source.source_metadata === null) return null
    return optionalPositiveInteger(source.source_metadata as Record<string, unknown>, 'row_count')
  })()

  const fitRowsHash = source.fit_rows_hash
  if (fitRowsHash !== null && (typeof fitRowsHash !== 'string' || !SHA256.test(fitRowsHash))) return null

  return {
    id,
    researchVersionId: typeof researchVersionValue === 'string' ? researchVersionValue : null,
    datasetVersionId,
    createdAt,
    accessClass: source.artifact_access_class,
    observationDimension,
    coordinateDimension: optionalPositiveInteger(source, 'coordinate_dimension'),
    representationDimension,
    intrinsicDimensionEstimate: optionalNonNegativeNumber(source, 'intrinsic_dimension_estimate'),
    structureCandidates,
    timeBasis: source.time_basis,
    periodicity: source.periodicity,
    methodManifestId,
    fitRowsHash,
    uncertaintyReason,
    analysisScope: source.analysis_scope,
    sourceRowCount: rowCount,
    sourceColumns,
  }
}

/** 只有後端明確給出內在維度、且結構候選不只是 UNKNOWN 時，才視為已識別。 */
export function isStructureIdentified(assessment: StructureAssessment): boolean {
  if (assessment.intrinsicDimensionEstimate === null) return false
  return assessment.structureCandidates.some((candidate) => candidate !== 'UNKNOWN')
}

export interface LatentRow {
  versionId: string
  researchId: string
  researchName: string
  versionStatus: ResearchVersionStatus
  versionCreatedAt: string
  artifactId: string | null
  assessment: StructureAssessment | null
  /** 產物存在但解析失敗時保留原因，畫面照實顯示而不是假裝沒有資料。 */
  parseFailed: boolean
}

function researchNameOf(researches: Research[], researchId: string): string {
  return researches.find((row) => row.id === researchId)?.name ?? '未命名研究'
}

/** 每個研究版本一列；沒有結構產物或解析失敗時 assessment 為 null，由畫面顯示「未取得」。 */
export function buildLatentRows(
  versions: ResearchVersion[],
  researches: Research[],
  assessments: Record<string, StructureAssessment | null>,
  parseFailures: Set<string>,
): LatentRow[] {
  return versions.map((version) => {
    const artifactId = version.structure_assessment_artifact_id
    return {
      versionId: version.id,
      researchId: version.research_id,
      researchName: researchNameOf(researches, version.research_id),
      versionStatus: version.status,
      versionCreatedAt: version.created_at,
      artifactId,
      assessment: artifactId === null ? null : (assessments[artifactId] ?? null),
      parseFailed: artifactId !== null && parseFailures.has(artifactId),
    }
  })
}

/** 已識別列數；未取得與未判定一律不計入，避免把「沒有資料」誤讀成「已確認低維」。 */
export function countIdentifiedRows(rows: LatentRow[]): number {
  return rows.filter((row) => row.assessment !== null && isStructureIdentified(row.assessment)).length
}

export interface LatentSummary {
  /** 後端明確給出內在維度且結構不只 UNKNOWN 的版本數。 */
  identified: number
  /** 版本帶有結構評估產物、且成功解析的數量。 */
  artifactBacked: number
  /** 版本沒有結構評估產物：PROFILE 尚未產生或未揭露。 */
  missing: number
  /** 產物存在但契約不符而解析失敗的數量。 */
  parseFailed: number
}

export function summarizeLatent(rows: LatentRow[]): LatentSummary {
  let identified = 0
  let artifactBacked = 0
  let missing = 0
  let parseFailed = 0

  for (const row of rows) {
    if (row.parseFailed) parseFailed += 1
    else if (row.assessment === null) missing += 1
    else {
      artifactBacked += 1
      if (isStructureIdentified(row.assessment)) identified += 1
    }
  }

  return { identified, artifactBacked, missing, parseFailed }
}

/** 本頁實際讀取的範圍；後端仍有未讀取頁面時 `truncated` 為真，畫面必須明示。 */
export interface LatentScope {
  researchesRead: number
  versionsRead: number
  truncated: boolean
}

export interface LatentSnapshot {
  rows: LatentRow[]
  summary: LatentSummary
  scope: LatentScope
}

