import { useState, useEffect, useRef, useCallback, useMemo, type PointerEvent as ReactPointerEvent } from 'react'
import { useShallow } from 'zustand/react/shallow'
import { useStore } from '../store'
import type { Thing, SweepFinding } from '../store'
import { typeIcon } from '../utils'
import { CalendarSection } from './CalendarSection'
import { ThingCard } from './ThingCard'
import { GmailPanel } from './GmailPanel'

const FINDING_TYPE_ICONS: Record<string, string> = {
  approaching_date: '\u23F0',
  stale: '\u{1F4A4}',
  orphan: '\u{1F50D}',
  inconsistency: '\u26A0\uFE0F',
  open_question: '\u2753',
  connection: '\u{1F517}',
}

function FindingCard({ finding, onDismiss }: { finding: SweepFinding; onDismiss: (id: string) => void }) {
  const icon = FINDING_TYPE_ICONS[finding.finding_type] ?? '\u{1F4CB}'
  return (
    <div
      className="group px-4 py-2 hover:bg-gray-100 dark:hover:bg-gray-900 transition-colors cursor-pointer"
      onClick={() => finding.thing_id && useStore.getState().openThingDetail(finding.thing_id)}
      role={finding.thing_id ? 'button' : undefined}
    >
      <div className="flex items-start gap-2">
        <span className="text-sm mt-0.5 shrink-0">{icon}</span>
        <div className="flex-1 min-w-0">
          <p className="text-sm text-gray-700 dark:text-gray-300 leading-snug">{finding.message}</p>
          {finding.thing && (
            <p className="text-xs text-gray-400 dark:text-gray-500 mt-0.5 truncate">
              {typeIcon(finding.thing.type_hint)} {finding.thing.title}
            </p>
          )}
        </div>
        <button
          onClick={() => onDismiss(finding.id)}
          className="shrink-0 opacity-0 group-hover:opacity-100 p-0.5 text-gray-400 dark:text-gray-500 hover:text-gray-600 dark:hover:text-gray-300 transition-opacity"
          aria-label="Dismiss"
          title="Dismiss"
        >
          <svg xmlns="http://www.w3.org/2000/svg" className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>
    </div>
  )
}

const SIDEBAR_MIN_WIDTH = 200
const SIDEBAR_MAX_WIDTH = 500
const SIDEBAR_DEFAULT_WIDTH = 288 // w-72
const SIDEBAR_WIDTH_KEY = 'reli-sidebar-width'

function loadSidebarWidth(): number {
  try {
    const stored = localStorage.getItem(SIDEBAR_WIDTH_KEY)
    if (stored) {
      const val = Number(stored)
      if (val >= SIDEBAR_MIN_WIDTH && val <= SIDEBAR_MAX_WIDTH) return val
    }
  } catch { /* ignore */ }
  return SIDEBAR_DEFAULT_WIDTH
}

