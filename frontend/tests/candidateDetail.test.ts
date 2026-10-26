import { describe, expect, it } from 'vitest'
import type { Candidate, EquationVersion, FitRun } from '../src/api/candidates'
import type { ValidationRun } from '../src/lib/evaluation'
import {
  buildCandidatePeerRows,
  buildCandidateReading,
  findCandidate,
  orderedFits,
  PEER_LIMIT,
  renderUnit,
} from '../src/lib/candidateDetail'

function candidate(overrides: Partial<Candidate> = {}): Candidate {
  return {
    kind: 'Candidate',
    id: 'candidate-1',
    tenant_id: 'tenant-1',
    schema_version: 'v1',
    created_at: '2026-10-26T00:00:00Z',
    search_run_id: 'run-search-1',
    equation_version_id: 'equation-1',
    source: 'SEARCH',
    development_rank: 1,
    validation_status: 'NOT_RUN',
    fit_run_ids: [],
    validation_run_ids: [],
    ...overrides,
  }
}

function equation(overrides: Partial<EquationVersion> = {}): EquationVersion {
  return {
    kind: 'EquationVersion',
    id: 'equation-1',
    tenant_id: 'tenant-1',
    schema_version: 'v1',
    created_at: '2026-10-26T00:00:00Z',
    identity_hash: 'hash-1',
    dsl: {
      dsl_version: 'v1',
      variables: [{ name: 'x', unit: [1, 0, 0] }],
      parameters: [{ name: 'a', unit: [0, 0, 0], lower: '-2', upper: '2' }],
      domain: [{ name: 'x', lower: { numerator: '0', denominator: '1' }, upper: { numerator: '10', denominator: '1' }, lower_closed: true, upper_closed: false }],
      root: { op: 'mul', args: [{ op: 'param', name: 'a' }, { op: 'sin', args: [{ op: 'var', name: 'x' }] }] },
    },
    ...overrides,
  }
}

function fit(overrides: Partial<FitRun> = {}): FitRun {
  return {
    kind: 'FitRun',
    id: 'fit-1',
    tenant_id: 'tenant-1',
    schema_version: 'v1',
    created_at: '2026-10-26T00:00:00Z',
    run_id: 'run-fit-1',
    equation_version_id: 'equation-1',
    dataset_version_id: 'datasetversion-1',
    parameters: { a: '1.2345' },
    optimizer: 'LBFGS',
    observation_split_id: 'split-1',
    split_role: 'FIT',
    precision_bits: 53,
    fit_row_ids: [1, 2, 3],
    fit_rows_hash: 'rows-hash',
    representation_artifact_id: 'artifact-1',
    ...overrides,
  }
}

function validation(overrides: Partial<ValidationRun> = {}): ValidationRun {
  return {
    id: 'validation-1',
    outcome: 'SUPPORTED',
    metricVersion: 'v1',
    splitRole: 'FINAL_TEST',
    empiricalLevel: 'E2',
    proofLevel: 'P0',
    mae: 0.1,
    rmse: 0.2,
    metricReasons: {},
    validCoverage: 0.9,
    selectedCount: 10,
    validCount: 9,
    failedCount: 1,
    sha256: 'a'.repeat(64),
    createdAt: '2026-10-26T00:00:00Z',
    ...overrides,
  }
}

describe('renderUnit', () => {
  it('treats an all-zero dimension as dimensionless', () => {
    expect(renderUnit([0, 0, 0])).toBe('無因次')
    expect(renderUnit([])).toBe('無因次')
  })

  it('renders a dimension vector otherwise', () => {
    expect(renderUnit([1, 0, -2])).toBe('[1, 0, -2]')
  })
})

describe('findCandidate', () => {
  it('returns null when the candidate is absent', () => {
    expect(findCandidate([candidate()], 'missing')).toBeNull()
    expect(findCandidate([candidate()], 'candidate-1')?.id).toBe('candidate-1')
  })
})

describe('orderedFits', () => {
  it('keeps declared order and skips unloaded fits', () => {
    const rows = orderedFits(candidate({ fit_run_ids: ['fit-1', 'fit-2'] }), { 'fit-2': fit({ id: 'fit-2' }) })
    expect(rows.map((row) => row.id)).toEqual(['fit-2'])
  })
})

