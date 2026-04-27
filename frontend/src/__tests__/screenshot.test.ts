import { describe, it, expect } from 'vitest'
import { isWithinSizeLimit } from '../lib/screenshot'

describe('isWithinSizeLimit', () => {
  it('returns true for an empty string', () => {
    expect(isWithinSizeLimit('')).toBe(true)
  })

  it('returns true for a string representing exactly 2MB', () => {
    // floor(2097152 * 4/3) = 2796202 base64 chars → bytes = 2796202 * 3/4 = 2097151.5 ≤ 2097152
    const atLimit = 'A'.repeat(Math.floor(2097152 * 4 / 3))
    expect(isWithinSizeLimit(atLimit)).toBe(true)
  })

  it('returns false for a string representing just over 2MB', () => {
    const over2MB = 'A'.repeat(Math.floor(2097152 * 4 / 3) + 100)
    expect(isWithinSizeLimit(over2MB)).toBe(false)
  })
})
