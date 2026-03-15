import { describe, it, expect } from 'vitest'
import { typeIcon, formatDate, priorityLabel, formatTimestamp, isOverdue } from '../utils'

describe('typeIcon', () => {
  it('returns fallback icon for null hint', () => {
    expect(typeIcon(null)).toBe('📌')
  })

  it('returns fallback icon for undefined hint', () => {
    expect(typeIcon(undefined)).toBe('📌')
  })

  it('returns built-in icon for known type', () => {
    expect(typeIcon('task')).toBe('📋')
    expect(typeIcon('note')).toBe('📝')
    expect(typeIcon('project')).toBe('📁')
    expect(typeIcon('person')).toBe('👤')
  })

  it('is case-insensitive', () => {
    expect(typeIcon('Task')).toBe('📋')
    expect(typeIcon('NOTE')).toBe('📝')
  })

  it('returns default icon for unknown type', () => {
    expect(typeIcon('unknown_type')).toBe('📌')
  })

  it('prefers DB-backed thingTypes over fallback', () => {
    const thingTypes = [{ id: '1', name: 'task', icon: '✅', color: null, created_at: '' }]
    expect(typeIcon('task', thingTypes)).toBe('✅')
  })

  it('falls back to built-in when thingTypes has no match', () => {
    const thingTypes = [{ id: '1', name: 'custom', icon: '🎨', color: null, created_at: '' }]
    expect(typeIcon('task', thingTypes)).toBe('📋')
  })
})

describe('formatDate', () => {
  it('returns empty string for null', () => {
    expect(formatDate(null)).toBe('')
  })

  it('returns empty string for undefined', () => {
    expect(formatDate(undefined)).toBe('')
  })

  it('returns "Today" for today', () => {
    const today = new Date()
    expect(formatDate(today.toISOString())).toBe('Today')
  })

  it('returns "Tomorrow" for tomorrow', () => {
    const tomorrow = new Date()
    tomorrow.setDate(tomorrow.getDate() + 1)
    expect(formatDate(tomorrow.toISOString())).toBe('Tomorrow')
  })

  it('returns "Yesterday" for yesterday', () => {
    const yesterday = new Date()
    yesterday.setDate(yesterday.getDate() - 1)
    expect(formatDate(yesterday.toISOString())).toBe('Yesterday')
  })

  it('returns overdue label for past dates', () => {
    const past = new Date()
    past.setDate(past.getDate() - 3)
    expect(formatDate(past.toISOString())).toBe('3d overdue')
  })

  it('returns "In Nd" for near-future dates', () => {
    const future = new Date()
    future.setDate(future.getDate() + 3)
    expect(formatDate(future.toISOString())).toBe('In 3d')
  })

  it('returns month/day for dates >= 7 days away', () => {
    const far = new Date()
    far.setDate(far.getDate() + 10)
    const result = formatDate(far.toISOString())
    // Should be a localized date like "Mar 25"
    expect(result).not.toBe('')
    expect(result).not.toMatch(/In \d+d/)
  })
})

describe('priorityLabel', () => {
  it('returns labeled string for known priorities', () => {
    expect(priorityLabel(1)).toBe('🔴 Critical')
    expect(priorityLabel(2)).toBe('🟠 High')
    expect(priorityLabel(3)).toBe('🟡 Medium')
    expect(priorityLabel(4)).toBe('🔵 Low')
    expect(priorityLabel(5)).toBe('⚪ None')
  })

  it('returns fallback for unknown priority', () => {
    expect(priorityLabel(99)).toBe('Priority 99')
  })
})

describe('formatTimestamp', () => {
  it('returns empty string for null', () => {
    expect(formatTimestamp(null)).toBe('')
  })

  it('returns empty string for undefined', () => {
    expect(formatTimestamp(undefined)).toBe('')
  })

  it('returns formatted date string for valid ISO', () => {
    const result = formatTimestamp('2026-03-15T14:30:00Z')
    expect(result).not.toBe('')
    // Should contain month and year at minimum
    expect(result).toMatch(/2026/)
  })
})

describe('isOverdue', () => {
  it('returns false for null', () => {
    expect(isOverdue(null)).toBe(false)
  })

  it('returns false for undefined', () => {
    expect(isOverdue(undefined)).toBe(false)
  })

  it('returns true for past date', () => {
    const past = new Date()
    past.setDate(past.getDate() - 5)
    expect(isOverdue(past.toISOString())).toBe(true)
  })

  it('returns false for future date', () => {
    const future = new Date()
    future.setDate(future.getDate() + 5)
    expect(isOverdue(future.toISOString())).toBe(false)
  })
})
