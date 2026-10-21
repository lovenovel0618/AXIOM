/**
 * 語意確認的純邏輯：把表單模型整理成後端固定的 CreateResearchVersion 請求。
 * 前端檢查只重述文件化規則以便早一步提示；後端仍是唯一權威判定者。
 */
import type {
  Baseline,
  BudgetLimit,
  CreateResearchVersionRequest,
  DomainInterval,
  EvaluationPolicy,
  ResearchPurpose,
  SemanticQuantity,
} from '../api/research'

const NAME = /^[A-Za-z_][A-Za-z0-9_]{0,63}$/
const DECIMAL = /^(0|[1-9][0-9]*)(\.[0-9]+)?$/
const POSITIVE_DECIMAL = /^(?!0(\.0+)?$)(0|[1-9][0-9]*)(\.[0-9]+)?$/
const NUMERATOR = /^-?(0|[1-9][0-9]{0,127})$/
const DENOMINATOR = /^[1-9][0-9]{0,127}$/
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

/** 後端只支援無時間、無群組的獨立列切分。 */
export const SPLITTER_VERSION = 'axiom-ui-sequential-v1'
export const SPLIT_POLICY_VERSION = '2.0'
export const DIMENSION_AXES = 7
export const DIMENSION_BOUND = 32

export interface ColumnMetadata {
  name: string
  physical_type: string
}

export interface SourceMetadata {
  row_count: number
  columns: ColumnMetadata[]
}

export interface Partitions {
  fit: number[]
  development: number[]
  final_test: number[]
}

/** 結構預覽產物為不可信輸入，形狀不符就當作沒有可用 metadata。 */
export function parseSourceMetadata(value: unknown): SourceMetadata | null {
  if (typeof value !== 'object' || value === null) return null
  if (!('source_metadata' in value)) return null
  const metadata: unknown = value.source_metadata
  if (typeof metadata !== 'object' || metadata === null) return null
  if (!('row_count' in metadata) || !('columns' in metadata)) return null
  const count: unknown = metadata.row_count
  const columns: unknown = metadata.columns
  if (typeof count !== 'number' || !Number.isInteger(count) || count < 0) return null
  if (!Array.isArray(columns)) return null
  const parsed: ColumnMetadata[] = []
  for (const column of columns) {
    if (typeof column !== 'object' || column === null) return null
    if (!('name' in column) || typeof column.name !== 'string' || column.name === '') return null
    const physical: unknown = 'physical_type' in column ? column.physical_type : ''
    parsed.push({ name: column.name, physical_type: typeof physical === 'string' ? physical : '' })
  }
  return { row_count: count, columns: parsed }
}

/** 七維量綱向量：-32～32 的整數，以逗號分隔輸入。 */
export function parseDimension(text: string): number[] | null {
  const parts = text.split(',').map((part) => part.trim())
  if (parts.length !== DIMENSION_AXES) return null
  const values: number[] = []
  for (const part of parts) {
    if (!/^-?\d+$/.test(part)) return null
    const value = Number(part)
    if (!Number.isInteger(value) || Math.abs(value) > DIMENSION_BOUND) return null
    values.push(value)
  }
  return values
}

/** 依列序固定均分：前 60% fit、次 20% development、後 20% final_test，每列恰屬一區。 */
export function sequentialSplit(rowCount: number): Partitions | null {
  if (!Number.isInteger(rowCount) || rowCount < 3) return null
  const fitEnd = Math.max(1, Math.floor((rowCount * 3) / 5))
  const developmentEnd = Math.max(fitEnd + 1, Math.floor((rowCount * 4) / 5))
  if (developmentEnd > rowCount - 1) return null
  const range = (start: number, end: number): number[] =>
    Array.from({ length: end - start }, (_item, offset) => start + offset)
  return {
    fit: range(0, fitEnd),
    development: range(fitEnd, developmentEnd),
    final_test: range(developmentEnd, rowCount),
  }
}

export interface VersionFormModel {
  datasetVersionId: string
  rowCount: number
  inputName: string
  inputColumn: string
  inputUnit: string
  inputSourceUnit: string
  inputScale: string
  inputOffset: string
  targetName: string
  targetColumn: string
  targetUnit: string
  targetSourceUnit: string
  targetScale: string
  targetOffset: string
  measurementResolution: string
  resolutionReason: string
  purpose: ResearchPurpose
  domainLowerNumerator: string
  domainLowerDenominator: string
  domainUpperNumerator: string
  domainUpperDenominator: string
  seed: string
  baseline: Baseline
  practicalMarginRatio: string
  cpuSeconds: string
  gpuSeconds: string
  wallSeconds: string
  tokens: string
  candidateLimit: string
  memoryBytes: string
}

