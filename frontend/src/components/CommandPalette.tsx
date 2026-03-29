import { useEffect, useRef, useState, useCallback, useMemo } from 'react'
import { useShallow } from 'zustand/react/shallow'
import { useStore } from '../store'
import type { Thing } from '../store'

// ── Types ──────────────────────────────────────────────────────────────────

type ResultItem =
  | { kind: 'thing'; thing: Thing }
  | { kind: 'action'; id: string; label: string; shortcut?: string; run: () => void }

// ── Helpers ────────────────────────────────────────────────────────────────

function thingIcon(typeHint: string | null): string {
  switch (typeHint) {
    case 'task':    return '✓'
    case 'project': return '📁'
    case 'note':    return '📝'
    case 'event':   return '📅'
    case 'contact': return '👤'
    default:        return '◇'
  }
}

/** Simple fuzzy match: all chars of `needle` appear in order in `haystack`. */
function fuzzyMatch(haystack: string, needle: string): boolean {
  const h = haystack.toLowerCase()
  const n = needle.toLowerCase()
  let hi = 0
  for (let ni = 0; ni < n.length; ni++) {
    const ch = n.charAt(ni)
    hi = h.indexOf(ch, hi)
    if (hi === -1) return false
    hi++
  }
  return true
}

// Highlight matching characters in text
function HighlightedText({ text, query }: { text: string; query: string }) {
  if (!query) return <span>{text}</span>

  const lText = text.toLowerCase()
  const lQuery = query.toLowerCase()

  // Find positions of matching characters
  const positions = new Set<number>()
  let hi = 0
  for (let ni = 0; ni < lQuery.length; ni++) {
    const pos = lText.indexOf(lQuery.charAt(ni), hi)
    if (pos === -1) break
    positions.add(pos)
    hi = pos + 1
  }

  if (positions.size === 0) return <span>{text}</span>

  return (
    <span>
      {text.split('').map((ch, i) =>
        positions.has(i)
          ? <strong key={i} className="text-indigo-600 dark:text-indigo-400 font-semibold">{ch}</strong>
          : <span key={i}>{ch}</span>
      )}
    </span>
  )
}

// ── Main Component ─────────────────────────────────────────────────────────

