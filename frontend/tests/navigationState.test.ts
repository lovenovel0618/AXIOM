import { describe, expect, it } from 'vitest'
import { readBackRef, withBackRef } from '../src/lib/navigationState'

describe('navigationState', () => {
  it('reads the back reference from query', () => {
    expect(readBackRef({ ref: '/verification?submission=sub-1' })).toBe('/verification?submission=sub-1')
    expect(readBackRef({})).toBe('')
  })

  it('builds query objects with a back reference', () => {
    expect(withBackRef('/researches/r1?version=v1')).toEqual({
      ref: '/researches/r1?version=v1',
    })
    expect(withBackRef('/discoveries?run=1', { version: 'v2' })).toEqual({
      version: 'v2',
      ref: '/discoveries?run=1',
    })
  })
})
