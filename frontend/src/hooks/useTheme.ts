import { useEffect, useSyncExternalStore } from 'react'

type Theme = 'light' | 'dark' | 'system'

const STORAGE_KEY = 'reli-theme'

function prefersColorSchemeDark(): boolean {
  return typeof window !== 'undefined' && typeof window.matchMedia === 'function'
    ? window.matchMedia('(prefers-color-scheme: dark)').matches
    : false
}

function getStoredTheme(): Theme {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored === 'light' || stored === 'dark' || stored === 'system') return stored
  } catch { /* SSR / test env */ }
  return 'dark'
}

function resolveTheme(theme: Theme): 'light' | 'dark' {
  if (theme !== 'system') return theme
  return prefersColorSchemeDark() ? 'dark' : 'light'
}

function applyTheme(theme: Theme) {
  if (typeof document === 'undefined') return
  const resolved = resolveTheme(theme)
  document.documentElement.classList.toggle('dark', resolved === 'dark')
  document.documentElement.style.colorScheme = resolved
}

let currentTheme: Theme = getStoredTheme()
const listeners = new Set<() => void>()

function notify() {
  listeners.forEach(l => l())
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => { listeners.delete(listener) }
}

function getSnapshot(): Theme {
  return currentTheme
}

export function setTheme(theme: Theme) {
  currentTheme = theme
  try { localStorage.setItem(STORAGE_KEY, theme) } catch { /* test env */ }
  applyTheme(theme)
  notify()
}

// Apply on load
applyTheme(currentTheme)

// Listen for system preference changes
if (typeof window !== 'undefined' && typeof window.matchMedia === 'function') {
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
    if (currentTheme === 'system') {
      applyTheme('system')
    }
  })
}

export function useTheme() {
  const theme = useSyncExternalStore(subscribe, getSnapshot)

  useEffect(() => {
    applyTheme(theme)
  }, [theme])

  return { theme, setTheme }
}