export function CommandPalette() {
  const {
    commandPaletteOpen,
    closeCommandPalette,
    things,
    searchResults,
    searchLoading,
    searchThings,
    clearSearch,
    openThingDetail,
    setMainView,
    openSettings,
    openFeedback,
  } = useStore(useShallow(s => ({
    commandPaletteOpen: s.commandPaletteOpen,
    closeCommandPalette: s.closeCommandPalette,
    things: s.things,
    searchResults: s.searchResults,
    searchLoading: s.searchLoading,
    searchThings: s.searchThings,
    clearSearch: s.clearSearch,
    openThingDetail: s.openThingDetail,
    setMainView: s.setMainView,
    openSettings: s.openSettings,
    openFeedback: s.openFeedback,
  })))

  const [query, setQuery] = useState('')
  const [selectedIndex, setSelectedIndex] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)
  const listRef = useRef<HTMLDivElement>(null)

  // Parse prefix filters from query
  const { prefix, rawQuery } = useMemo(() => {
    if (query.startsWith('>')) return { prefix: 'action', rawQuery: query.slice(1).trim() }
    const typeMatch = query.match(/^#(\w+)\s*(.*)$/)
    if (typeMatch) return { prefix: (typeMatch[1] ?? '').toLowerCase(), rawQuery: (typeMatch[2] ?? '').trim() }
    return { prefix: null, rawQuery: query.trim() }
  }, [query])

  // Debounced vector search
  useEffect(() => {
    if (prefix === 'action') {
      clearSearch()
      return
    }
    if (rawQuery.length >= 2) {
      const timer = setTimeout(() => searchThings(rawQuery), 200)
      return () => clearTimeout(timer)
    } else {
      clearSearch()
    }
  }, [rawQuery, prefix, searchThings, clearSearch])

  // Quick actions (always available, filterable by rawQuery)
  const quickActions = useMemo((): ResultItem[] => {
    const actions: ResultItem[] = [
      {
        kind: 'action',
        id: 'open-settings',
        label: 'Open Settings',
        shortcut: '⌘,',
        run: () => { openSettings(); closeCommandPalette() },
      },
      {
        kind: 'action',
        id: 'view-list',
        label: 'Switch to List View',
        run: () => { setMainView('list'); closeCommandPalette() },
      },
      {
        kind: 'action',
        id: 'view-graph',
        label: 'Switch to Graph View',
        run: () => { setMainView('graph'); closeCommandPalette() },
      },
      {
        kind: 'action',
        id: 'send-feedback',
        label: 'Send Feedback',
        run: () => { openFeedback(); closeCommandPalette() },
      },
    ]
    if (!rawQuery) return actions
    return actions.filter(a => a.kind === 'action' && fuzzyMatch(a.label, rawQuery))
  }, [rawQuery, openSettings, closeCommandPalette, setMainView, openFeedback])

  // Build result list based on current mode
  const results = useMemo((): { things: ResultItem[]; actions: ResultItem[]; quickActions: ResultItem[] } => {
    // Action-only mode (> prefix)
    if (prefix === 'action') {
      const filtered = quickActions.filter(a => !rawQuery || fuzzyMatch((a as { kind: 'action'; label: string }).label, rawQuery))
      return { things: [], actions: [], quickActions: filtered }
    }

    // Things section: use vector search results if query active, else recent things
    let thingItems: ResultItem[]
    if (rawQuery.length >= 2 && searchResults.length > 0) {
      // Filter by type prefix if set
      const filtered = prefix
        ? searchResults.filter(t => t.type_hint?.toLowerCase() === prefix)
        : searchResults
      thingItems = filtered.slice(0, 8).map(t => ({ kind: 'thing', thing: t }))
    } else if (!rawQuery) {
      // Empty state: recent items sorted by last_referenced or updated_at
      const recent = [...things]
        .sort((a, b) => {
          const ta = a.last_referenced || a.updated_at
          const tb = b.last_referenced || b.updated_at
          return tb.localeCompare(ta)
        })
        .slice(0, 5)
      thingItems = recent.map(t => ({ kind: 'thing', thing: t }))
    } else {
      // Short query: local fuzzy filter on titles
      const filtered = things.filter(t =>
        (!prefix || t.type_hint?.toLowerCase() === prefix) &&
        fuzzyMatch(t.title, rawQuery)
      ).slice(0, 8)
      thingItems = filtered.map(t => ({ kind: 'thing', thing: t }))
    }

    // Contextual actions for top thing result
    const contextActions: ResultItem[] = []
    const firstItem = thingItems[0]
    if (firstItem && firstItem.kind === 'thing') {
      const topThing = (firstItem as { kind: 'thing'; thing: Thing }).thing
      contextActions.push({
        kind: 'action',
        id: `chat-${topThing.id}`,
        label: `Chat about "${topThing.title}"`,
        run: () => {
          openThingDetail(topThing.id)
          closeCommandPalette()
        },
      })
    }

    return { things: thingItems, actions: contextActions, quickActions }
  }, [prefix, rawQuery, searchResults, things, quickActions, openThingDetail, closeCommandPalette])

  // Flat list for keyboard navigation
  const flatResults = useMemo((): ResultItem[] => [
    ...results.things,
    ...results.actions,
    ...results.quickActions,
  ], [results])

  // Reset selection when results change
  useEffect(() => {
    setSelectedIndex(0)
  }, [query])

  // Focus input when opened
  useEffect(() => {
    if (commandPaletteOpen) {
      setQuery('')
      clearSearch()
      setTimeout(() => inputRef.current?.focus(), 50)
    }
  }, [commandPaletteOpen, clearSearch])

  // Scroll selected item into view
  useEffect(() => {
    const el = listRef.current?.querySelector(`[data-idx="${selectedIndex}"]`)
    el?.scrollIntoView({ block: 'nearest' })
  }, [selectedIndex])

  const handleSelect = useCallback((item: ResultItem) => {
    if (item.kind === 'thing') {
      openThingDetail(item.thing.id)
      closeCommandPalette()
    } else {
      item.run()
    }
  }, [openThingDetail, closeCommandPalette])

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setSelectedIndex(i => Math.min(i + 1, flatResults.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setSelectedIndex(i => Math.max(i - 1, 0))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      if (flatResults[selectedIndex]) handleSelect(flatResults[selectedIndex])
    } else if (e.key === 'Escape') {
      closeCommandPalette()
    }
  }, [flatResults, selectedIndex, handleSelect, closeCommandPalette])

  if (!commandPaletteOpen) return null

  const isEmpty = flatResults.length === 0

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center pt-[20vh] px-4"
      onClick={closeCommandPalette}
      aria-modal="true"
      role="dialog"
      aria-label="Command palette"
    >
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/40 dark:bg-black/60" />

      {/* Palette */}
      <div
        className="relative w-full max-w-xl bg-white dark:bg-gray-900 rounded-xl shadow-2xl border border-gray-200 dark:border-gray-700 overflow-hidden"
        onClick={e => e.stopPropagation()}
      >
        {/* Search input */}
        <div className="flex items-center gap-2 px-4 py-3 border-b border-gray-100 dark:border-gray-800">
          {searchLoading
            ? <div className="h-4 w-4 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin flex-shrink-0" />
            : <svg className="w-4 h-4 text-gray-400 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-4.35-4.35m0 0A7.5 7.5 0 1 0 6.5 6.5a7.5 7.5 0 0 0 10.6 10.6z" />
              </svg>
          }
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={e => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Search Things, run actions… (> for actions, #type to filter)"
            className="flex-1 bg-transparent text-sm text-gray-900 dark:text-gray-100 placeholder-gray-400 outline-none"
            aria-label="Command palette search"
          />
          {query && (
            <button
              onClick={() => setQuery('')}
              className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 text-lg leading-none"
              aria-label="Clear input"
            >
              ×
            </button>
          )}
        </div>

        {/* Results */}
        <div ref={listRef} className="max-h-96 overflow-y-auto py-1">
          {isEmpty && !searchLoading && (
            <div className="px-4 py-8 text-center text-sm text-gray-400 dark:text-gray-500">
              {rawQuery ? 'No results found' : 'No Things yet'}
            </div>
          )}

          {/* Things section */}
          {results.things.length > 0 && (
            <Section label={rawQuery ? 'Things' : 'Recent'}>
              {results.things.map((item, i) => {
                const thing = (item as { kind: 'thing'; thing: Thing }).thing
                const flatIdx = i
                return (
                  <ResultRow
                    key={thing.id}
                    idx={flatIdx}
                    selected={selectedIndex === flatIdx}
                    onSelect={() => handleSelect(item)}
                    onHover={() => setSelectedIndex(flatIdx)}
                    icon={thingIcon(thing.type_hint)}
                  >
                    <span className="flex-1 truncate text-sm text-gray-900 dark:text-gray-100">
                      <HighlightedText text={thing.title} query={rawQuery} />
                    </span>
                    {thing.type_hint && (
                      <span className="ml-2 text-xs text-gray-400 dark:text-gray-500 flex-shrink-0">
                        {thing.type_hint}
                      </span>
                    )}
                  </ResultRow>
                )
              })}
            </Section>
          )}

          {/* Contextual actions */}
          {results.actions.length > 0 && (
            <Section label="Actions">
              {results.actions.map((item, i) => {
                const flatIdx = results.things.length + i
                const action = item as { kind: 'action'; id: string; label: string; shortcut?: string }
                return (
                  <ResultRow
                    key={action.id}
                    idx={flatIdx}
                    selected={selectedIndex === flatIdx}
                    onSelect={() => handleSelect(item)}
                    onHover={() => setSelectedIndex(flatIdx)}
                    icon="💬"
                  >
                    <span className="flex-1 truncate text-sm text-gray-900 dark:text-gray-100">
                      {action.label}
                    </span>
                    {action.shortcut && (
                      <kbd className="ml-2 text-xs text-gray-400 dark:text-gray-500 bg-gray-100 dark:bg-gray-800 rounded px-1 py-0.5 flex-shrink-0">
                        {action.shortcut}
                      </kbd>
                    )}
                  </ResultRow>
                )
              })}
            </Section>
          )}

          {/* Quick actions */}
          {results.quickActions.length > 0 && (
            <Section label="Quick Actions">
              {results.quickActions.map((item, i) => {
                const flatIdx = results.things.length + results.actions.length + i
                const action = item as { kind: 'action'; id: string; label: string; shortcut?: string }
                return (
                  <ResultRow
                    key={action.id}
                    idx={flatIdx}
                    selected={selectedIndex === flatIdx}
                    onSelect={() => handleSelect(item)}
                    onHover={() => setSelectedIndex(flatIdx)}
                    icon="⚡"
                  >
                    <span className="flex-1 truncate text-sm text-gray-900 dark:text-gray-100">
                      {action.label}
                    </span>
                    {action.shortcut && (
                      <kbd className="ml-2 text-xs text-gray-400 dark:text-gray-500 bg-gray-100 dark:bg-gray-800 rounded px-1 py-0.5 flex-shrink-0">
                        {action.shortcut}
                      </kbd>
                    )}
                  </ResultRow>
                )
              })}
            </Section>
          )}
        </div>

        {/* Footer hints */}
        <div className="px-4 py-2 border-t border-gray-100 dark:border-gray-800 flex items-center gap-3 text-xs text-gray-400 dark:text-gray-500">
          <span><kbd className="font-mono">↑↓</kbd> navigate</span>
          <span><kbd className="font-mono">↵</kbd> select</span>
          <span><kbd className="font-mono">Esc</kbd> close</span>
          <span className="ml-auto"><kbd className="font-mono">&gt;</kbd> actions · <kbd className="font-mono">#type</kbd> filter</span>
        </div>
      </div>
    </div>
  )
}

// ── Sub-components ─────────────────────────────────────────────────────────

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="px-4 py-1.5 text-xs font-semibold text-gray-400 dark:text-gray-500 uppercase tracking-wide">
        {label}
      </div>
      {children}
    </div>
  )
}

function ResultRow({
  idx,
  selected,
  onSelect,
  onHover,
  icon,
  children,
}: {
  idx: number
  selected: boolean
  onSelect: () => void
  onHover: () => void
  icon: string
  children: React.ReactNode
}) {
  return (
    <div
      data-idx={idx}
      className={`flex items-center gap-3 px-4 py-2 cursor-pointer transition-colors ${
        selected
          ? 'bg-indigo-50 dark:bg-indigo-900/30'
          : 'hover:bg-gray-50 dark:hover:bg-gray-800/50'
      }`}
      onClick={onSelect}
      onMouseEnter={onHover}
      role="option"
      aria-selected={selected}
    >
      <span className="w-5 text-center text-base flex-shrink-0 select-none">{icon}</span>
      {children}
    </div>
  )
}