describe('buildCandidateReading', () => {
  it('reports formula, parameters and fit precision from disclosed fields', () => {
    const reading = buildCandidateReading(
      candidate({ fit_run_ids: ['fit-1'], validation_run_ids: ['validation-1'] }),
      equation(),
      [fit()],
      { 'validation-1': validation() },
    )
    expect(reading.formulaText).toBe('(a * sin(x))')
    expect(reading.complexity).toBe(4)
    expect(reading.identityHash).toBe('hash-1')
    expect(reading.domains).toBe('x ∈ [0, 10)')
    expect(reading.parameters?.[0]).toEqual({ name: 'a', unit: '無因次', lower: '-2', upper: '2', fittedValue: '1.2345' })
    expect(reading.variables?.[0]).toEqual({ name: 'x', unit: '[1, 0, 0]' })
    expect(reading.fits[0]?.fitRowCount).toBe(3)
    expect(reading.fitPrecisionBits).toBe(5)
    expect(reading.validations.map((row) => row.id)).toEqual(['validation-1'])
    expect(reading.missingValidationIds).toEqual([])
  })

  it('marks missing equation content as unavailable instead of guessing', () => {
    const reading = buildCandidateReading(candidate(), null, [], {})
    expect(reading.formulaText).toBeNull()
    expect(reading.complexity).toBeNull()
    expect(reading.domains).toBeNull()
    expect(reading.parameters).toBeNull()
    expect(reading.variables).toBeNull()
    expect(reading.identityHash).toBeNull()
    expect(reading.fitPrecisionBits).toBeNull()
  })

  it('lists unparsable validation ids instead of pretending they loaded', () => {
    const reading = buildCandidateReading(
      candidate({ validation_run_ids: ['validation-1', 'validation-2'] }),
      equation(),
      [],
      { 'validation-1': validation() },
    )
    expect(reading.validations).toHaveLength(1)
    expect(reading.missingValidationIds).toEqual(['validation-2'])
  })

  it('leaves the fitted value unset when no fit discloses the parameter', () => {
    const reading = buildCandidateReading(candidate({ fit_run_ids: ['fit-1'] }), equation(), [fit({ parameters: {} })], {})
    expect(reading.parameters?.[0]?.fittedValue).toBeNull()
    expect(reading.fitPrecisionBits).toBe(0)
  })
})

describe('buildCandidatePeerRows', () => {
  it('sorts by rank, keeps null ranks last and caps the list', () => {
    const rows = Array.from({ length: PEER_LIMIT + 3 }, (_, index) =>
      candidate({ id: `candidate-${String(index)}`, development_rank: index + 1, equation_version_id: `equation-${String(index)}` }),
    )
    rows.push(candidate({ id: 'candidate-null', development_rank: null, equation_version_id: 'equation-null' }))
    const peers = buildCandidatePeerRows(rows, {}, {}, 'candidate-2')
    expect(peers).toHaveLength(PEER_LIMIT)
    expect(peers[0]?.id).toBe('candidate-0')
    expect(peers.every((row) => row.rank !== null)).toBe(true)
    expect(peers.find((row) => row.id === 'candidate-2')?.active).toBe(true)
  })

  it('exposes complexity and precision from loaded equation and fit', () => {
    const peers = buildCandidatePeerRows(
      [candidate({ fit_run_ids: ['fit-1'] })],
      { 'equation-1': equation() },
      { 'fit-1': fit() },
      'candidate-1',
    )
    expect(peers[0]?.complexity).toBe(4)
    expect(peers[0]?.parameterCount).toBe(1)
    expect(peers[0]?.precisionBits).toBe(5)
  })

  it('reports null metrics when nothing is loaded', () => {
    const peers = buildCandidatePeerRows([candidate()], {}, {}, 'candidate-1')
    expect(peers[0]?.complexity).toBeNull()
    expect(peers[0]?.parameterCount).toBeNull()
    expect(peers[0]?.precisionBits).toBeNull()
  })
})