export function Sidebar() {
  const { things, thingTypes, briefing, findings, proactiveSurfaces, loading, searchResults, searchLoading, searchThings, clearSearch, dismissFinding } = useStore(useShallow(s => ({ things: s.things, thingTypes: s.thingTypes, briefing: s.briefing, findings: s.findings, proactiveSurfaces: s.proactiveSurfaces, loading: s.loading, searchResults: s.searchResults, searchLoading: s.searchLoading, searchThings: s.searchThings, clearSearch: s.clearSearch, dismissFinding: s.dismissFinding })))
  const [searchQuery, setSearchQuery] = useState('')
  const debounceRef = useRef<ReturnType<typeof setTimeout>>(null)

  // --- Resizable sidebar state (desktop only) ---
  const [sidebarWidth, setSidebarWidth] = useState(loadSidebarWidth)
  const isDraggingRef = useRef(false)

  const handleDragStart = useCallback((e: ReactPointerEvent<HTMLDivElement>) => {
    e.preventDefault()
    isDraggingRef.current = true
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'

    const onPointerMove = (ev: globalThis.PointerEvent) => {
      if (!isDraggingRef.current) return
      const newWidth = Math.min(SIDEBAR_MAX_WIDTH, Math.max(SIDEBAR_MIN_WIDTH, ev.clientX))
      setSidebarWidth(newWidth)
    }
    const onPointerUp = () => {
      isDraggingRef.current = false
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
      document.removeEventListener('pointermove', onPointerMove)
      document.removeEventListener('pointerup', onPointerUp)
      // Persist on release
      setSidebarWidth(w => {
        try { localStorage.setItem(SIDEBAR_WIDTH_KEY, String(w)) } catch { /* ignore */ }
        return w
      })
    }
    document.addEventListener('pointermove', onPointerMove)
    document.addEventListener('pointerup', onPointerUp)
  }, [])

  const isSearching = searchQuery.trim().length > 0

  const handleSearchChange = useCallback((value: string) => {
    setSearchQuery(value)
    if (debounceRef.current) clearTimeout(debounceRef.current)
    if (!value.trim()) {
      clearSearch()
      return
    }
    debounceRef.current = setTimeout(() => {
      searchThings(value)
    }, 250)
  }, [searchThings, clearSearch])

  const [isOpen, setIsOpen] = useState(() =>
    typeof window !== 'undefined' ? window.innerWidth >= 768 : true
  )

  useEffect(() => {
    const mql = window.matchMedia('(min-width: 768px)')
    const handler = (e: MediaQueryListEvent) => setIsOpen(e.matches)
    mql.addEventListener('change', handler)
    return () => mql.removeEventListener('change', handler)
  }, [])

  const upcoming = things
    .filter(t => t.checkin_date != null)
    .sort((a, b) => {
      const da = new Date(a.checkin_date!).getTime()
      const db = new Date(b.checkin_date!).getTime()
      return da - db
    })

  const active = things.filter(t => t.checkin_date == null)

  // Recently discussed: things referenced in the last 7 days, sorted by most recent
  const [nowMs, setNowMs] = useState(() => Date.now())
  useEffect(() => {
    // Refresh timestamp every minute to keep recency filter current
    const interval = setInterval(() => setNowMs(Date.now()), 60_000)
    return () => clearInterval(interval)
  }, [])
  const RECENT_WINDOW_MS = 7 * 24 * 60 * 60 * 1000
  const recentlyDiscussed = useMemo(() => {
    return things
      .filter(t => t.last_referenced != null && (nowMs - new Date(t.last_referenced).getTime()) < RECENT_WINDOW_MS)
      .sort((a, b) => new Date(b.last_referenced!).getTime() - new Date(a.last_referenced!).getTime())
  }, [things, nowMs, RECENT_WINDOW_MS])

  // Group active things by type, excluding children of projects (shown under parent)
  const activeGroups = useMemo(() => {
    const TYPE_ORDER = ['project', 'goal', 'task', 'note', 'idea', 'journal'] as const
    const FALLBACK_LABELS: Record<string, string> = {
      project: 'Projects',
      goal: 'Goals',
      task: 'Tasks',
      note: 'Notes',
      idea: 'Ideas',
      journal: 'Journal',
    }
    // Build label map from DB types (pluralise by appending 's')
    const typeLabels: Record<string, string> = { ...FALLBACK_LABELS }
    for (const tt of thingTypes) {
      if (!typeLabels[tt.name]) {
        typeLabels[tt.name] = tt.name.charAt(0).toUpperCase() + tt.name.slice(1) + 's'
      }
    }
    const projectIds = new Set(active.filter(t => t.type_hint === 'project').map(t => t.id))
    // Don't show children of projects as standalone items
    const standalone = active.filter(t => !t.parent_id || !projectIds.has(t.parent_id))
    const groups: { type: string; label: string; icon: string; items: Thing[] }[] = []
    const byType = new Map<string, Thing[]>()
    for (const t of standalone) {
      const key = t.type_hint ?? 'other'
      if (!byType.has(key)) byType.set(key, [])
      byType.get(key)!.push(t)
    }
    // Ordered types first, then remaining
    for (const type of TYPE_ORDER) {
      const items = byType.get(type)
      if (items && items.length > 0) {
        groups.push({ type, label: typeLabels[type] ?? type, icon: typeIcon(type, thingTypes), items })
        byType.delete(type)
      }
    }
    // Remaining types (including custom user types)
    for (const [type, items] of byType) {
      if (items.length > 0) {
        groups.push({ type, label: typeLabels[type] ?? type.charAt(0).toUpperCase() + type.slice(1), icon: typeIcon(type, thingTypes), items })
      }
    }
    return groups
  }, [active, thingTypes])

  return (
    <>
      {/* Toggle button — visible when sidebar is closed */}
      {!isOpen && (
        <button
          onClick={() => setIsOpen(true)}
          aria-label="Open sidebar"
          className="fixed top-3 left-3 z-50 p-2 rounded-lg bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 shadow-md text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors md:static md:m-0 md:border-0 md:shadow-none md:rounded-none md:bg-gray-50 md:dark:bg-gray-950 md:border-r md:border-gray-200 md:dark:border-gray-800 md:px-2 md:py-3"
        >
          <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M4 6h16M4 12h16M4 18h16" />
          </svg>
        </button>
      )}

      {/* Backdrop — mobile only, when sidebar is open */}
      {isOpen && (
        <div
          onClick={() => { if (window.innerWidth < 768) setIsOpen(false) }}
          className="fixed inset-0 z-40 bg-black/30 transition-opacity md:hidden"
        />
      )}

      {/* Sidebar panel */}
      <aside
        style={{ width: window.innerWidth >= 768 ? sidebarWidth : undefined }}
        className={`
          fixed inset-y-0 left-0 z-50 w-72 md:w-auto flex flex-col border-r border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-gray-950 overflow-y-auto
          transform transition-transform duration-200 ease-in-out
          ${isOpen ? 'translate-x-0' : '-translate-x-full'}
          md:static md:z-auto md:shrink-0 md:relative
          ${isOpen ? '' : 'md:-translate-x-full md:hidden'}
        `}
      >
        {/* Header */}
        <div className="px-4 py-3 border-b border-gray-200 dark:border-gray-800 flex items-center justify-between">
          <div>
            <div className="flex items-center gap-2">
              <img src="/logo.svg" alt="Reli" className="h-7 w-7 rounded-md" />
              <h1 className="text-lg font-bold text-gray-900 dark:text-white tracking-tight">Reli</h1>
            </div>
            <p className="text-xs text-gray-400 dark:text-gray-500 mt-0.5">
              {new Date().toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric' })}
            </p>
          </div>
          <button
            onClick={() => setIsOpen(false)}
            aria-label="Close sidebar"
            className="p-1.5 rounded-lg text-gray-400 dark:text-gray-500 hover:bg-gray-200 dark:hover:bg-gray-800 hover:text-gray-600 dark:hover:text-gray-300 transition-colors"
          >
            <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
            </svg>
          </button>
        </div>

        {/* Search bar */}
        <div className="px-3 py-2 border-b border-gray-200 dark:border-gray-800">
          <div className="relative">
            <svg xmlns="http://www.w3.org/2000/svg" className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-gray-400 dark:text-gray-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
            <input
              type="text"
              placeholder="Search everything…"
              value={searchQuery}
              onChange={e => handleSearchChange(e.target.value)}
              className="w-full pl-8 pr-7 py-1.5 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 text-gray-900 dark:text-gray-100 placeholder-gray-400 dark:placeholder-gray-500 focus:outline-none focus:ring-1 focus:ring-indigo-400 dark:focus:ring-indigo-500 focus:border-indigo-400 dark:focus:border-indigo-500"
            />
            {searchQuery && (
              <button
                onClick={() => handleSearchChange('')}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 dark:text-gray-500 hover:text-gray-600 dark:hover:text-gray-300"
                aria-label="Clear search"
              >
                <svg xmlns="http://www.w3.org/2000/svg" className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            )}
          </div>
        </div>

        {/* Search results */}
        {isSearching ? (
          <section className="py-2 flex-1">
            <h2 className="px-4 pb-1 text-xs font-semibold text-gray-400 dark:text-gray-500 uppercase tracking-widest">
              Search Results {!searchLoading && `(${searchResults.length})`}
            </h2>
            {searchLoading ? (
              <div className="px-4 py-3 space-y-2 animate-pulse">
                <div className="h-4 bg-gray-200 dark:bg-gray-700 rounded w-3/4"></div>
                <div className="h-4 bg-gray-200 dark:bg-gray-700 rounded w-1/2"></div>
              </div>
            ) : searchResults.length === 0 ? (
              <div className="px-4 py-4 text-sm text-gray-400 dark:text-gray-500 text-center">
                No results found
              </div>
            ) : (
              searchResults.map(t => <ThingCard key={t.id} thing={t} />)
            )}
          </section>
        ) : (
          <>
            {loading && things.length === 0 && (
              <div className="px-4 py-3 space-y-2 animate-pulse">
                <div className="h-4 bg-gray-200 dark:bg-gray-700 rounded w-3/4"></div>
                <div className="h-4 bg-gray-200 dark:bg-gray-700 rounded w-1/2"></div>
                <div className="h-4 bg-gray-200 dark:bg-gray-700 rounded w-5/6"></div>
              </div>
            )}

            {/* Google Calendar */}
            <CalendarSection />

            {/* Daily Briefing — sweep findings + checkin-due things */}
            {(findings.length > 0 || briefing.length > 0) && (
              <section className="py-2 border-b border-gray-100 dark:border-gray-800">
                <h2 className="px-4 pb-1 text-xs font-semibold text-gray-400 dark:text-gray-500 uppercase tracking-widest">
                  Daily Briefing
                </h2>

                {/* Sweep findings */}
                {findings.map(f => (
                  <FindingCard key={f.id} finding={f} onDismiss={dismissFinding} />
                ))}

                {/* Checkin-due things */}
                {briefing.map(t => <ThingCard key={t.id} thing={t} />)}
              </section>
            )}

            {/* Proactive Surfaces */}
            {proactiveSurfaces && proactiveSurfaces.length > 0 && (
              <section className="py-2 border-b border-gray-100 dark:border-gray-800">
                <h2 className="px-4 pb-1 text-xs font-semibold text-gray-400 dark:text-gray-500 uppercase tracking-widest">
                  ✨ Coming Up
                </h2>
                {proactiveSurfaces.map(s => (
                  <div key={`${s.thing.id}-${s.date_key}`} className="px-3 py-1">
                    <div
                      className="flex items-start gap-2 py-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors px-1 cursor-pointer"
                      onClick={() => useStore.getState().openThingDetail(s.thing.id)}
                      role="button"
                    >
                      <span className="text-lg leading-none mt-0.5 select-none" title={s.thing.type_hint ?? 'thing'}>
                        {typeIcon(s.thing.type_hint, thingTypes)}
                      </span>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium text-gray-900 dark:text-gray-100 truncate leading-snug">
                          {s.thing.title}
                        </p>
                        <p className={`text-xs mt-0.5 ${s.days_away === 0 ? 'text-amber-500 font-semibold' : 'text-gray-400 dark:text-gray-500'}`}>
                          {s.reason}
                        </p>
                      </div>
                    </div>
                  </div>
                ))}
              </section>
            )}

            {/* Recently Discussed */}
            {recentlyDiscussed.length > 0 && (
              <section className="py-2 border-b border-gray-100 dark:border-gray-800">
                <h2 className="px-4 pb-1 text-xs font-semibold text-gray-400 dark:text-gray-500 uppercase tracking-widest">
                  Recently Discussed
                </h2>
                {recentlyDiscussed.map(t => {
                  const ageMs = nowMs - new Date(t.last_referenced!).getTime()
                  const opacity = Math.max(0.4, 1 - ageMs / RECENT_WINDOW_MS)
                  return (
                    <div key={t.id} style={{ opacity }}>
                      <ThingCard thing={t} />
                    </div>
                  )
                })}
              </section>
            )}

        {/* Active Things grouped by type */}
        {activeGroups.map(group => (
          <section key={group.type} className="py-2 border-t border-gray-100 dark:border-gray-800">
            <h2 className="px-4 pb-1 text-xs font-semibold text-gray-400 dark:text-gray-500 uppercase tracking-widest flex items-center gap-1.5">
              <span>{group.icon}</span>
              <span>{group.label}</span>
              <span className="ml-auto text-[10px] font-normal tabular-nums">{group.items.length}</span>
            </h2>
            {group.items.map(t => <ThingCard key={t.id} thing={t} />)}
          </section>
        ))}

            {/* Upcoming Check-ins */}
            {upcoming.length > 0 && (
              <section className="py-2">
                <h2 className="px-4 pb-1 text-xs font-semibold text-gray-400 dark:text-gray-500 uppercase tracking-widest">
                  Upcoming Check-ins
                </h2>
                {upcoming.map(t => <ThingCard key={t.id} thing={t} />)}
              </section>
            )}

            {/* Gmail */}
            <GmailPanel />

            {!loading && things.length === 0 && (
              <div className="px-4 py-6 text-sm text-gray-400 dark:text-gray-500 text-center">
                Start by typing in the chat…
              </div>
            )}
          </>
        )}
        {/* Drag handle — desktop only */}
        <div
          onPointerDown={handleDragStart}
          className="hidden md:flex absolute top-0 right-0 w-2 h-full cursor-col-resize group/handle z-10 items-center justify-center"
        >
          <div className="w-1 h-full bg-gray-300 dark:bg-gray-600 group-hover/handle:bg-indigo-400 dark:group-hover/handle:bg-indigo-500 transition-colors" />
          {/* Grip indicator — three dots centered vertically */}
          <div className="absolute flex flex-col gap-1 pointer-events-none">
            <div className="w-1 h-1 rounded-full bg-gray-400 dark:bg-gray-500 group-hover/handle:bg-indigo-300 dark:group-hover/handle:bg-indigo-400 transition-colors" />
            <div className="w-1 h-1 rounded-full bg-gray-400 dark:bg-gray-500 group-hover/handle:bg-indigo-300 dark:group-hover/handle:bg-indigo-400 transition-colors" />
            <div className="w-1 h-1 rounded-full bg-gray-400 dark:bg-gray-500 group-hover/handle:bg-indigo-300 dark:group-hover/handle:bg-indigo-400 transition-colors" />
          </div>
        </div>
      </aside>
    </>
  )
}
