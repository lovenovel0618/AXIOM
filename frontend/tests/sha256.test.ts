import { describe, expect, it } from 'vitest'
import { sha256Hex } from '../src/lib/sha256'

describe('sha256Hex', () => {
  it('matches the known digest of "abc"', async () => {
    expect(await sha256Hex(new TextEncoder().encode('abc'))).toBe(
      'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad',
    )
  })

  it('matches the known digest of the empty input', async () => {
    expect(await sha256Hex(new Uint8Array())).toBe(
      'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
    )
  })

  it('always emits 64 lowercase hex characters', async () => {
    expect(await sha256Hex(new Uint8Array([0, 1, 255]))).toMatch(/^[0-9a-f]{64}$/)
  })
})