export const DEFAULT_VERSION_FORM: VersionFormModel = {
  datasetVersionId: '',
  rowCount: 0,
  inputName: 'x',
  inputColumn: '',
  inputUnit: '0, 0, 0, 0, 0, 0, 0',
  inputSourceUnit: '1',
  inputScale: '1',
  inputOffset: '0',
  targetName: 'y',
  targetColumn: '',
  targetUnit: '0, 0, 0, 0, 0, 0, 0',
  targetSourceUnit: '1',
  targetScale: '1',
  targetOffset: '0',
  measurementResolution: '',
  resolutionReason: '',
  purpose: 'DESCRIPTION',
  domainLowerNumerator: '0',
  domainLowerDenominator: '1',
  domainUpperNumerator: '1',
  domainUpperDenominator: '1',
  seed: '0',
  baseline: 'FIT_MEAN',
  practicalMarginRatio: '0.01',
  cpuSeconds: '60',
  gpuSeconds: '0',
  wallSeconds: '120',
  tokens: '0',
  candidateLimit: '0',
  memoryBytes: '2147483648',
}

export interface DraftOutcome {
  request: CreateResearchVersionRequest | null
  problems: string[]
}

function integer(text: string, minimum: number, maximum: number): number | null {
  if (!/^\d+$/.test(text.trim())) return null
  const value = Number(text.trim())
  if (!Number.isSafeInteger(value) || value < minimum || value > maximum) return null
  return value
}

function seconds(text: string): number | null {
  const trimmed = text.trim()
  if (!DECIMAL.test(trimmed)) return null
  const value = Number(trimmed)
  return Number.isFinite(value) && value >= 0 && value <= 300 ? value : null
}

/** 以整數交叉相乘比較兩分數，避免先轉浮點而誤判觀測值域端點。 */
export function compareFractions(
  left: { numerator: string; denominator: string },
  right: { numerator: string; denominator: string },
): number | null {
  if (!NUMERATOR.test(left.numerator) || !DENOMINATOR.test(left.denominator)) return null
  if (!NUMERATOR.test(right.numerator) || !DENOMINATOR.test(right.denominator)) return null
  const a = BigInt(left.numerator) * BigInt(right.denominator)
  const b = BigInt(right.numerator) * BigInt(left.denominator)
  if (a === b) return 0
  return a < b ? -1 : 1
}

function quantity(
  model: VersionFormModel,
  kind: 'input' | 'target',
): { value: SemanticQuantity | null; problems: string[] } {
  const name = kind === 'input' ? model.inputName.trim() : model.targetName.trim()
  const column = kind === 'input' ? model.inputColumn : model.targetColumn
  const dimension = kind === 'input' ? model.inputUnit : model.targetUnit
  const sourceUnit = kind === 'input' ? model.inputSourceUnit : model.targetSourceUnit
  const scale = kind === 'input' ? model.inputScale : model.targetScale
  const offset = kind === 'input' ? model.inputOffset : model.targetOffset
  const label = kind === 'input' ? '輸入' : '目標'
  const problems: string[] = []
  if (!NAME.test(name)) problems.push(`${label}名稱需符合 ^[A-Za-z_][A-Za-z0-9_]{0,63}$。`)
  if (column === '') problems.push(`${label}必須選擇來源欄位。`)
  const parsed = parseDimension(dimension)
  if (parsed === null) {
    problems.push(`${label}量綱需為 ${String(DIMENSION_AXES)} 個 -${String(DIMENSION_BOUND)}～${String(DIMENSION_BOUND)} 的整數，以逗號分隔。`)
  }
  if (sourceUnit.trim() === '') problems.push(`${label}來源單位不可空白。`)
  if (!POSITIVE_DECIMAL.test(scale.trim())) problems.push(`${label}換算比例需為大於 0 的十進位字串。`)
  if (!DECIMAL.test(offset.trim())) problems.push(`${label}換算位移需為十進位字串。`)
  if (problems.length > 0 || parsed === null) return { value: null, problems }
  return {
    value: {
      name,
      unit: parsed,
      source_column: column,
      conversion: { source_unit: sourceUnit.trim(), scale: scale.trim(), offset: offset.trim() },
    },
    problems,
  }
}

/**
 * 依文件化規則組出請求；任何檢查未通過就回 null 並列出原因，不送出半成品。
 * 時間序與群組依賴在後端仍為未實作能力，這裡固定不宣告。
 */
