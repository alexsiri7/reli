import React, { useState, useEffect, useRef, useCallback, useMemo, type PointerEvent as ReactPointerEvent } from 'react'
import { useShallow } from 'zustand/react/shallow'
import { useStore } from '../store'
import { apiFetch } from '../api'
import type { Thing, SweepFinding, FocusRecommendation, MorningBriefing, WeeklyBriefing } from '../store'
import { NudgeBanner } from './NudgeBanner'
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
      className="group px-4 py-2 hover:bg-surface-container-high transition-colors"
    >
      <div className="flex items-start gap-2">
        <span className="text-sm mt-0.5 shrink-0">{icon}</span>
        <div className="flex-1 min-w-0">
          <p className="text-sm text-on-surface leading-snug">{finding.message}</p>
          {finding.thing && (
            <p className="text-xs text-on-surface-variant mt-0.5 truncate">
              {typeIcon(finding.thing.type_hint)} {finding.thing.title}
            </p>
          )}
          {/* Action buttons */}
          <div className="flex items-center gap-2 mt-1.5 opacity-0 group-hover:opacity-100 transition-opacity">
            {finding.thing_id && (
              <button
                onClick={() => onAct(finding)}
                className="text-xs text-primary hover:text-primary/80 font-medium"
                title="Open in detail panel"
              >
                Open
              </button>
            )}
            <button
              onClick={() => onSnooze(finding.id)}
              className="text-xs text-on-surface-variant hover:text-on-surface"
              title="Snooze for 1 day"
            >
              Snooze
            </button>
            <button
              onClick={() => onDismiss(finding.id)}
              className="text-xs text-on-surface-variant hover:text-ideas"
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
        className="flex items-start gap-2 py-1.5 rounded-lg hover:bg-surface-container-high transition-colors px-2 cursor-pointer"
        onClick={() => useStore.getState().openThingDetail(rec.thing.id)}
        role="button"
      >
        <span className="text-lg leading-none mt-0.5 select-none" title={rec.thing.type_hint ?? 'thing'}>
          {typeIcon(rec.thing.type_hint)}
        </span>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-on-surface truncate leading-snug">
            {rec.thing.title}
          </p>
          <p className="text-xs text-on-surface-variant mt-0.5 leading-snug">
            {rec.reasons.join(' \u00B7 ')}
          </p>
        </div>
        {rec.is_blocked && (
          <span className="text-[10px] text-ideas font-medium mt-1 shrink-0">BLOCKED</span>
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
    <section className="py-2">
      <button
        className="w-full flex items-center justify-between px-4 pb-1"
        onClick={() => setExpanded(!expanded)}
      >
        <h2 className="text-label font-semibold text-on-surface-variant">
          Morning Briefing
        </h2>
        <span className="text-xs text-on-surface-variant">{expanded ? '\u25B2' : '\u25BC'}</span>
      </button>

      {expanded && (
        <div className="space-y-1">
          {/* Summary */}
          <p className="px-4 text-sm text-on-surface leading-snug">
            {c.summary}
          </p>

          {/* Overdue items */}
          {hasOverdue && (
            <div className="px-4 mt-1">
              <p className="text-label font-medium text-ideas mb-0.5">Overdue</p>
              {c.overdue.map(item => (
                <div
                  key={item.thing_id}
                  className="flex items-center gap-2 py-1 cursor-pointer hover:bg-surface-container-high rounded px-1 -mx-1"
                  onClick={() => useStore.getState().openThingDetail(item.thing_id)}
                  role="button"
                >
                  <span className="text-ideas text-xs shrink-0">{'\u26A0'}</span>
                  <span className="text-sm text-on-surface truncate flex-1">{item.title}</span>
                  <span className="text-xs text-ideas shrink-0">{item.days_overdue}d</span>
                </div>
              ))}
            </div>
          )}

          {/* Top priorities */}
          {hasPriorities && (
            <div className="px-4 mt-1">
              <p className="text-label font-medium text-events mb-0.5">Priorities</p>
              {c.priorities.map(item => (
                <div
                  key={item.thing_id}
                  className="flex items-start gap-2 py-1 cursor-pointer hover:bg-surface-container-high rounded px-1 -mx-1"
                  onClick={() => useStore.getState().openThingDetail(item.thing_id)}
                  role="button"
                >
                  <span className="text-events text-xs mt-0.5 shrink-0">{'\u2B50'}</span>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-on-surface truncate leading-snug">{item.title}</p>
                    <p className="text-xs text-on-surface-variant leading-snug">{item.reasons.join(' \u00B7 ')}</p>
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Blockers */}
          {hasBlockers && (
            <div className="px-4 mt-1">
              <p className="text-label font-medium text-events mb-0.5">Blocked</p>
              {c.blockers.map(item => (
                <div
                  key={item.thing_id}
                  className="flex items-start gap-2 py-1 cursor-pointer hover:bg-surface-container-high rounded px-1 -mx-1"
                  onClick={() => useStore.getState().openThingDetail(item.thing_id)}
                  role="button"
                >
                  <span className="text-events text-xs mt-0.5 shrink-0">{'\u{1F6AB}'}</span>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-on-surface truncate leading-snug">{item.title}</p>
                    {item.blocked_by.length > 0 && (
                      <p className="text-xs text-on-surface-variant leading-snug truncate">
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
              <p className="text-label font-medium text-primary mb-0.5">Insights</p>
              {c.findings.slice(0, 5).map(f => (
                <div
                  key={f.id}
                  className={`flex items-start gap-2 py-1 ${f.thing_id ? 'cursor-pointer hover:bg-surface-container-high' : ''} rounded px-1 -mx-1`}
                  onClick={() => f.thing_id && useStore.getState().openThingDetail(f.thing_id)}
                  role={f.thing_id ? 'button' : undefined}
                >
                  <span className="text-primary text-xs mt-0.5 shrink-0">{'\u{1F4A1}'}</span>
                  <p className="text-sm text-on-surface leading-snug">{f.message}</p>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </section>
  )
}

function WeeklyBriefingSection({ briefing }: { briefing: WeeklyBriefing }) {
  const [expanded, setExpanded] = useState(false)
  const c = briefing.content

  const hasContent = c.completed.length > 0 || c.upcoming.length > 0 || c.new_connections.length > 0 || c.preferences_learned.length > 0 || c.open_questions.length > 0
  if (!hasContent && !c.summary) return null

  return (
    <section className="py-2">
      <button
        className="w-full flex items-center justify-between px-4 pb-1"
        onClick={() => setExpanded(!expanded)}
      >
        <h2 className="text-label font-semibold text-on-surface-variant">
          Weekly Digest
        </h2>
        <span className="text-xs text-on-surface-variant">{expanded ? '\u25B2' : '\u25BC'}</span>
      </button>

      <p className="px-4 text-sm text-on-surface leading-snug">{c.summary}</p>

      {expanded && (
        <div className="space-y-1 mt-1">
          {c.upcoming.length > 0 && (
            <div className="px-4">
              <p className="text-label font-medium text-events mb-0.5">Upcoming</p>
              {c.upcoming.map(item => (
                <div
                  key={item.thing_id}
                  className="flex items-center gap-2 py-1 cursor-pointer hover:bg-surface-container-high rounded px-1 -mx-1"
                  onClick={() => useStore.getState().openThingDetail(item.thing_id)}
                  role="button"
                >
                  <span className="text-sm shrink-0">{typeIcon(item.type_hint)}</span>
                  <span className="text-sm text-on-surface truncate flex-1">{item.title}</span>
                  {item.detail && <span className="text-xs text-events shrink-0">{item.detail}</span>}
                </div>
              ))}
            </div>
          )}

          {c.completed.length > 0 && (
            <div className="px-4">
              <p className="text-label font-medium text-projects mb-0.5">Completed</p>
              {c.completed.map(item => (
                <div
                  key={item.thing_id}
                  className="flex items-center gap-2 py-1 cursor-pointer hover:bg-surface-container-high rounded px-1 -mx-1"
                  onClick={() => useStore.getState().openThingDetail(item.thing_id)}
                  role="button"
                >
                  <span className="text-projects text-xs shrink-0">{'\u2713'}</span>
                  <span className="text-sm text-on-surface truncate flex-1">{item.title}</span>
                </div>
              ))}
            </div>
          )}

          {c.new_connections.length > 0 && (
            <div className="px-4">
              <p className="text-label font-medium text-primary mb-0.5">New Connections</p>
              {c.new_connections.map((conn, i) => (
                <p key={i} className="text-sm text-on-surface py-0.5 leading-snug">
                  <span className="font-medium">{conn.from_title}</span>
                  <span className="text-on-surface-variant mx-1">{'\u2192'}</span>
                  <span className="font-medium">{conn.to_title}</span>
                  {conn.relationship_type && <span className="text-on-surface-variant ml-1 text-xs">({conn.relationship_type})</span>}
                </p>
              ))}
            </div>
          )}

          {c.open_questions.length > 0 && (
            <div className="px-4">
              <p className="text-label font-medium text-primary mb-0.5">Open Questions</p>
              {c.open_questions.map(item => (
                <div
                  key={item.thing_id}
                  className="flex items-start gap-2 py-1 cursor-pointer hover:bg-surface-container-high rounded px-1 -mx-1"
                  onClick={() => useStore.getState().openThingDetail(item.thing_id)}
                  role="button"
                >
                  <span className="text-primary text-xs mt-0.5 shrink-0">{'\u2753'}</span>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-on-surface truncate leading-snug">{item.title}</p>
                    {item.detail && <p className="text-xs text-on-surface-variant leading-snug truncate">{item.detail}</p>}
                  </div>
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
  if (confidence >= 0.7) return { label: 'Strong', className: 'text-projects bg-projects/10' }
  if (confidence >= 0.5) return { label: 'Moderate', className: 'text-primary bg-primary/10' }
  return { label: 'Emerging', className: 'text-events bg-events/10' }
}

function PreferenceCard({ thing }: { thing: Thing }) {
  const openThingDetail = useStore(s => s.openThingDetail)
  const submitPreferenceFeedback = useStore(s => s.submitPreferenceFeedback)
  const [feedbackSent, setFeedbackSent] = useState<'accurate' | 'inaccurate' | null>(null)
  const confidence: number = typeof thing.data?.confidence === 'number' ? thing.data.confidence : 0
  const evidence: unknown[] = Array.isArray(thing.data?.evidence) ? (thing.data.evidence as unknown[]) : []
  const category: string = typeof thing.data?.category === 'string' ? thing.data.category : ''
  const { label, className } = confidenceLabel(confidence)

  const handleFeedback = useCallback((accurate: boolean, e: React.MouseEvent) => {
    e.stopPropagation()
    if (feedbackSent) return
    setFeedbackSent(accurate ? 'accurate' : 'inaccurate')
    submitPreferenceFeedback(thing.id, accurate)
  }, [feedbackSent, submitPreferenceFeedback, thing.id])

  return (
    <div className="px-3 py-1 group">
      <div
        className="flex items-start gap-2 py-1.5 rounded-lg hover:bg-surface-container-high transition-colors px-2 cursor-pointer"
        onClick={() => openThingDetail(thing.id)}
        role="button"
      >
        <span className="text-base leading-none mt-0.5 select-none shrink-0">🧠</span>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-on-surface truncate leading-snug">
            {thing.title}
          </p>
          <div className="flex items-center gap-1.5 mt-0.5 flex-wrap">
            <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded-full ${className}`}>
              {label}
            </span>
            {evidence.length > 0 && (
              <span className="text-[10px] text-on-surface-variant">
                {evidence.length} obs.
              </span>
            )}
            {category && (
              <span className="text-[10px] text-on-surface-variant capitalize">
                {category}
              </span>
            )}
          </div>
          {/* Feedback buttons */}
          <div className="flex items-center gap-1.5 mt-1 opacity-0 group-hover:opacity-100 transition-opacity">
            {feedbackSent === null ? (
              <>
                <button
                  onClick={e => handleFeedback(true, e)}
                  className="text-[10px] px-2 py-0.5 rounded-full bg-projects/20 text-projects hover:bg-projects/30 font-medium transition-colors"
                  title="Confirm this preference"
                >
                  That&apos;s right
                </button>
                <button
                  onClick={e => handleFeedback(false, e)}
                  className="text-[10px] px-2 py-0.5 rounded-full bg-surface-container-high text-on-surface-variant hover:bg-surface-container-high/80 font-medium transition-colors"
                  title="Correct this preference"
                >
                  Not really
                </button>
              </>
            ) : (
              <span className="text-[10px] text-on-surface-variant italic">
                {feedbackSent === 'accurate' ? 'Thanks for confirming!' : 'Got it, noted.'}
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
const SIDEBAR_DEFAULT_WIDTH = 240
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

const TYPE_ORDER = ['task', 'project', 'person', 'idea', 'note', 'goal', 'journal', 'preference'] as const

const FALLBACK_LABELS: Record<string, string> = {
  project: 'Projects',
  goal: 'Goals',
  task: 'Tasks',
  note: 'Notes',
  idea: 'Ideas',
  journal: 'Journal',
  preference: 'Preferences',
  person: 'People',
}

const SEVERITY_COLORS: Record<string, string> = {
  critical: 'text-ideas',
  warning: 'text-events',
}

function singularize(label: string): string {
  if (label === 'People') return 'person'
  if (label.endsWith('ies')) return label.slice(0, -3) + 'y'
  return label.slice(0, -1).toLowerCase()
}

export function Sidebar() {
  const { currentUser, logout, things, thingTypes, briefing, theOneThing, findings, proactiveSurfaces, focusRecommendations, conflictAlerts, morningBriefing, nudges, weeklyBriefing, loading, searchResults, searchLoading, searchThings, clearSearch, dismissFinding, snoozeFinding, actOnFinding, thingFilterQuery, thingFilterTypes, setThingFilterQuery, toggleThingFilterType, clearThingFilters, mainView, setMainView, rightView, setRightView, sidebarOpen, setSidebarOpen, createThing, openQuickAdd } = useStore(useShallow(s => ({ currentUser: s.currentUser, logout: s.logout, things: s.things, thingTypes: s.thingTypes, briefing: s.briefing, theOneThing: s.theOneThing, findings: s.findings, proactiveSurfaces: s.proactiveSurfaces, focusRecommendations: s.focusRecommendations, conflictAlerts: s.conflictAlerts, morningBriefing: s.morningBriefing, nudges: s.nudges, weeklyBriefing: s.weeklyBriefing, loading: s.loading, searchResults: s.searchResults, searchLoading: s.searchLoading, searchThings: s.searchThings, clearSearch: s.clearSearch, dismissFinding: s.dismissFinding, snoozeFinding: s.snoozeFinding, actOnFinding: s.actOnFinding, thingFilterQuery: s.thingFilterQuery, thingFilterTypes: s.thingFilterTypes, setThingFilterQuery: s.setThingFilterQuery, toggleThingFilterType: s.toggleThingFilterType, clearThingFilters: s.clearThingFilters, mainView: s.mainView, setMainView: s.setMainView, rightView: s.rightView, setRightView: s.setRightView, sidebarOpen: s.sidebarOpen, setSidebarOpen: s.setSidebarOpen, createThing: s.createThing, openQuickAdd: s.openQuickAdd })))
  const disclosure = useProgressiveDisclosure()
  const [searchQuery, setSearchQuery] = useState('')
  const [collapsedSections, setCollapsedSections] = useState<Set<string>>(new Set())
  const toggleSection = useCallback((type: string) => {
    setCollapsedSections(prev => {
      const next = new Set(prev)
      if (next.has(type)) next.delete(type)
      else next.add(type)
      return next
    })
  }, [])
  const [completedTasks, setCompletedTasks] = useState<Thing[]>([])
  const handleTaskComplete = useCallback((thing: Thing) => {
    setCompletedTasks(prev => [...prev.filter(t => t.id !== thing.id), thing])
  }, [])
  const [quickAddSection, setQuickAddSection] = useState<string | null>(null)
  const [quickAddTitle, setQuickAddTitle] = useState('')
  const [quickAddSaving, setQuickAddSaving] = useState(false)
  const [quickAddError, setQuickAddError] = useState<string | null>(null)
  const [quickAddCheckinDate, setQuickAddCheckinDate] = useState('')
  const [quickAddParentId, setQuickAddParentId] = useState('')
  const closeQuickAdd = useCallback(() => {
    setQuickAddSection(null)
    setQuickAddTitle('')
    setQuickAddCheckinDate('')
    setQuickAddParentId('')
  }, [])
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

  const handleQuickAddSubmit = useCallback(async (type: string) => {
    const trimmed = quickAddTitle.trim()
    if (!trimmed) return
    setQuickAddSaving(true)
    setQuickAddError(null)
    try {
      const newThing = await createThing(trimmed, type, quickAddCheckinDate || undefined)
      if (quickAddParentId && newThing?.id) {
        const relRes = await apiFetch('/api/things/relationships', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            from_thing_id: quickAddParentId,
            to_thing_id: newThing.id,
            relationship_type: 'parent-of',
          }),
        })
        if (!relRes.ok) {
          throw new Error(`Task created but parent link failed (${relRes.status}) — try again`)
        }
      }
      closeQuickAdd()
    } catch (err) {
      setQuickAddError(err instanceof Error ? err.message : 'Failed to create')
    } finally {
      setQuickAddSaving(false)
    }
  }, [quickAddTitle, quickAddCheckinDate, quickAddParentId, createThing, closeQuickAdd])

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

  const [isOpen, setIsOpenLocal] = useState(() =>
    typeof window !== 'undefined' ? window.innerWidth >= 768 : true
  )

  // Keep local open state in sync with store (Cmd+B drives the store)
  useEffect(() => {
    setIsOpenLocal(sidebarOpen)
  }, [sidebarOpen])

  const setIsOpen = (open: boolean) => {
    setIsOpenLocal(open)
    setSidebarOpen(open)
  }

  useEffect(() => {
    const mql = window.matchMedia('(min-width: 768px)')
    const handler = (e: MediaQueryListEvent) => {
      setIsOpenLocal(e.matches)
      setSidebarOpen(e.matches)
    }
    mql.addEventListener('change', handler)
    return () => mql.removeEventListener('change', handler)
  }, [setSidebarOpen])

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
    // Build label map from DB types (pluralise by appending 's')
    const typeLabels: Record<string, string> = { ...FALLBACK_LABELS }
    for (const tt of thingTypes) {
      if (!typeLabels[tt.name]) {
        typeLabels[tt.name] = tt.name.charAt(0).toUpperCase() + tt.name.slice(1) + 's'
      }
    }
    const projectIds = new Set(active.filter(t => t.type_hint === 'project').map(t => t.id))
    // Don't show children of projects or preference Things as standalone items (preferences get their own section)
    let standalone = active.filter(t => {
      const parentIds = t.parent_ids ?? []
      const isChildOfProject = parentIds.some(pid => projectIds.has(pid))
      return !isChildOfProject && t.type_hint !== 'preference'
    })

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
          className="hidden md:block md:static md:m-0 md:border-0 md:shadow-none md:rounded-none md:bg-surface-container-low md:px-2 md:py-3 p-2 rounded-lg text-on-surface-variant hover:bg-surface-container-high transition-colors"
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
          relative md:shrink-0 h-full
          ${isOpen ? '' : 'md:hidden'}
        `}
      >
      <aside
        className="flex flex-col bg-surface-container-low w-full h-full"
      >
        <div className="flex-1 overflow-y-auto min-h-0 pb-14 md:pb-0">
        {/* Header */}
        <div className="px-4 py-4 flex items-center justify-between">
          <div>
            <div className="flex items-center gap-2">
              {/* Mobile: show user avatar */}
              {currentUser?.picture && (
                <div className="md:hidden w-8 h-8 rounded-full overflow-hidden border border-white/5 shrink-0">
                  <img src={currentUser.picture} alt={currentUser.name ?? 'User'} className="w-full h-full object-cover" />
                </div>
              )}
              <div className="w-7 h-7 rounded bg-primary-container flex items-center justify-center">
                <img src="/logo.svg" alt="Reli" className="h-4 w-4" />
              </div>
              <h1 className="text-lg font-bold text-on-surface tracking-tight">The Radar</h1>
            </div>
            <p className="text-label text-on-surface-variant mt-0.5">
              {new Date().toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric' })}
            </p>
          </div>
          <div className="flex items-center gap-1.5">
            {/* Briefing / Chat toggle */}
            <button
              onClick={() => setRightView(rightView === 'briefing' ? 'chat' : 'briefing')}
              aria-label={rightView === 'briefing' ? 'Switch to Chat' : 'Switch to Briefing'}
              title={rightView === 'briefing' ? 'Chat' : 'Briefing'}
              className={`p-1.5 rounded-lg transition-colors ${
                rightView === 'briefing'
                  ? 'text-primary bg-primary/10'
                  : 'text-on-surface-variant hover:bg-surface-container-high hover:text-on-surface'
              }`}
            >
              {rightView === 'briefing' ? (
                <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 7.5h1.5m-1.5 3h1.5m-7.5 3h7.5m-7.5 3h7.5m3-9h3.375c.621 0 1.125.504 1.125 1.125V18a2.25 2.25 0 0 1-2.25 2.25M16.5 7.5V18a2.25 2.25 0 0 0 2.25 2.25M16.5 7.5V4.875c0-.621-.504-1.125-1.125-1.125H4.125C3.504 3.75 3 4.254 3 4.875V18a2.25 2.25 0 0 0 2.25 2.25h13.5M6 7.5h3v3H6v-3Z" />
                </svg>
              ) : (
                <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M8.625 12a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0H8.25m4.125 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0H12m4.125 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0h-.375M21 12c0 4.556-4.03 8.25-9 8.25a9.764 9.764 0 0 1-2.555-.337A5.972 5.972 0 0 1 5.41 20.97a5.969 5.969 0 0 1-.474-.065 4.48 4.48 0 0 0 .978-2.025c.09-.457-.133-.901-.467-1.226C3.93 16.178 3 14.189 3 12c0-4.556 4.03-8.25 9-8.25s9 3.694 9 8.25Z" />
                </svg>
              )}
            </button>
            {disclosure.showGraphView && (
            <>
            <button
              onClick={() => setMainView(mainView === 'graph' ? 'list' : 'graph')}
              aria-label={mainView === 'graph' ? 'Switch to list view' : 'Switch to graph view'}
              title={mainView === 'graph' ? 'List view' : 'Graph view'}
              className={`p-1.5 rounded-lg transition-colors ${
                mainView === 'graph'
                  ? 'text-primary bg-primary/10'
                  : 'text-on-surface-variant hover:bg-surface-container-high hover:text-on-surface'
              }`}
            >
              <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M7.5 3.75a3.75 3.75 0 100 7.5 3.75 3.75 0 000-7.5zm9 0a3.75 3.75 0 100 7.5 3.75 3.75 0 000-7.5zm-4.5 9a3.75 3.75 0 100 7.5 3.75 3.75 0 000-7.5zM7.5 7.5h9M12 12.75v3" />
              </svg>
            </button>
            <button
              onClick={() => setMainView(mainView === 'calendar' ? 'list' : 'calendar')}
              aria-label={mainView === 'calendar' ? 'Switch to list view' : 'Switch to calendar view'}
              title={mainView === 'calendar' ? 'List view' : 'Calendar view'}
              className={`p-1.5 rounded-lg transition-colors ${
                mainView === 'calendar'
                  ? 'text-primary bg-primary/10'
                  : 'text-on-surface-variant hover:bg-surface-container-high hover:text-on-surface'
              }`}
            >
              <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M6.75 3v2.25M17.25 3v2.25M3 18.75V7.5a2.25 2.25 0 0 1 2.25-2.25h13.5A2.25 2.25 0 0 1 21 7.5v11.25m-18 0A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75m-18 0v-7.5A2.25 2.25 0 0 1 5.25 9h13.5A2.25 2.25 0 0 1 21 11.25v7.5" />
              </svg>
            </button>
            </>
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
                    className="h-7 w-7 rounded-full bg-primary flex items-center justify-center text-white text-xs font-medium cursor-pointer"
                    onClick={() => setUserMenuOpen(v => !v)}
                  >
                    {currentUser.name.charAt(0).toUpperCase()}
                  </div>
                )}
                <div className={`absolute right-0 top-full mt-1 w-48 bg-surface-container-high border border-on-surface-variant/10 rounded-lg shadow-lg transition-all z-50 ${userMenuOpen ? 'opacity-100 visible' : 'opacity-0 invisible'}`}>
                  <div className="px-3 py-3 bg-surface rounded-t-lg">
                    <p className="text-sm font-medium text-on-surface truncate">{currentUser.name}</p>
                    <p className="text-xs text-on-surface-variant truncate">{currentUser.email}</p>
                  </div>
                  <button
                    onClick={() => { setUserMenuOpen(false); useStore.getState().openSettings() }}
                    className="w-full text-left px-3 py-2 text-sm text-on-surface-variant hover:bg-surface-container-low hover:text-on-surface transition-colors"
                  >
                    Settings
                  </button>
                  <button
                    onClick={() => { setUserMenuOpen(false); useStore.getState().openFeedback() }}
                    className="w-full text-left px-3 py-2 text-sm text-on-surface-variant hover:bg-surface-container-low hover:text-on-surface transition-colors"
                  >
                    Send Feedback
                  </button>
                  <button
                    onClick={() => { setUserMenuOpen(false); logout() }}
                    className="w-full text-left px-3 py-2 text-sm text-on-surface-variant hover:bg-surface-container-low hover:text-on-surface rounded-b-lg transition-colors"
                  >
                    Sign out
                  </button>
                </div>
              </div>
            )}
            <button
              onClick={() => setIsOpen(false)}
              aria-label="Close sidebar"
              className="hidden md:block p-1.5 rounded-lg text-on-surface-variant hover:bg-surface-container-high hover:text-on-surface transition-colors"
            >
              <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
              </svg>
            </button>
          </div>
        </div>

        {/* Search bar */}
        <div className="px-3 py-2">
          <div className="relative">
            <svg xmlns="http://www.w3.org/2000/svg" className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-on-surface-variant" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
            <input
              type="text"
              placeholder="Search everything…"
              value={searchQuery}
              onChange={e => handleSearchChange(e.target.value)}
              className="w-full pl-8 pr-16 py-1.5 text-sm rounded-lg border border-on-surface-variant/10 bg-surface text-on-surface placeholder-on-surface-variant focus:outline-none focus:ring-1 focus:ring-primary focus:border-primary"
            />
            {searchQuery ? (
              <button
                onClick={() => handleSearchChange('')}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-on-surface-variant hover:text-on-surface"
                aria-label="Clear search"
              >
                <svg xmlns="http://www.w3.org/2000/svg" className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            ) : disclosure.showCommandPaletteHint && (
              <span className="absolute right-2 top-1/2 -translate-y-1/2 text-[10px] text-on-surface-variant/50 font-mono select-none pointer-events-none">
                ⌘K
              </span>
            )}
          </div>
        </div>

        {/* Search results */}
        {isSearching ? (
          <section className="py-2 flex-1">
            <h2 className="px-4 pb-1 text-label font-semibold text-on-surface-variant">
              Search Results {!searchLoading && `(${searchResults.length})`}
            </h2>
            {searchLoading ? (
              <div className="px-4 py-3 space-y-2 animate-pulse">
                <div className="h-4 bg-surface-container-high rounded w-3/4"></div>
                <div className="h-4 bg-surface-container-high rounded w-1/2"></div>
              </div>
            ) : searchResults.length === 0 ? (
              <div className="px-4 py-4 text-sm text-on-surface-variant text-center">
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
                <div className="h-4 bg-surface-container-high rounded w-3/4"></div>
                <div className="h-4 bg-surface-container-high rounded w-1/2"></div>
                <div className="h-4 bg-surface-container-high rounded w-5/6"></div>
              </div>
            )}

            {/* The One Thing — hero card */}
            {theOneThing && (
              <div className="px-4 pt-3 pb-1">
                {/* Mobile hero card — gradient glow, prominent typography */}
                <div
                  className="md:hidden relative group cursor-pointer active:scale-[0.98] transition-transform duration-300"
                  onClick={() => useStore.getState().openThingDetail(theOneThing.thing.id)}
                  role="button"
                >
                  <div className="absolute inset-0 bg-gradient-to-br from-primary to-primary/20 blur-xl opacity-20 group-hover:opacity-30 transition-opacity rounded-2xl" />
                  <div className="relative bg-surface-container-high p-6 rounded-2xl border border-white/5 overflow-hidden">
                    <div className="flex flex-col gap-3">
                      <div className="flex items-center gap-2">
                        <span className="w-2 h-2 rounded-full bg-ideas animate-pulse shrink-0" />
                        <span className="text-[10px] uppercase tracking-[0.2em] font-bold text-on-surface-variant">The One Thing</span>
                      </div>
                      <h3 className="text-2xl font-black tracking-tighter text-on-surface leading-tight">
                        {theOneThing.thing.title}
                      </h3>
                      {theOneThing.reasons.length > 0 && (
                        <p className="text-sm text-on-surface-variant leading-snug">{theOneThing.reasons[0]}</p>
                      )}
                      {theOneThing.thing.checkin_date && (
                        <p className="text-sm font-medium text-primary">
                          Due {new Date(theOneThing.thing.checkin_date).toLocaleDateString(undefined, { weekday: 'long' })}
                        </p>
                      )}
                    </div>
                  </div>
                </div>
                {/* Desktop hero card — existing glass card */}
                <div
                  className="hidden md:block glass p-5 rounded-2xl cursor-pointer hover:bg-surface-container-high/80 transition-colors"
                  onClick={() => useStore.getState().openThingDetail(theOneThing.thing.id)}
                  role="button"
                >
                  <p className="text-label font-bold text-on-surface-variant mb-2">The One Thing</p>
                  <h3 className="text-on-surface font-bold text-lg leading-tight">{theOneThing.thing.title}</h3>
                  {theOneThing.reasons.length > 0 && (
                    <p className="text-xs text-on-surface-variant mt-2 leading-snug">
                      {theOneThing.reasons[0]}
                    </p>
                  )}
                </div>
              </div>
            )}

            {/* Google Calendar */}
            <CalendarSection />

            {/* Nudges — time-sensitive proactive reminders */}
            {nudges.length > 0 && (
              <section className="px-3 pt-2 pb-1">
                {nudges.map(nudge => (
                  <NudgeBanner key={nudge.id} nudge={nudge} />
                ))}
              </section>
            )}

            {/* Morning Briefing — pre-generated summary (meaningful at 5+ things) */}
            {disclosure.showBriefing && morningBriefing && <MorningBriefingSection briefing={morningBriefing} />}

            {/* Weekly Digest */}
            {disclosure.showGraphView && weeklyBriefing && <WeeklyBriefingSection briefing={weeklyBriefing} />}

            {/* Briefing empty state */}
            {!loading && !morningBriefing && !(disclosure.showGraphView && weeklyBriefing) && findings.length === 0 && briefing.length === 0 && (
              <div className="px-4 py-3">
                <h2 className="pb-1 text-label font-semibold text-on-surface-variant">
                  Daily Briefing
                </h2>
                <p className="text-xs text-on-surface-variant py-1">
                  Your morning briefing shows up here once you have Things with check-in dates.
                </p>
              </div>
            )}

            {/* Daily Briefing — sweep findings + checkin-due things */}
            {(findings.length > 0 || briefing.length > 0) && (
              <section className="py-2">
                <h2 className="px-4 pb-1 text-label font-semibold text-on-surface-variant">
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
              <section className="py-2">
                <h2 className="px-4 pb-1 text-label font-semibold text-on-surface-variant">
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
              <section className="py-2">
                <h2 className="px-4 pb-1 text-label font-semibold text-on-surface-variant">
                  {'\u26A0\uFE0F'} Alerts
                </h2>
                {conflictAlerts.map((alert, i) => {
                  const severityColor = SEVERITY_COLORS[alert.severity] ?? 'text-primary'
                  const severityIcon = alert.severity === 'critical' ? '\u{1F6A8}' : alert.severity === 'warning' ? '\u26A0\uFE0F' : '\u2139\uFE0F'
                  const typeIcon = alert.alert_type === 'blocking_chain' ? '\u{1F6D1}' : alert.alert_type === 'schedule_overlap' ? '\u{1F4C5}' : '\u23F0'
                  return (
                    <div key={`conflict-${i}`} className="px-4 py-1.5 hover:bg-surface-container-high transition-colors">
                      <div className="flex items-start gap-2">
                        <span className="text-sm mt-0.5 shrink-0">{typeIcon}</span>
                        <div className="flex-1 min-w-0">
                          <p className={`text-sm leading-snug ${severityColor}`}>
                            {alert.message}
                          </p>
                          <div className="flex items-center gap-1 mt-0.5">
                            <span className="text-xs">{severityIcon}</span>
                            <span className="text-xs text-on-surface-variant capitalize">{alert.severity}</span>
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
              <section className="py-2">
                <h2 className="px-4 pb-1 text-label font-semibold text-on-surface-variant">
                  Coming Up
                </h2>
                {proactiveSurfaces.map(s => (
                  <div key={`${s.thing.id}-${s.date_key}`} className="px-3 py-1">
                    <div
                      className="flex items-start gap-2 py-1.5 rounded-lg hover:bg-surface-container-high transition-colors px-2 cursor-pointer"
                      onClick={() => useStore.getState().openThingDetail(s.thing.id)}
                      role="button"
                    >
                      <span className="text-lg leading-none mt-0.5 select-none" title={s.thing.type_hint ?? 'thing'}>
                        {typeIcon(s.thing.type_hint, thingTypes)}
                      </span>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium text-on-surface truncate leading-snug">
                          {s.thing.title}
                        </p>
                        <p className={`text-xs mt-0.5 ${s.days_away === 0 ? 'text-events font-semibold' : 'text-on-surface-variant'}`}>
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
              <section className="py-2">
                <h2 className="px-4 pb-1 text-label font-semibold text-on-surface-variant">
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
          <div className="px-3 py-2 mt-2">
            <div className="flex items-center gap-1.5">
              <div className="relative flex-1">
                <svg xmlns="http://www.w3.org/2000/svg" className="absolute left-2 top-1/2 -translate-y-1/2 h-3 w-3 text-on-surface-variant" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
                </svg>
                <input
                  type="text"
                  placeholder="Filter things…"
                  value={thingFilterQuery}
                  onChange={e => setThingFilterQuery(e.target.value)}
                  className="w-full pl-7 pr-2 py-1 text-xs rounded border border-on-surface-variant/10 bg-surface text-on-surface placeholder-on-surface-variant focus:outline-none focus:ring-1 focus:ring-primary"
                />
              </div>
              <div className="relative" ref={filterDropdownRef}>
                <button
                  onClick={() => setFilterDropdownOpen(o => !o)}
                  className={`p-1 rounded transition-colors relative ${
                    thingFilterTypes.length > 0
                      ? 'text-primary bg-primary/10'
                      : 'text-on-surface-variant hover:text-on-surface hover:bg-surface-container-high'
                  }`}
                  aria-label="Filter by type"
                  title="Filter by type"
                >
                  <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M3 4a1 1 0 011-1h16a1 1 0 011 1v2.586a1 1 0 01-.293.707l-6.414 6.414a1 1 0 00-.293.707V17l-4 4v-6.586a1 1 0 00-.293-.707L3.293 7.293A1 1 0 013 6.586V4z" />
                  </svg>
                  {thingFilterTypes.length > 0 && (
                    <span className="absolute -top-1 -right-1 flex items-center justify-center h-3.5 w-3.5 rounded-full bg-primary text-white text-[9px] font-bold leading-none">
                      {thingFilterTypes.length}
                    </span>
                  )}
                </button>
                {filterDropdownOpen && (
                  <div className="absolute right-0 top-full mt-1 w-44 bg-surface-container-high border border-on-surface-variant/10 rounded-lg shadow-lg z-50 py-1">
                    {availableTypes.map(t => (
                      <button
                        key={t.type}
                        onClick={() => toggleThingFilterType(t.type)}
                        className={`w-full text-left px-3 py-1.5 text-xs flex items-center gap-2 transition-colors ${
                          thingFilterTypes.includes(t.type)
                            ? 'bg-primary/10 text-primary'
                            : 'text-on-surface-variant hover:bg-surface-container-low hover:text-on-surface'
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
                      <p className="px-3 py-2 text-xs text-on-surface-variant">No types available</p>
                    )}
                  </div>
                )}
              </div>
              {isThingFilterActive && (
                <button
                  onClick={clearThingFilters}
                  className="text-[10px] text-on-surface-variant hover:text-on-surface whitespace-nowrap"
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
          <div className="px-4 py-4 text-sm text-on-surface-variant text-center">
            No things match your filters
          </div>
        )}

        {/* Active Things grouped by type */}
        {activeGroups.map(group => (
          <section key={group.type} className="py-2">
            <button
              onClick={() => toggleSection(group.type)}
              aria-expanded={!collapsedSections.has(group.type)}
              className="w-full px-4 pb-1 text-label font-semibold text-on-surface-variant flex items-center gap-1.5 hover:text-on-surface transition-colors"
            >
              <span>{group.icon}</span>
              <span>{group.label}</span>
              <span className="ml-auto flex items-center gap-1">
                <span className="text-[10px] font-normal tabular-nums">{group.items.length}</span>
                <svg
                  className={`w-3 h-3 transition-transform duration-200 ${collapsedSections.has(group.type) ? '-rotate-90' : ''}`}
                  xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor"
                  aria-hidden="true"
                >
                  <path fillRule="evenodd" d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z" clipRule="evenodd" />
                </svg>
              </span>
            </button>
            <div className={`grid transition-[grid-template-rows] duration-200 ease-in-out ${
              collapsedSections.has(group.type) ? 'grid-rows-[0fr]' : 'grid-rows-[1fr]'
            }`}>
              <div className="overflow-hidden">
                {group.items.map(t => (
                  <ThingCard
                    key={t.id}
                    thing={t}
                    onComplete={group.type === 'task' ? handleTaskComplete : undefined}
                  />
                ))}
                {quickAddSection === group.type ? (
                  <form
                    className="px-4 pb-2"
                    onSubmit={e => { e.preventDefault(); handleQuickAddSubmit(group.type) }}
                  >
                    <input
                      autoFocus
                      type="text"
                      placeholder={`Add ${singularize(group.label)}…`}
                      value={quickAddTitle}
                      onChange={e => setQuickAddTitle(e.target.value)}
                      onKeyDown={e => { if (e.key === 'Escape') closeQuickAdd() }}
                      disabled={quickAddSaving}
                      className="w-full text-xs bg-surface-container-high rounded px-2 py-1.5 text-on-surface placeholder-on-surface-variant/60 outline-none border border-on-surface-variant/20 focus:border-primary"
                    />
                    {group.type === 'task' && (
                      <>
                        <input
                          type="date"
                          value={quickAddCheckinDate}
                          onChange={e => setQuickAddCheckinDate(e.target.value)}
                          disabled={quickAddSaving}
                          className="w-full text-xs bg-surface-container-high rounded px-2 py-1.5 text-on-surface placeholder-on-surface-variant/60 outline-none border border-on-surface-variant/20 focus:border-primary mt-1"
                        />
                        <select
                          value={quickAddParentId}
                          onChange={e => setQuickAddParentId(e.target.value)}
                          disabled={quickAddSaving}
                          className="w-full text-xs bg-surface-container-high rounded px-2 py-1.5 text-on-surface outline-none border border-on-surface-variant/20 focus:border-primary mt-1"
                        >
                          <option value="">No parent project</option>
                          {things.filter(t => t.type_hint === 'project' && t.active).map(p => (
                            <option key={p.id} value={p.id}>{p.title}</option>
                          ))}
                        </select>
                      </>
                    )}
                    {quickAddError && <p className="text-[10px] text-ideas mt-1">{quickAddError}</p>}
                    <div className="flex justify-end mt-1">
                      <button
                        type="submit"
                        disabled={!quickAddTitle.trim() || quickAddSaving}
                        className="text-xs font-medium px-3 py-1 rounded-lg bg-primary text-on-primary disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        {quickAddSaving ? 'Saving…' : 'Add'}
                      </button>
                    </div>
                  </form>
                ) : (
                  <button
                    onClick={() => { closeQuickAdd(); setQuickAddSection(group.type); setQuickAddError(null) }}
                    className="mx-4 mb-1 text-[11px] text-on-surface-variant/60 hover:text-primary transition-colors flex items-center gap-0.5"
                  >
                    <span>+</span>
                    <span>Add {singularize(group.label)}</span>
                  </button>
                )}
                {group.type === 'task' && completedTasks.length > 0 && (
                  <div className="mt-3 opacity-40">
                    {completedTasks.map(t => (
                      <div key={t.id} className="px-5 py-1.5 flex items-center gap-2">
                        <div className="shrink-0 w-4 h-4 rounded border border-on-surface-variant/30 bg-primary/60 flex items-center justify-center">
                          <svg className="w-2.5 h-2.5 text-on-primary" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
                            <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                          </svg>
                        </div>
                        <span className="text-sm line-through text-on-surface-variant truncate flex-1">{t.title}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </section>
        ))}

        {/* Preferences — learned behavioral patterns */}
        {preferenceThings.length > 0 && (
          <section className="py-2">
            <h2 className="px-4 pb-1 text-label font-semibold text-on-surface-variant flex items-center gap-1.5">
              <span>⚙️</span>
              <span>Preferences</span>
              <span className="ml-auto text-[10px] font-normal tabular-nums text-on-surface-variant">{preferenceThings.length}</span>
            </h2>
            {preferenceThings.map(t => <PreferenceCard key={t.id} thing={t} />)}
          </section>
        )}

            {/* Upcoming Check-ins */}
            {upcoming.length > 0 && (
              <section className="py-2">
                <h2 className="px-4 pb-1 text-label font-semibold text-on-surface-variant">
                  Upcoming Check-ins
                </h2>
                {upcoming.map(t => <ThingCard key={t.id} thing={t} />)}
              </section>
            )}

            {/* Gmail */}
            <GmailPanel />

            {!loading && things.length === 0 && (
              <div className="px-6 py-8 flex flex-col items-center gap-4 text-center">
                <svg className="w-16 h-16 text-surface-container-high" viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                  <circle cx="12" cy="32" r="8" stroke="currentColor" strokeWidth="2" fill="none"/>
                  <circle cx="52" cy="16" r="7" stroke="currentColor" strokeWidth="2" fill="none"/>
                  <circle cx="52" cy="48" r="7" stroke="currentColor" strokeWidth="2" fill="none"/>
                  <line x1="20" y1="30" x2="45" y2="19" stroke="currentColor" strokeWidth="1.5" strokeDasharray="3 2"/>
                  <line x1="20" y1="34" x2="45" y2="45" stroke="currentColor" strokeWidth="1.5" strokeDasharray="3 2"/>
                </svg>
                <div>
                  <p className="text-sm font-medium text-on-surface-variant">Things you mention in chat appear here</p>
                  <p className="text-xs text-on-surface-variant/70 mt-1">Try telling me about a project, goal, or task you're working on.</p>
                </div>
              </div>
            )}
          </>
        )}
        </div>

        <div className="hidden md:block shrink-0 p-3">
          <button
            onClick={openQuickAdd}
            className="w-full bg-primary-container text-on-primary-container py-3 rounded-xl font-semibold flex items-center justify-center gap-2 hover:opacity-90 transition-opacity"
          >
            <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
            </svg>
            New Thought
          </button>
        </div>
      </aside>
        {/* Drag handle — desktop only, outside aside to avoid overflow clipping */}
        <div
          onPointerDown={handleDragStart}
          className="hidden md:flex absolute top-0 right-0 w-2 h-full cursor-col-resize group/handle z-10 items-center justify-center"
        >
          <div className="w-1 h-full bg-on-surface-variant/20 group-hover/handle:bg-primary transition-colors" />
          {/* Grip indicator — three dots centered vertically */}
          <div className="absolute flex flex-col gap-1 pointer-events-none">
            <div className="w-1 h-1 rounded-full bg-on-surface-variant/30 group-hover/handle:bg-primary/60 transition-colors" />
            <div className="w-1 h-1 rounded-full bg-on-surface-variant/30 group-hover/handle:bg-primary/60 transition-colors" />
            <div className="w-1 h-1 rounded-full bg-on-surface-variant/30 group-hover/handle:bg-primary/60 transition-colors" />
          </div>
        </div>
      </div>
    </>
  )
}
