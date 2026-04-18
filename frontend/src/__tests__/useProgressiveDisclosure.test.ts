import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook } from '@testing-library/react'
import { useProgressiveDisclosure } from '../hooks/useProgressiveDisclosure'

type Thing = {
  id: string
  title: string
  type_hint: string | null
  checkin_date: string | null
  priority: number
  active: boolean
  surface: boolean
  data: Record<string, unknown> | null
  created_at: string
  updated_at: string
  last_referenced: string | null
  open_questions: string[] | null
  children_count: number | null
  completed_count: number | null
  parent_ids: string[] | null
}

let mockState: { things: Thing[] } = { things: [] }

vi.mock('zustand/react/shallow', () => ({
  useShallow: <T,>(fn: (state: unknown) => T) => fn,
}))

vi.mock('../store', () => ({
  useStore: (selector: (s: typeof mockState) => unknown) => selector(mockState),
}))

const makeThing = (id: string): Thing => ({
  id,
  title: `Thing ${id}`,
  type_hint: 'task',
  checkin_date: null,
  priority: 2,
  active: true,
  surface: true,
  data: null,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  last_referenced: null,
  open_questions: null,
  children_count: null,
  completed_count: null,
  parent_ids: null,
})

const makeThings = (count: number): Thing[] =>
  Array.from({ length: count }, (_, i) => makeThing(`t${i}`))

beforeEach(() => {
  mockState = { things: [] }
})

describe('useProgressiveDisclosure', () => {
  it('returns showOnboarding true and all others false at 0 things', () => {
    mockState.things = []
    const { result } = renderHook(() => useProgressiveDisclosure())
    expect(result.current.showOnboarding).toBe(true)
    expect(result.current.showBriefing).toBe(false)
    expect(result.current.showConnectionDiscovery).toBe(false)
    expect(result.current.showFocusBoard).toBe(false)
    expect(result.current.showCommandPaletteHint).toBe(false)
    expect(result.current.showGraphView).toBe(false)
  })

  it('returns showOnboarding false and showBriefing false at 4 things', () => {
    mockState.things = makeThings(4)
    const { result } = renderHook(() => useProgressiveDisclosure())
    expect(result.current.showOnboarding).toBe(false)
    expect(result.current.showBriefing).toBe(false)
  })

  it('returns showBriefing true at 5 things', () => {
    mockState.things = makeThings(5)
    const { result } = renderHook(() => useProgressiveDisclosure())
    expect(result.current.showBriefing).toBe(true)
    expect(result.current.showConnectionDiscovery).toBe(false)
  })

  it('returns showConnectionDiscovery true at 10 things', () => {
    mockState.things = makeThings(10)
    const { result } = renderHook(() => useProgressiveDisclosure())
    expect(result.current.showConnectionDiscovery).toBe(true)
    expect(result.current.showFocusBoard).toBe(false)
  })

  it('returns showFocusBoard true at 20 things', () => {
    mockState.things = makeThings(20)
    const { result } = renderHook(() => useProgressiveDisclosure())
    expect(result.current.showFocusBoard).toBe(true)
    expect(result.current.showCommandPaletteHint).toBe(false)
  })

  it('returns showCommandPaletteHint true at 50 things', () => {
    mockState.things = makeThings(50)
    const { result } = renderHook(() => useProgressiveDisclosure())
    expect(result.current.showCommandPaletteHint).toBe(true)
    expect(result.current.showGraphView).toBe(false)
  })

  it('returns showGraphView true at 100 things', () => {
    mockState.things = makeThings(100)
    const { result } = renderHook(() => useProgressiveDisclosure())
    expect(result.current.showGraphView).toBe(true)
  })
})
