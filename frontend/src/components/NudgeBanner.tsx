/**
 * NudgeBanner — proactive in-app nudge banners at the top of the chat panel.
 *
 * Shows up to 3 nudges sourced from proactive surfaces (today or tomorrow).
 * Each nudge has:
 *   - Gradient background with bell icon
 *   - Primary "View" action to open the related Thing
 *   - Dismiss button (stores dismissed IDs in localStorage)
 *   - "Stop these" button (sends negative preference signal to backend)
 *
 * Daily limit: max 3 nudges shown.
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import { apiFetch } from '../api'
import { useStore, type ProactiveSurface } from '../store'
import { typeIcon } from '../utils'

const BASE = '/api'
const DISMISSED_KEY = 'reli-dismissed-nudges'
const STOPPED_KEY = 'reli-stopped-nudge-keys'
const MAX_DAILY_NUDGES = 3

function loadDismissed(): Set<string> {
  try {
    const raw = localStorage.getItem(DISMISSED_KEY)
    return raw ? new Set(JSON.parse(raw)) : new Set()
  } catch {
    return new Set()
  }
}

function saveDismissed(dismissed: Set<string>) {
  try {
    const arr = Array.from(dismissed)
    // Keep last 200 entries to avoid unbounded growth
    localStorage.setItem(DISMISSED_KEY, JSON.stringify(arr.slice(-200)))
  } catch {
    // storage full or blocked — ignore
  }
}

function loadStopped(): Set<string> {
  try {
    const raw = localStorage.getItem(STOPPED_KEY)
    return raw ? new Set(JSON.parse(raw)) : new Set()
  } catch {
    return new Set()
  }
}

function saveStopped(stopped: Set<string>) {
  try {
    localStorage.setItem(STOPPED_KEY, JSON.stringify(Array.from(stopped)))
  } catch {}
}

function nudgeId(s: ProactiveSurface): string {
  return `${s.thing.id}:${s.date_key}`
}


interface NudgeBannerItemProps {
  surface: ProactiveSurface
  onDismiss: (s: ProactiveSurface) => void
  onStop: (s: ProactiveSurface) => void
  onView: (s: ProactiveSurface) => void
}

function NudgeBannerItem({ surface, onDismiss, onStop, onView }: NudgeBannerItemProps) {
  return (
    <div
      className="flex items-start gap-3 px-4 py-3 bg-gradient-to-r from-indigo-50 to-purple-50 dark:from-indigo-950/40 dark:to-purple-950/40 border-b border-indigo-200 dark:border-indigo-800"
      role="alert"
      aria-label={`Nudge: ${surface.thing.title}`}
    >
      {/* Bell icon */}
      <div className="shrink-0 w-8 h-8 rounded-full bg-indigo-100 dark:bg-indigo-900/50 flex items-center justify-center mt-0.5">
        <svg
          className="w-4 h-4 text-indigo-600 dark:text-indigo-400"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth={2}
          aria-hidden="true"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M14.857 17.082a23.848 23.848 0 0 0 5.454-1.31A8.967 8.967 0 0 1 18 9.75V9A6 6 0 0 0 6 9v.75a8.967 8.967 0 0 1-2.312 6.022c1.733.64 3.56 1.085 5.455 1.31m5.714 0a24.255 24.255 0 0 1-5.714 0m5.714 0a3 3 0 1 1-5.714 0"
          />
        </svg>
      </div>

      {/* Content */}
      <div className="flex-1 min-w-0">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <p className="text-xs font-semibold text-indigo-700 dark:text-indigo-300 uppercase tracking-wide leading-none mb-0.5">
              Reminder
            </p>
            <p className="text-sm font-medium text-gray-800 dark:text-gray-100 truncate">
              <span className="mr-1">{typeIcon(surface.thing.type_hint)}</span>
              {surface.thing.title}
            </p>
            <p className="text-xs text-indigo-600 dark:text-indigo-400 mt-0.5">
              {surface.reason}
            </p>
          </div>

          {/* Dismiss × button */}
          <button
            onClick={() => onDismiss(surface)}
            className="shrink-0 p-1 text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 transition-colors rounded"
            aria-label="Dismiss nudge"
          >
            <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18 18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Action row */}
        <div className="flex items-center gap-3 mt-2">
          <button
            onClick={() => onView(surface)}
            className="text-xs font-medium text-indigo-700 dark:text-indigo-300 hover:text-indigo-900 dark:hover:text-indigo-100 transition-colors"
          >
            View →
          </button>
          <span className="text-gray-300 dark:text-gray-600">·</span>
          <button
            onClick={() => onStop(surface)}
            className="text-xs text-gray-400 dark:text-gray-500 hover:text-gray-600 dark:hover:text-gray-300 transition-colors"
          >
            Stop these
          </button>
        </div>
      </div>
    </div>
  )
}

export function NudgeBanner() {
  const proactiveSurfaces = useStore(s => s.proactiveSurfaces)
  const openThingDetail = useStore(s => s.openThingDetail)

  const [dismissed, setDismissed] = useState<Set<string>>(() => loadDismissed())
  const [stopped, setStopped] = useState<Set<string>>(() => loadStopped())

  // Sync stopped keys from backend on mount (best-effort)
  useEffect(() => {
    apiFetch(`${BASE}/nudges/preferences`)
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        if (!data) return
        const backendStopped = new Set<string>(data.stopped_nudge_keys ?? [])
        const backendDismissed = new Set<string>(data.dismissed_nudges ?? [])
        setStopped(prev => {
          const merged = new Set([...prev, ...backendStopped])
          saveStopped(merged)
          return merged
        })
        setDismissed(prev => {
          const merged = new Set([...prev, ...backendDismissed])
          saveDismissed(merged)
          return merged
        })
      })
      .catch(() => {}) // best-effort
  }, [])

  const visible = useMemo(() => {
    return proactiveSurfaces
      .filter(s => s.days_away <= 1)
      .filter(s => !dismissed.has(nudgeId(s)))
      .filter(s => !stopped.has(s.date_key))
      .slice(0, MAX_DAILY_NUDGES)
  }, [proactiveSurfaces, dismissed, stopped])

  const handleDismiss = useCallback((surface: ProactiveSurface) => {
    const id = nudgeId(surface)
    setDismissed(prev => {
      const next = new Set(prev)
      next.add(id)
      saveDismissed(next)
      return next
    })
    // Persist to backend best-effort
    apiFetch(`${BASE}/nudges/dismiss`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ thing_id: surface.thing.id, date_key: surface.date_key }),
    }).catch(() => {})
  }, [])

  const handleStop = useCallback((surface: ProactiveSurface) => {
    const { date_key } = surface
    setStopped(prev => {
      const next = new Set(prev)
      next.add(date_key)
      saveStopped(next)
      return next
    })
    // Send negative preference signal to backend
    apiFetch(`${BASE}/nudges/stop`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ date_key }),
    }).catch(() => {})
  }, [])

  const handleView = useCallback((surface: ProactiveSurface) => {
    openThingDetail(surface.thing.id)
    handleDismiss(surface)
  }, [openThingDetail, handleDismiss])

  if (visible.length === 0) return null

  return (
    <div className="shrink-0">
      {visible.map(surface => (
        <NudgeBannerItem
          key={nudgeId(surface)}
          surface={surface}
          onDismiss={handleDismiss}
          onStop={handleStop}
          onView={handleView}
        />
      ))}
    </div>
  )
}
