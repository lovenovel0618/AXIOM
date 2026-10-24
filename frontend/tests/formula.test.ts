import { describe, expect, it } from 'vitest'
import type { DslNode } from '../src/api/candidates'
import {
  formulaComplexity,
  parameterPrecision,
  renderDomain,
  renderFormula,
  renderRational,
  significantDigits,
} from '../src/lib/formula'

describe('renderRational', () => {
  it('drops the denominator when it is one and keeps fractions otherwise', () => {
    expect(renderRational({ numerator: '3', denominator: '1' })).toBe('3')
    expect(renderRational({ numerator: '-1', denominator: '2' })).toBe('-1/2')
  })
})

describe('renderFormula', () => {
  it('renders a linear expression with parameters and variables', () => {
    const root: DslNode = {
      op: 'add',
      args: [
        { op: 'param', name: 'c0' },
        { op: 'mul', args: [{ op: 'param', name: 'c1' }, { op: 'var', name: 'x' }] },
      ],
    }
    expect(renderFormula(root)).toBe('(c0 + (c1 * x))')
  })

  it('renders unary functions and constants', () => {
    const root: DslNode = { op: 'sin', args: [{ op: 'const', value: { numerator: '1', denominator: '2' } }] }
    expect(renderFormula(root)).toBe('sin(1/2)')
  })

  it('renders piecewise branches with comparators and an otherwise arm', () => {
    const root: DslNode = {
      op: 'piecewise',
      branches: [
        {
          when: { var: 'x', comparator: 'lte', value: { numerator: '0', denominator: '1' } },
          then: { op: 'const', value: { numerator: '0', denominator: '1' } },
        },
      ],
      otherwise: { op: 'var', name: 'x' },
    }
    expect(renderFormula(root)).toBe('{ 0 若 x <= 0；否則 x }')
  })
})

describe('formulaComplexity', () => {
  it('counts every node, including leaves and branch arms', () => {
    const linear: DslNode = { op: 'add', args: [{ op: 'param', name: 'c0' }, { op: 'var', name: 'x' }] }
    expect(formulaComplexity(linear)).toBe(3)
    const branch: DslNode = {
      op: 'piecewise',
      branches: [{ when: { var: 'x', comparator: 'gt', value: { numerator: '1', denominator: '1' } }, then: { op: 'var', name: 'x' } }],
      otherwise: { op: 'const', value: { numerator: '0', denominator: '1' } },
    }
    expect(formulaComplexity(branch)).toBe(3)
  })
})

describe('renderDomain', () => {
  it('shows open and closed interval bounds explicitly', () => {
    expect(
      renderDomain([
        {
          name: 'x',
          lower: { numerator: '0', denominator: '1' },
          upper: { numerator: '5', denominator: '2' },
          lower_closed: true,
          upper_closed: false,
        },
      ]),
    ).toBe('x ∈ [0, 5/2)')
  })
})

describe('significantDigits', () => {
  it('counts distinct significant digits of canonical decimals', () => {
    expect(significantDigits('0')).toBe(1)
    expect(significantDigits('-3.1')).toBe(2)
    expect(significantDigits('0.05')).toBe(1)
    expect(significantDigits('100')).toBe(3)
  })
})

describe('parameterPrecision', () => {
  it('reports the widest parameter precision and zero when there are none', () => {
    expect(parameterPrecision({ c0: '2.5', c1: '10' })).toBe(2)
    expect(parameterPrecision({ c0: '0.125' })).toBe(3)
    expect(parameterPrecision({})).toBe(0)
  })
})
