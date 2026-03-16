import { useEffect, useSyncExternalStore } from 'react'
import { apiFetch } from '../api'

type Theme = 'light' | 'dark' | 'system'

const STORAGE_KEY = 'reli-theme'

function isValidTheme(v: unknown): v is Theme {
  return v === 'light' || v === 'dark' || v === 'system'
}

function prefersColorSchemeDark(): boolean {
  return typeof window !== 'undefined' && typeof window.matchMedia === 'function'
    ? window.matchMedia('(prefers-color-scheme: dark)').matches
    : false
}

function getStoredTheme(): Theme {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (isValidTheme(stored)) return stored
  } catch { /* SSR / test env */ }
  return 'system'
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

function persistToServer(theme: Theme) {
  apiFetch('/api/settings/user', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ theme }),
  }).catch(() => { /* best-effort */ })
}

export function setTheme(theme: Theme) {
  currentTheme = theme
  try { localStorage.setItem(STORAGE_KEY, theme) } catch { /* test env */ }
  applyTheme(theme)
  notify()
  persistToServer(theme)
}

/**
 * Apply theme from server-stored user settings.
 * Called after fetching user settings to sync cross-device preference.
 */
export function applyServerTheme(serverTheme: string | undefined | null) {
  if (!serverTheme || !isValidTheme(serverTheme)) return
  // Only apply if different from current local theme
  if (serverTheme === currentTheme) return
  currentTheme = serverTheme
  try { localStorage.setItem(STORAGE_KEY, serverTheme) } catch { /* test env */ }
  applyTheme(serverTheme)
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
