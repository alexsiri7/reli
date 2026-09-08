import { describe, it, expect } from 'vitest'
import { parsePreferenceToasts, preferenceConfidenceLabel } from '../format/preferences'

describe('preferenceConfidenceLabel', () => {
  it('labels confidence >= 0.7 as strong', () => {
    expect(preferenceConfidenceLabel({ confidence: 0.7 })).toBe('strong')
    expect(preferenceConfidenceLabel({ confidence: 0.9 })).toBe('strong')
  })

  it('labels confidence >= 0.5 and < 0.7 as moderate', () => {
    expect(preferenceConfidenceLabel({ confidence: 0.5 })).toBe('moderate')
    expect(preferenceConfidenceLabel({ confidence: 0.69 })).toBe('moderate')
  })

  it('labels confidence below 0.5 as emerging', () => {
    expect(preferenceConfidenceLabel({ confidence: 0.49 })).toBe('emerging')
    expect(preferenceConfidenceLabel({ confidence: 0 })).toBe('emerging')
  })

  it('falls back to empty string when data is not an object', () => {
    expect(preferenceConfidenceLabel(null)).toBe('')
    expect(preferenceConfidenceLabel(undefined)).toBe('')
    expect(preferenceConfidenceLabel('not an object')).toBe('')
  })
})

describe('parsePreferenceToasts', () => {
  it('returns an empty toast list when changes is null or undefined', () => {
    expect(parsePreferenceToasts(null)).toEqual([])
    expect(parsePreferenceToasts(undefined)).toEqual([])
  })

  it('ignores created/updated items that are not preferences', () => {
    const toasts = parsePreferenceToasts({
      created: [{ id: 't1', title: 'Buy milk', type_hint: 'task' }],
    })
    expect(toasts).toEqual([])
  })

  it('falls back to empty confidence label when data is malformed JSON', () => {
    const toasts = parsePreferenceToasts({
      created: [{ id: 'pref-1', title: 'Prefers concise replies', type_hint: 'preference', data: '{not valid json' }],
    })
    expect(toasts).toHaveLength(1)
    expect(toasts[0]).toMatchObject({
      title: 'Prefers concise replies',
      confidenceLabel: '',
      action: 'created',
    })
  })

  it('parses created and updated preference items with stringified data', () => {
    const toasts = parsePreferenceToasts({
      created: [{ id: 'pref-1', title: 'Likes short answers', type_hint: 'preference', data: JSON.stringify({ confidence: 0.8 }) }],
      updated: [{ id: 'pref-2', title: 'Prefers dark mode', type_hint: 'preference', data: JSON.stringify({ confidence: 0.4 }) }],
    })
    expect(toasts).toHaveLength(2)
    expect(toasts[0]).toMatchObject({ title: 'Likes short answers', confidenceLabel: 'strong', action: 'created' })
    expect(toasts[1]).toMatchObject({ title: 'Prefers dark mode', confidenceLabel: 'emerging', action: 'updated' })
  })
})
