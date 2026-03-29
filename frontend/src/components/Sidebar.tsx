import { useState, useEffect, useRef, useCallback, useMemo, type PointerEvent as ReactPointerEvent } from 'react'
import { useShallow } from 'zustand/react/shallow'
import { useStore } from '../store'
import type { Thing, SweepFinding, FocusRecommendation, MorningBriefing } from '../store'
import { typeIcon } from '../utils'
import { CalendarSection } from './CalendarSection'
import { ThingCard } from './ThingCard'
import { GmailPanel } from './GmailPanel'
import { MergeSuggestions } from './MergeSuggestions'
import { ConnectionSuggestions } from './ConnectionSuggestions'
import { useProgressiveDisclosure } from '../hooks/useProgressiveDisclosure'

const FINDING_TYPE_ICONS: Record<string, string> = {
  approaching_date: '\u23F0',
  stale: '\u{1F4A4}',
  neglected: '\u{1F6A8}',
  overdue_checkin: '\u{1F4C5}',
  orphan: '\u{1F50D}',
  inconsistency: '\u26A0\uFE0F',
  open_question: '\u2753',
  connection: '\u{1F517}',
}

function FindingCard({ finding, onDismiss, onSnooze, onAct }: {
  finding: SweepFinding
  onDismiss: (id: string) => void
  onSnooze: (id: string) => void
  onAct: (finding: SweepFinding) => void
}) {
  const icon = FINDING_TYPE_ICONS[finding.finding_type] ?? '\u{1F4CB}'
  return (
    <div
      className="group px-4 py-2 hover:bg-gray-100 dark:hover:bg-gray-900 transition-colors"
    >
      <div className="flex items-start gap-2">
        <span className="text-sm mt-0.5 shrink-0">{icon}</span>
        <div className="flex-1 min-w-0">
          <p className="text-sm text-gray-700 dark:text-gray-300 leading-snug">{finding.message}</p>
          {finding.thing && (
            <p className="text-xs text-gray-400 dark:text-gray-400 mt-0.5 truncate">
              {typeIcon(finding.thing.type_hint)} {finding.thing.title}
            </p>
          )}
          {/* Action buttons */}
          <div className="flex items-center gap-2 mt-1.5 opacity-0 group-hover:opacity-100 transition-opacity">
            {finding.thing_id && (
              <button
                onClick={() => onAct(finding)}
                className="text-xs text-indigo-500 dark:text-indigo-400 hover:text-indigo-700 dark:hover:text-indigo-300 font-medium"
                title="Open in detail panel"
              >
                Open
              </button>
            )}
            <button
              onClick={() => onSnooze(finding.id)}
              className="text-xs text-gray-400 dark:text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
              title="Snooze for 1 day"
            >
              Snooze
            </button>
            <button
              onClick={() => onDismiss(finding.id)}
              className="text-xs text-gray-400 dark:text-gray-400 hover:text-red-500 dark:hover:text-red-400"
              title="Dismiss"
            >
              Dismiss
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

function FocusCard({ rec }: { rec: FocusRecommendation }) {
  return (
    <div
      className={`group px-3 py-1 ${rec.is_blocked ? 'opacity-50' : ''}`}
    >
      <div
        className="flex items-start gap-2 py-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors px-1 cursor-pointer"
        onClick={() => useStore.getState().openThingDetail(rec.thing.id)}
        role="button"
      >
        <span className="text-lg leading-none mt-0.5 select-none" title={rec.thing.type_hint ?? 'thing'}>
          {typeIcon(rec.thing.type_hint)}
        </span>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-gray-900 dark:text-gray-100 truncate leading-snug">
            {rec.thing.title}
          </p>
          <p className="text-xs text-gray-400 dark:text-gray-400 mt-0.5 leading-snug">
            {rec.reasons.join(' \u00B7 ')}
          </p>
        </div>
        {rec.is_blocked && (
          <span className="text-[10px] text-red-400 dark:text-red-500 font-medium mt-1 shrink-0">BLOCKED</span>
        )}
      </div>
    </div>
  )
}

function MorningBriefingSection({ briefing }: { briefing: MorningBriefing }) {
  const [expanded, setExpanded] = useState(true)
  const c = briefing.content

  const hasPriorities = c.priorities.length > 0
  const hasOverdue = c.overdue.length > 0
  const hasBlockers = c.blockers.length > 0
  const hasFindings = c.findings.length > 0
  const hasContent = hasPriorities || hasOverdue || hasBlockers || hasFindings

  if (!hasContent) return null

  return (
    <section className="py-2 border-b border-gray-100 dark:border-gray-800">
      <button
        className="w-full flex items-center justify-between px-4 pb-1"
        onClick={() => setExpanded(!expanded)}
      >
        <h2 className="text-xs font-semibold text-gray-400 dark:text-gray-400 uppercase tracking-widest">
          Morning Briefing
        </h2>
        <span className="text-xs text-gray-300 dark:text-gray-500">{expanded ? '\u25B2' : '\u25BC'}</span>
      </button>

      {expanded && (
        <div className="space-y-1">
          {/* Summary */}
          <p className="px-4 text-sm text-gray-600 dark:text-gray-300 leading-snug">
            {c.summary}
          </p>

          {/* Overdue items */}
          {hasOverdue && (
            <div className="px-4 mt-1">
              <p className="text-xs font-medium text-red-500 dark:text-red-400 uppercase tracking-wider mb-0.5">Overdue</p>
              {c.overdue.map(item => (
                <div
                  key={item.thing_id}
                  className="flex items-center gap-2 py-1 cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-800 rounded px-1 -mx-1"
                  onClick={() => useStore.getState().openThingDetail(item.thing_id)}
                  role="button"
                >
                  <span className="text-red-400 text-xs shrink-0">{'\u26A0'}</span>
                  <span className="text-sm text-gray-700 dark:text-gray-200 truncate flex-1">{item.title}</span>
                  <span className="text-xs text-red-400 shrink-0">{item.days_overdue}d</span>
                </div>
              ))}
            </div>
          )}

          {/* Top priorities */}
          {hasPriorities && (
            <div className="px-4 mt-1">
              <p className="text-xs font-medium text-amber-500 dark:text-amber-400 uppercase tracking-wider mb-0.5">Priorities</p>
              {c.priorities.map(item => (
                <div
                  key={item.thing_id}
                  className="flex items-start gap-2 py-1 cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-800 rounded px-1 -mx-1"
                  onClick={() => useStore.getState().openThingDetail(item.thing_id)}
                  role="button"
                >
                  <span className="text-amber-400 text-xs mt-0.5 shrink-0">{'\u2B50'}</span>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-gray-700 dark:text-gray-200 truncate leading-snug">{item.title}</p>
                    <p className="text-xs text-gray-400 dark:text-gray-500 leading-snug">{item.reasons.join(' \u00B7 ')}</p>
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Blockers */}
          {hasBlockers && (
            <div className="px-4 mt-1">
              <p className="text-xs font-medium text-orange-500 dark:text-orange-400 uppercase tracking-wider mb-0.5">Blocked</p>
              {c.blockers.map(item => (
                <div
                  key={item.thing_id}
                  className="flex items-start gap-2 py-1 cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-800 rounded px-1 -mx-1"
                  onClick={() => useStore.getState().openThingDetail(item.thing_id)}
                  role="button"
                >
                  <span className="text-orange-400 text-xs mt-0.5 shrink-0">{'\u{1F6AB}'}</span>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-gray-700 dark:text-gray-200 truncate leading-snug">{item.title}</p>
                    {item.blocked_by.length > 0 && (
                      <p className="text-xs text-gray-400 dark:text-gray-500 leading-snug truncate">
                        Blocked by: {item.blocked_by.join(', ')}
                      </p>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Sweep findings summary */}
          {hasFindings && (
            <div className="px-4 mt-1">
              <p className="text-xs font-medium text-blue-500 dark:text-blue-400 uppercase tracking-wider mb-0.5">Insights</p>
              {c.findings.slice(0, 5).map(f => (
                <div
                  key={f.id}
                  className={`flex items-start gap-2 py-1 ${f.thing_id ? 'cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-800' : ''} rounded px-1 -mx-1`}
                  onClick={() => f.thing_id && useStore.getState().openThingDetail(f.thing_id)}
                  role={f.thing_id ? 'button' : undefined}
                >
                  <span className="text-blue-400 text-xs mt-0.5 shrink-0">{'\u{1F4A1}'}</span>
                  <p className="text-sm text-gray-700 dark:text-gray-200 leading-snug">{f.message}</p>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </section>
  )
}

function confidenceLabel(confidence: number): { label: string; className: string } {
  if (confidence >= 0.7) return { label: 'Strong', className: 'text-emerald-600 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-950' }
  if (confidence >= 0.5) return { label: 'Moderate', className: 'text-blue-600 dark:text-blue-400 bg-blue-50 dark:bg-blue-950' }
  return { label: 'Emerging', className: 'text-amber-600 dark:text-amber-400 bg-amber-50 dark:bg-amber-950' }
}

function PreferenceCard({ thing }: { thing: Thing }) {
  const openThingDetail = useStore(s => s.openThingDetail)
  const confidence: number = typeof thing.data?.confidence === 'number' ? thing.data.confidence : 0
  const evidence: unknown[] = Array.isArray(thing.data?.evidence) ? (thing.data.evidence as unknown[]) : []
  const category: string = typeof thing.data?.category === 'string' ? thing.data.category : ''
  const { label, className } = confidenceLabel(confidence)

  return (
    <div className="px-3 py-1">
      <div
        className="flex items-start gap-2 py-1.5 rounded-lg hover:bg-purple-50 dark:hover:bg-purple-950/30 transition-colors px-2 cursor-pointer border border-transparent hover:border-purple-100 dark:hover:border-purple-900"
        onClick={() => openThingDetail(thing.id)}
        role="button"
      >
        <span className="text-base leading-none mt-0.5 select-none shrink-0">⚙️</span>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-gray-900 dark:text-gray-100 truncate leading-snug">
            {thing.title}
          </p>
          <div className="flex items-center gap-1.5 mt-0.5 flex-wrap">
            <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded-full ${className}`}>
              {label}
            </span>
            {evidence.length > 0 && (
              <span className="text-[10px] text-gray-400 dark:text-gray-500">
                {evidence.length} obs.
              </span>
            )}
            {category && (
              <span className="text-[10px] text-gray-400 dark:text-gray-500 capitalize">
                {category}
              </span>
            )}
          </div>
        </div>
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
  const { currentUser, logout, things, thingTypes, briefing, findings, proactiveSurfaces, focusRecommendations, conflictAlerts, morningBriefing, loading, searchResults, searchLoading, searchThings, clearSearch, dismissFinding, snoozeFinding, actOnFinding, thingFilterQuery, thingFilterTypes, setThingFilterQuery, toggleThingFilterType, clearThingFilters, mainView, setMainView } = useStore(useShallow(s => ({ currentUser: s.currentUser, logout: s.logout, things: s.things, thingTypes: s.thingTypes, briefing: s.briefing, findings: s.findings, proactiveSurfaces: s.proactiveSurfaces, focusRecommendations: s.focusRecommendations, conflictAlerts: s.conflictAlerts, morningBriefing: s.morningBriefing, loading: s.loading, searchResults: s.searchResults, searchLoading: s.searchLoading, searchThings: s.searchThings, clearSearch: s.clearSearch, dismissFinding: s.dismissFinding, snoozeFinding: s.snoozeFinding, actOnFinding: s.actOnFinding, thingFilterQuery: s.thingFilterQuery, thingFilterTypes: s.thingFilterTypes, setThingFilterQuery: s.setThingFilterQuery, toggleThingFilterType: s.toggleThingFilterType, clearThingFilters: s.clearThingFilters, mainView: s.mainView, setMainView: s.setMainView })))
  const disclosure = useProgressiveDisclosure()
  const [searchQuery, setSearchQuery] = useState('')
  const [userMenuOpen, setUserMenuOpen] = useState(false)
  const userMenuRef = useRef<HTMLDivElement>(null)
  const debounceRef = useRef<ReturnType<typeof setTimeout>>(null)

  // Close user menu on click outside
  useEffect(() => {
    if (!userMenuOpen) return
    const handler = (e: MouseEvent) => {
      if (userMenuRef.current && !userMenuRef.current.contains(e.target as Node)) {
        setUserMenuOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [userMenuOpen])

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

  const handleSnooze = useCallback((findingId: string) => {
    const tomorrow = new Date()
    tomorrow.setDate(tomorrow.getDate() + 1)
    tomorrow.setHours(9, 0, 0, 0)
    snoozeFinding(findingId, tomorrow.toISOString())
  }, [snoozeFinding])

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

  const [filterDropdownOpen, setFilterDropdownOpen] = useState(false)
  const filterDropdownRef = useRef<HTMLDivElement>(null)

  // Close filter dropdown on outside click
  useEffect(() => {
    if (!filterDropdownOpen) return
    const handler = (e: MouseEvent) => {
      if (filterDropdownRef.current && !filterDropdownRef.current.contains(e.target as Node)) {
        setFilterDropdownOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [filterDropdownOpen])

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
    const TYPE_ORDER = ['project', 'goal', 'task', 'note', 'idea', 'journal', 'preference'] as const
    const FALLBACK_LABELS: Record<string, string> = {
      project: 'Projects',
      goal: 'Goals',
      task: 'Tasks',
      note: 'Notes',
      idea: 'Ideas',
      journal: 'Journal',
      preference: 'Preferences',
    }
    // Build label map from DB types (pluralise by appending 's')
    const typeLabels: Record<string, string> = { ...FALLBACK_LABELS }
    for (const tt of thingTypes) {
      if (!typeLabels[tt.name]) {
        typeLabels[tt.name] = tt.name.charAt(0).toUpperCase() + tt.name.slice(1) + 's'
      }
    }
    const projectIds = new Set(active.filter(t => t.type_hint === 'project').map(t => t.id))
    // Don't show children of projects or preference Things as standalone items (preferences get their own section)
    let standalone = active.filter(t => (!t.parent_id || !projectIds.has(t.parent_id)) && t.type_hint !== 'preference')

    // Apply client-side filters
    const filterQ = thingFilterQuery.trim().toLowerCase()
    if (filterQ) {
      standalone = standalone.filter(t => t.title.toLowerCase().includes(filterQ))
    }
    if (thingFilterTypes.length > 0) {
      standalone = standalone.filter(t => thingFilterTypes.includes(t.type_hint ?? 'other'))
    }

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
  }, [active, thingTypes, thingFilterQuery, thingFilterTypes])

  // Preference Things — shown in their own dedicated section
  const preferenceThings = useMemo(() => {
    return things.filter(t => t.type_hint === 'preference')
  }, [things])

  // Available types for the filter dropdown (derived from active things)
  const availableTypes = useMemo(() => {
    const TYPE_ORDER = ['project', 'goal', 'task', 'note', 'idea', 'journal', 'preference']
    const FALLBACK_LABELS: Record<string, string> = {
      project: 'Projects', goal: 'Goals', task: 'Tasks',
      note: 'Notes', idea: 'Ideas', journal: 'Journal',
      preference: 'Preferences',
    }
    const typeLabels: Record<string, string> = { ...FALLBACK_LABELS }
    for (const tt of thingTypes) {
      if (!typeLabels[tt.name]) {
        typeLabels[tt.name] = tt.name.charAt(0).toUpperCase() + tt.name.slice(1) + 's'
      }
    }
    const typesInUse = new Set(active.map(t => t.type_hint ?? 'other'))
    const ordered: { type: string; label: string; icon: string }[] = []
    for (const type of TYPE_ORDER) {
      if (typesInUse.has(type)) {
        ordered.push({ type, label: typeLabels[type] ?? type, icon: typeIcon(type, thingTypes) })
        typesInUse.delete(type)
      }
    }
    for (const type of typesInUse) {
      ordered.push({ type, label: typeLabels[type] ?? type.charAt(0).toUpperCase() + type.slice(1), icon: typeIcon(type, thingTypes) })
    }
    return ordered
  }, [active, thingTypes])

  const activeFilterCount = thingFilterTypes.length + (thingFilterQuery.trim() ? 1 : 0)
  const isThingFilterActive = activeFilterCount > 0

  return (
    <>
      {/* Toggle button — visible on desktop when sidebar is closed */}
      {!isOpen && (
        <button
          onClick={() => setIsOpen(true)}
          aria-label="Open sidebar"
          className="hidden md:block md:static md:m-0 md:border-0 md:shadow-none md:rounded-none md:bg-gray-50 md:dark:bg-gray-950 md:border-r md:border-gray-200 md:dark:border-gray-800 md:px-2 md:py-3 p-2 rounded-lg text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors"
        >
          <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M4 6h16M4 12h16M4 18h16" />
          </svg>
        </button>
      )}

      {/* Sidebar panel + resize handle wrapper */}
      <div
        style={{ width: window.innerWidth >= 768 ? sidebarWidth : undefined }}
        className={`
          relative md:shrink-0
          ${isOpen ? '' : 'md:hidden'}
        `}
      >
      <aside
        className={`
          flex flex-col border-r border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-gray-950 overflow-y-auto
          w-full h-full pb-14
          md:pb-0
        `}
      >
        {/* Header */}
        <div className="px-4 py-3 border-b border-gray-200 dark:border-gray-800 flex items-center justify-between">
          <div>
            <div className="flex items-center gap-2">
              <img src="/logo.svg" alt="Reli" className="h-7 w-7 rounded-md" />
              <h1 className="text-lg font-bold text-gray-900 dark:text-white tracking-tight">Reli</h1>
            </div>
            <p className="text-xs text-gray-400 dark:text-gray-400 mt-0.5">
              {new Date().toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric' })}
            </p>
          </div>
          <div className="flex items-center gap-1.5">
            {disclosure.showGraphView && (
            <button
              onClick={() => setMainView(mainView === 'graph' ? 'list' : 'graph')}
              aria-label={mainView === 'graph' ? 'Switch to list view' : 'Switch to graph view'}
              title={mainView === 'graph' ? 'List view' : 'Graph view'}
              className={`p-1.5 rounded-lg transition-colors ${
                mainView === 'graph'
                  ? 'text-indigo-500 dark:text-indigo-400 bg-indigo-50 dark:bg-indigo-950'
                  : 'text-gray-400 dark:text-gray-400 hover:bg-gray-200 dark:hover:bg-gray-800 hover:text-gray-600 dark:hover:text-gray-300'
              }`}
            >
              <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                {mainView === 'graph' ? (
                  <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 6.75h12M8.25 12h12m-12 5.25h12M3.75 6.75h.007v.008H3.75V6.75Zm.375 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0ZM3.75 12h.007v.008H3.75V12Zm.375 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm-.375 5.25h.007v.008H3.75v-.008Zm.375 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Z" />
                ) : (
                  <path strokeLinecap="round" strokeLinejoin="round" d="M7.5 3.75a3.75 3.75 0 100 7.5 3.75 3.75 0 000-7.5zm9 0a3.75 3.75 0 100 7.5 3.75 3.75 0 000-7.5zm-4.5 9a3.75 3.75 0 100 7.5 3.75 3.75 0 000-7.5zM7.5 7.5h9M12 12.75v3" />
                )}
              </svg>
            </button>
            )}
            {currentUser && (
              <div className="relative" ref={userMenuRef}>
                {currentUser.picture ? (
                  <img
                    src={currentUser.picture}
                    alt={currentUser.name}
                    className="h-7 w-7 rounded-full cursor-pointer"
                    referrerPolicy="no-referrer"
                    onClick={() => setUserMenuOpen(v => !v)}
                  />
                ) : (
                  <div
                    className="h-7 w-7 rounded-full bg-indigo-500 flex items-center justify-center text-white text-xs font-medium cursor-pointer"
                    onClick={() => setUserMenuOpen(v => !v)}
                  >
                    {currentUser.name.charAt(0).toUpperCase()}
                  </div>
                )}
                <div className={`absolute right-0 top-full mt-1 w-48 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg shadow-lg transition-all z-50 ${userMenuOpen ? 'opacity-100 visible' : 'opacity-0 invisible'}`}>
                  <div className="px-3 py-2 border-b border-gray-100 dark:border-gray-700">
                    <p className="text-sm font-medium text-gray-900 dark:text-white truncate">{currentUser.name}</p>
                    <p className="text-xs text-gray-400 dark:text-gray-400 truncate">{currentUser.email}</p>
                  </div>
                  <button
                    onClick={() => { setUserMenuOpen(false); useStore.getState().openSettings() }}
                    className="w-full text-left px-3 py-2 text-sm text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors"
                  >
                    Settings
                  </button>
                  <button
                    onClick={() => { setUserMenuOpen(false); useStore.getState().openFeedback() }}
                    className="w-full text-left px-3 py-2 text-sm text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors"
                  >
                    Send Feedback
                  </button>
                  <button
                    onClick={() => { setUserMenuOpen(false); logout() }}
                    className="w-full text-left px-3 py-2 text-sm text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-b-lg transition-colors"
                  >
                    Sign out
                  </button>
                </div>
              </div>
            )}
            <button
              onClick={() => setIsOpen(false)}
              aria-label="Close sidebar"
              className="hidden md:block p-1.5 rounded-lg text-gray-400 dark:text-gray-400 hover:bg-gray-200 dark:hover:bg-gray-800 hover:text-gray-600 dark:hover:text-gray-300 transition-colors"
            >
              <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
              </svg>
            </button>
          </div>
        </div>

        {/* Briefing / All Things view toggle (desktop only) */}
        <div className="hidden md:flex px-3 pt-2 pb-1 gap-1 border-b border-gray-200 dark:border-gray-800">
          <button
            onClick={() => setMainView('briefing')}
            className={`flex-1 py-1 text-xs font-medium rounded-md transition-colors ${
              mainView === 'briefing'
                ? 'bg-indigo-100 dark:bg-indigo-950 text-indigo-700 dark:text-indigo-300'
                : 'text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800'
            }`}
          >
            Briefing
          </button>
          <button
            onClick={() => setMainView(mainView === 'graph' ? 'graph' : 'list')}
            className={`flex-1 py-1 text-xs font-medium rounded-md transition-colors ${
              mainView === 'list' || mainView === 'graph'
                ? 'bg-indigo-100 dark:bg-indigo-950 text-indigo-700 dark:text-indigo-300'
                : 'text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800'
            }`}
          >
            All Things
          </button>
        </div>

        {/* Search bar */}
        <div className="px-3 py-2 border-b border-gray-200 dark:border-gray-800">
          <div className="relative">
            <svg xmlns="http://www.w3.org/2000/svg" className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-gray-400 dark:text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
            <input
              type="text"
              placeholder="Search everything…"
              value={searchQuery}
              onChange={e => handleSearchChange(e.target.value)}
              className="w-full pl-8 pr-7 py-1.5 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 text-gray-900 dark:text-gray-100 placeholder-gray-400 dark:placeholder-gray-400 focus:outline-none focus:ring-1 focus:ring-indigo-400 dark:focus:ring-indigo-500 focus:border-indigo-400 dark:focus:border-indigo-500"
            />
            {searchQuery ? (
              <button
                onClick={() => handleSearchChange('')}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 dark:text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
                aria-label="Clear search"
              >
                <svg xmlns="http://www.w3.org/2000/svg" className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            ) : disclosure.showCommandPaletteHint && (
              <span className="absolute right-2 top-1/2 -translate-y-1/2 text-[10px] text-gray-300 dark:text-gray-600 font-mono select-none pointer-events-none">
                ⌘K
              </span>
            )}
          </div>
        </div>

        {/* Search results */}
        {isSearching ? (
          <section className="py-2 flex-1">
            <h2 className="px-4 pb-1 text-xs font-semibold text-gray-400 dark:text-gray-400 uppercase tracking-widest">
              Search Results {!searchLoading && `(${searchResults.length})`}
            </h2>
            {searchLoading ? (
              <div className="px-4 py-3 space-y-2 animate-pulse">
                <div className="h-4 bg-gray-200 dark:bg-gray-700 rounded w-3/4"></div>
                <div className="h-4 bg-gray-200 dark:bg-gray-700 rounded w-1/2"></div>
              </div>
            ) : searchResults.length === 0 ? (
              <div className="px-4 py-4 text-sm text-gray-400 dark:text-gray-400 text-center">
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

            {/* Morning Briefing — pre-generated summary (meaningful at 5+ things) */}
            {disclosure.showBriefing && morningBriefing && <MorningBriefingSection briefing={morningBriefing} />}

            {/* Daily Briefing — sweep findings + checkin-due things (meaningful at 5+ things) */}
            {disclosure.showBriefing && (findings.length > 0 || briefing.length > 0) && (
              <section className="py-2 border-b border-gray-100 dark:border-gray-800">
                <h2 className="px-4 pb-1 text-xs font-semibold text-gray-400 dark:text-gray-400 uppercase tracking-widest">
                  Daily Briefing
                </h2>

                {/* Sweep findings */}
                {findings.map(f => (
                  <FindingCard key={f.id} finding={f} onDismiss={dismissFinding} onSnooze={handleSnooze} onAct={actOnFinding} />
                ))}

                {/* Checkin-due things */}
                {briefing.map(t => <ThingCard key={t.id} thing={t} />)}
              </section>
            )}

            {/* Focus Recommendations (priority board useful at 20+ things) */}
            {disclosure.showFocusBoard && focusRecommendations.length > 0 && (
              <section className="py-2 border-b border-gray-100 dark:border-gray-800">
                <h2 className="px-4 pb-1 text-xs font-semibold text-gray-400 dark:text-gray-400 uppercase tracking-widest">
                  Focus
                </h2>
                {focusRecommendations.slice(0, 5).map(rec => (
                  <FocusCard key={rec.thing.id} rec={rec} />
                ))}
              </section>
            )}

            {/* Merge Suggestions (relationship discovery at 10+ things) */}
            {disclosure.showConnectionDiscovery && <MergeSuggestions />}

            {/* Connection Suggestions (relationship discovery at 10+ things) */}
            {disclosure.showConnectionDiscovery && <ConnectionSuggestions />}

            {/* Conflict Alerts */}
            {conflictAlerts && conflictAlerts.length > 0 && (
              <section className="py-2 border-b border-gray-100 dark:border-gray-800">
                <h2 className="px-4 pb-1 text-xs font-semibold text-gray-400 dark:text-gray-400 uppercase tracking-widest">
                  {'\u26A0\uFE0F'} Alerts
                </h2>
                {conflictAlerts.map((alert, i) => {
                  const severityColor = alert.severity === 'critical'
                    ? 'text-red-600 dark:text-red-400'
                    : alert.severity === 'warning'
                    ? 'text-amber-600 dark:text-amber-400'
                    : 'text-blue-500 dark:text-blue-400'
                  const severityIcon = alert.severity === 'critical' ? '\u{1F6A8}' : alert.severity === 'warning' ? '\u26A0\uFE0F' : '\u2139\uFE0F'
                  const typeIcon = alert.alert_type === 'blocking_chain' ? '\u{1F6D1}' : alert.alert_type === 'schedule_overlap' ? '\u{1F4C5}' : '\u23F0'
                  return (
                    <div key={`conflict-${i}`} className="px-4 py-1.5 hover:bg-gray-100 dark:hover:bg-gray-900 transition-colors">
                      <div className="flex items-start gap-2">
                        <span className="text-sm mt-0.5 shrink-0">{typeIcon}</span>
                        <div className="flex-1 min-w-0">
                          <p className={`text-sm leading-snug ${severityColor}`}>
                            {alert.message}
                          </p>
                          <div className="flex items-center gap-1 mt-0.5">
                            <span className="text-xs">{severityIcon}</span>
                            <span className="text-xs text-gray-400 dark:text-gray-500 capitalize">{alert.severity}</span>
                          </div>
                        </div>
                      </div>
                    </div>
                  )
                })}
              </section>
            )}

            {/* Proactive Surfaces */}
            {proactiveSurfaces && proactiveSurfaces.length > 0 && (
              <section className="py-2 border-b border-gray-100 dark:border-gray-800">
                <h2 className="px-4 pb-1 text-xs font-semibold text-gray-400 dark:text-gray-400 uppercase tracking-widest">
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
                        <p className={`text-xs mt-0.5 ${s.days_away === 0 ? 'text-amber-500 font-semibold' : 'text-gray-400 dark:text-gray-400'}`}>
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
                <h2 className="px-4 pb-1 text-xs font-semibold text-gray-400 dark:text-gray-400 uppercase tracking-widest">
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

        {/* Things filter bar */}
        {active.length > 0 && (
          <div className="px-3 py-2 border-t border-gray-100 dark:border-gray-800">
            <div className="flex items-center gap-1.5">
              <div className="relative flex-1">
                <svg xmlns="http://www.w3.org/2000/svg" className="absolute left-2 top-1/2 -translate-y-1/2 h-3 w-3 text-gray-400 dark:text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
                </svg>
                <input
                  type="text"
                  placeholder="Filter things…"
                  value={thingFilterQuery}
                  onChange={e => setThingFilterQuery(e.target.value)}
                  className="w-full pl-7 pr-2 py-1 text-xs rounded border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 text-gray-900 dark:text-gray-100 placeholder-gray-400 dark:placeholder-gray-400 focus:outline-none focus:ring-1 focus:ring-indigo-400 dark:focus:ring-indigo-500"
                />
              </div>
              <div className="relative" ref={filterDropdownRef}>
                <button
                  onClick={() => setFilterDropdownOpen(o => !o)}
                  className={`p-1 rounded transition-colors relative ${
                    thingFilterTypes.length > 0
                      ? 'text-indigo-500 dark:text-indigo-400 bg-indigo-50 dark:bg-indigo-950'
                      : 'text-gray-400 dark:text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800'
                  }`}
                  aria-label="Filter by type"
                  title="Filter by type"
                >
                  <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M3 4a1 1 0 011-1h16a1 1 0 011 1v2.586a1 1 0 01-.293.707l-6.414 6.414a1 1 0 00-.293.707V17l-4 4v-6.586a1 1 0 00-.293-.707L3.293 7.293A1 1 0 013 6.586V4z" />
                  </svg>
                  {thingFilterTypes.length > 0 && (
                    <span className="absolute -top-1 -right-1 flex items-center justify-center h-3.5 w-3.5 rounded-full bg-indigo-500 text-white text-[9px] font-bold leading-none">
                      {thingFilterTypes.length}
                    </span>
                  )}
                </button>
                {filterDropdownOpen && (
                  <div className="absolute right-0 top-full mt-1 w-44 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg shadow-lg z-50 py-1">
                    {availableTypes.map(t => (
                      <button
                        key={t.type}
                        onClick={() => toggleThingFilterType(t.type)}
                        className={`w-full text-left px-3 py-1.5 text-xs flex items-center gap-2 transition-colors ${
                          thingFilterTypes.includes(t.type)
                            ? 'bg-indigo-50 dark:bg-indigo-950 text-indigo-700 dark:text-indigo-300'
                            : 'text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700'
                        }`}
                      >
                        <span>{t.icon}</span>
                        <span className="flex-1">{t.label}</span>
                        {thingFilterTypes.includes(t.type) && (
                          <svg xmlns="http://www.w3.org/2000/svg" className="h-3 w-3" viewBox="0 0 20 20" fill="currentColor">
                            <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                          </svg>
                        )}
                      </button>
                    ))}
                    {availableTypes.length === 0 && (
                      <p className="px-3 py-2 text-xs text-gray-400 dark:text-gray-400">No types available</p>
                    )}
                  </div>
                )}
              </div>
              {isThingFilterActive && (
                <button
                  onClick={clearThingFilters}
                  className="text-[10px] text-gray-400 dark:text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 whitespace-nowrap"
                  title="Clear all filters"
                >
                  Clear
                </button>
              )}
            </div>
          </div>
        )}

        {/* No results state for filtered things */}
        {isThingFilterActive && activeGroups.length === 0 && (
          <div className="px-4 py-4 text-sm text-gray-400 dark:text-gray-400 text-center">
            No things match your filters
          </div>
        )}

        {/* Active Things grouped by type */}
        {activeGroups.map(group => (
          <section key={group.type} className="py-2 border-t border-gray-100 dark:border-gray-800">
            <h2 className="px-4 pb-1 text-xs font-semibold text-gray-400 dark:text-gray-400 uppercase tracking-widest flex items-center gap-1.5">
              <span>{group.icon}</span>
              <span>{group.label}</span>
              <span className="ml-auto text-[10px] font-normal tabular-nums">{group.items.length}</span>
            </h2>
            {group.items.map(t => <ThingCard key={t.id} thing={t} />)}
          </section>
        ))}

        {/* Preferences — learned behavioral patterns */}
        {preferenceThings.length > 0 && (
          <section className="py-2 border-t border-gray-100 dark:border-gray-800">
            <h2 className="px-4 pb-1 text-xs font-semibold text-purple-400 dark:text-purple-400 uppercase tracking-widest flex items-center gap-1.5">
              <span>⚙️</span>
              <span>Preferences</span>
              <span className="ml-auto text-[10px] font-normal tabular-nums text-gray-400">{preferenceThings.length}</span>
            </h2>
            {preferenceThings.map(t => <PreferenceCard key={t.id} thing={t} />)}
          </section>
        )}

            {/* Upcoming Check-ins */}
            {upcoming.length > 0 && (
              <section className="py-2">
                <h2 className="px-4 pb-1 text-xs font-semibold text-gray-400 dark:text-gray-400 uppercase tracking-widest">
                  Upcoming Check-ins
                </h2>
                {upcoming.map(t => <ThingCard key={t.id} thing={t} />)}
              </section>
            )}

            {/* Gmail */}
            <GmailPanel />

            {!loading && things.length === 0 && (
              <div className="px-4 py-6 text-sm text-gray-400 dark:text-gray-400 text-center">
                Start by typing in the chat…
              </div>
            )}
          </>
        )}
      </aside>
        {/* Drag handle — desktop only, outside aside to avoid overflow clipping */}
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
      </div>
    </>
  )
}
