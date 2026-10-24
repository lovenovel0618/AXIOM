/**
 * DSL v1 AST 的純文字渲染與複雜度計算；純函式、無副作用，方便直接驗測。
 * 只呈現契約已定義的節點，遇到未知形狀回傳穩定字串而非猜測語意。
 */
import type { Comparator, DslDomain, DslNode, Rational } from '../api/candidates'

const BINARY: Record<'add' | 'mul' | 'sub' | 'div' | 'pow', string> = {
  add: '+',
  mul: '*',
  sub: '-',
  div: '/',
  pow: '^',
}

const COMPARATORS: Record<Comparator, string> = { lt: '<', lte: '<=', gt: '>', gte: '>=' }

/** 有理數以「分子/分母」呈現；分母為 1 時只顯示分子。 */
export function renderRational(value: Rational): string {
  return value.denominator === '1' ? value.numerator : `${value.numerator}/${value.denominator}`
}

export function renderFormula(node: DslNode): string {
  switch (node.op) {
    case 'const':
      return renderRational(node.value)
    case 'var':
    case 'param':
      return node.name
    case 'sin':
    case 'cos':
    case 'exp':
    case 'log':
    case 'abs':
      return `${node.op}(${node.args.map(renderFormula).join(', ')})`
    case 'piecewise':
      return renderPiecewise(node)
    default:
      return `(${node.args.map(renderFormula).join(` ${BINARY[node.op]} `)})`
  }
}

function renderPiecewise(node: Extract<DslNode, { op: 'piecewise' }>): string {
  const branches = node.branches.map((branch) => {
    const operator = COMPARATORS[branch.when.comparator]
    return `${renderFormula(branch.then)} 若 ${branch.when.var} ${operator} ${renderRational(branch.when.value)}`
  })
  return `{ ${[...branches, `否則 ${renderFormula(node.otherwise)}`].join('；')} }`
}

/** 模型複雜度定義為 AST 節點總數（含常數與葉節點），可跨候選一致比較。 */
export function formulaComplexity(node: DslNode): number {
  switch (node.op) {
    case 'const':
    case 'var':
    case 'param':
      return 1
    case 'piecewise':
      return (
        1 +
        node.branches.reduce((sum, branch) => sum + formulaComplexity(branch.then), 0) +
        formulaComplexity(node.otherwise)
      )
    default:
      return 1 + node.args.reduce((sum, argument) => sum + formulaComplexity(argument), 0)
  }
}

/** 定義域以半開區間呈現，端點是否閉合直接影響可比性，必須與契約一致。 */
export function renderDomain(domains: DslDomain[]): string {
  return domains
    .map((domain) => {
      const lower = domain.lower_closed ? '[' : '('
      const upper = domain.upper_closed ? ']' : ')'
      return `${domain.name} ∈ ${lower}${renderRational(domain.lower)}, ${renderRational(domain.upper)}${upper}`
    })
    .join('；')
}

/** 單一十進位字串的有效位數；canonical 值無尾零，故去號與小數點後計數即可。 */
export function significantDigits(value: string): number {
  const digits = value.replace(/^[-+]/, '').replace('.', '').replace(/^0+/, '')
  return digits === '' ? 1 : digits.length
}

export function parameterPrecision(parameters: Record<string, string>): number {
  return Object.values(parameters).reduce((max, value) => Math.max(max, significantDigits(value)), 0)
}