export function buildDraftRequest(model: VersionFormModel): DraftOutcome {
  const problems: string[] = []
  const note = (condition: boolean, message: string): void => {
    if (!condition) problems.push(message)
  }

  note(UUID.test(model.datasetVersionId), '請先選擇一個可用的資料集版本。')
  const input = quantity(model, 'input')
  const target = quantity(model, 'target')
  problems.push(...input.problems, ...target.problems)
  note(model.inputColumn !== model.targetColumn, '輸入與目標不可使用同一個來源欄位。')
  note(model.inputName.trim() !== model.targetName.trim(), '輸入與目標不可同名。')
  note(model.resolutionReason.trim() !== '', '必須說明解析度判定的理由（resolution_reason）。')

  const resolution = model.measurementResolution.trim()
  note(
    resolution === '' || POSITIVE_DECIMAL.test(resolution),
    '量測解析度可留白，填寫時需為大於 0 的十進位字串。',
  )

  const seed = integer(model.seed, 0, Number.MAX_SAFE_INTEGER)
  note(seed !== null, '切分與 bootstrap 種子需為非負整數。')
  const split = sequentialSplit(model.rowCount)
  note(split !== null, '結構預覽列數不足（至少 3 列）才能固定三段切分。')

  const lower = { numerator: model.domainLowerNumerator.trim(), denominator: model.domainLowerDenominator.trim() }
  const upper = { numerator: model.domainUpperNumerator.trim(), denominator: model.domainUpperDenominator.trim() }
  const order = compareFractions(lower, upper)
  note(order !== null, '觀測值域需以整數分子／正整數分母宣告。')
  note(order === null || order <= 0, '觀測值域下界必須小於上界（相等時兩端需為閉區間）。')

  note(
    POSITIVE_DECIMAL.test(model.practicalMarginRatio.trim()) &&
      Number(model.practicalMarginRatio.trim()) <= 1,
    '實務邊界比例需為 (0, 1] 的十進位字串。',
  )

  const cpu = seconds(model.cpuSeconds)
  const wall = seconds(model.wallSeconds)
  const gpu = seconds(model.gpuSeconds)
  const tokens = integer(model.tokens, 0, Number.MAX_SAFE_INTEGER)
  const candidates = integer(model.candidateLimit, 0, Number.MAX_SAFE_INTEGER)
  const memory = integer(model.memoryBytes, 1, Number.MAX_SAFE_INTEGER)
  note(cpu !== null, 'CPU 秒數需為 0～300 的十進位數。')
  note(wall !== null, '牆鐘秒數需為 0～300 的十進位數。')
  note(gpu !== null, 'GPU 秒數需為 0～300 的十進位數。')
  note(tokens !== null, 'Token 上限需為非負整數。')
  note(candidates !== null, '候選上限需為非負整數。')
  note(memory !== null, '記憶體上限需為正整數位元組。')

  if (
    problems.length > 0 ||
    input.value === null ||
    target.value === null ||
    split === null ||
    seed === null ||
    cpu === null ||
    wall === null ||
    gpu === null ||
    tokens === null ||
    candidates === null ||
    memory === null
  ) {
    return { request: null, problems }
  }

  const budget: BudgetLimit = {
    cpu_seconds: cpu,
    gpu_seconds: gpu,
    wall_seconds: wall,
    tokens,
    candidate_limit: candidates,
    memory_bytes: memory,
  }
  const policy: EvaluationPolicy = {
    policy_version: '1.0',
    metric_version: '2.0',
    error_model: 'UNSPECIFIED',
    absolute_error_bound: null,
    comparison_method: 'NONE',
    bootstrap_replicates: 2000,
    bootstrap_seed: seed,
    block_method: null,
    block_length: null,
    practical_scale_override: null,
    practical_margin_ratio: model.practicalMarginRatio.trim(),
    baseline: model.baseline,
    practical_scale_reason: null,
  }
  const domain: DomainInterval[] = [
    {
      name: input.value.name,
      lower,
      upper,
      lower_closed: true,
      upper_closed: true,
    },
  ]
  return {
    request: {
      dataset_version_id: model.datasetVersionId,
      semantic_profile: {
        inputs: [input.value],
        target: target.value,
        units_confirmed: true,
        time_ordered: false,
        measurement_resolution: resolution === '' ? null : resolution,
        resolution_reason: model.resolutionReason.trim(),
        group_column: null,
      },
      budget,
      purpose: model.purpose,
      observation_split: {
        kind: 'EXPLICIT',
        dataset_version_id: model.datasetVersionId,
        fit: split.fit,
        development: split.development,
        final_test: split.final_test,
        gap_rows: 0,
        lookback_rows: 0,
        horizon_rows: 0,
        seed,
        time_column: null,
        group_column: null,
        group_assignment_digest: null,
        splitter_version: SPLITTER_VERSION,
        policy_version: SPLIT_POLICY_VERSION,
        sealed_final_test: true,
      },
      domain,
      evaluation_policy: policy,
    },
    problems,
  }
}
