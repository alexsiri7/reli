import { describe, it, expect, beforeEach, vi } from 'vitest'

const STORAGE_KEY = 'reli-theme'

describe('useTheme – getStoredTheme default', () => {
  beforeEach(() => {
    localStorage.clear()
    document.documentElement.classList.remove('dark')
    document.documentElement.style.colorScheme = ''
    vi.resetModules()
  })

  it('defaults to dark when no theme is stored', async () => {
    await import('../hooks/useTheme')
    expect(document.documentElement.classList.contains('dark')).toBe(true)
    expect(document.documentElement.style.colorScheme).toBe('dark')
  })

  it('honours a stored light theme', async () => {
    localStorage.setItem(STORAGE_KEY, 'light')
    await import('../hooks/useTheme')
    expect(document.documentElement.classList.contains('dark')).toBe(false)
    expect(document.documentElement.style.colorScheme).toBe('light')
  })

  it('honours a stored dark theme', async () => {
    localStorage.setItem(STORAGE_KEY, 'dark')
    await import('../hooks/useTheme')
    expect(document.documentElement.classList.contains('dark')).toBe(true)
  })

  it('ignores invalid stored values and falls back to dark', async () => {
    localStorage.setItem(STORAGE_KEY, 'invalid-value')
    await import('../hooks/useTheme')
    expect(document.documentElement.classList.contains('dark')).toBe(true)
  })
})

describe('setTheme', () => {
  beforeEach(() => {
    localStorage.clear()
    document.documentElement.classList.remove('dark')
    document.documentElement.style.colorScheme = ''
    vi.resetModules()
  })

  it('switches to light and persists to localStorage', async () => {
    const { setTheme } = await import('../hooks/useTheme')
    setTheme('light')
    expect(document.documentElement.classList.contains('dark')).toBe(false)
    expect(localStorage.getItem(STORAGE_KEY)).toBe('light')
  })

  it('switches to dark and persists to localStorage', async () => {
    const { setTheme } = await import('../hooks/useTheme')
    setTheme('dark')
    expect(document.documentElement.classList.contains('dark')).toBe(true)
    expect(localStorage.getItem(STORAGE_KEY)).toBe('dark')
  })
})
