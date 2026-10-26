import { describe, expect, it } from 'vitest'
import { readQueryList, readQueryString, selectionKey } from '../src/lib/queryState'

describe('queryState', () => {
  it('reads a string value from query', () => {
    expect(readQueryString({ q: 'search-term' }, 'q')).toBe('search-term')
    expect(readQueryString({ q: ['first', 'second'] }, 'q')).toBe('first')
    expect(readQueryString({}, 'q')).toBe('')
  })

  it('reads a comma separated list from query', () => {
    expect(readQueryList({ pins: 'a,b,c' }, 'pins')).toEqual(['a', 'b', 'c'])
    expect(readQueryList({ pins: '' }, 'pins')).toEqual([])
  })

  it('builds a stable selection key', () => {
    expect(selectionKey('最近任務', 'run-1')).toBe('最近任務::run-1')
  })
})
