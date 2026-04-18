import { useEffect, useRef, useState } from 'react'
import { useStore, type Thing } from '../store'
import { typeIcon } from '../utils'

/** Returns the platform-appropriate modifier label. */
function mod(): string {
  return typeof navigator !== 'undefined' && /Mac|iPhone|iPad|iPod/i.test(navigator.platform)
    ? '⌘'
    : 'Ctrl'
}

interface Command {
  id: string
  label: string
  description?: string
  shortcut?: string
  action: () => void
}

interface ParsedQuery {
  thingQuery: string
  actionsOnly: boolean
  typeFilter: string | null
}

function parseQuery(raw: string): ParsedQuery {
  const q = raw.trim()
  if (q.startsWith('>')) {
    return { thingQuery: q.slice(1).trim(), actionsOnly: true, typeFilter: null }
  }
  const typeMatch = q.match(/^#(\w+)\s*(.*)$/)
  if (typeMatch && typeMatch[1]) {
    return { thingQuery: (typeMatch[2] ?? '').trim(), actionsOnly: false, typeFilter: typeMatch[1].toLowerCase() }
  }
  return { thingQuery: q, actionsOnly: false, typeFilter: null }
}

type ResultItem =
  | { kind: 'thing'; thing: Thing }
  | { kind: 'command'; command: Command }

export function CommandPalette() {
  const closeCommandPalette = useStore(s => s.closeCommandPalette)
  const openQuickAdd = useStore(s => s.openQuickAdd)
  const setSidebarOpen = useStore(s => s.setSidebarOpen)
  const sidebarOpen = useStore(s => s.sidebarOpen)
  const setChatMode = useStore(s => s.setChatMode)
  const chatMode = useStore(s => s.chatMode)
  const focusChatInput = useStore(s => s.focusChatInput)
  const openSettings = useStore(s => s.openSettings)
  const searchThings = useStore(s => s.searchThings)
  const clearSearch = useStore(s => s.clearSearch)
  const searchResults = useStore(s => s.searchResults)
  const searchLoading = useStore(s => s.searchLoading)
  const things = useStore(s => s.things)
  const thingTypes = useStore(s => s.thingTypes)
  const openThingDetail = useStore(s => s.openThingDetail)
  const mainView = useStore(s => s.mainView)
  const setMainView = useStore(s => s.setMainView)

  const [query, setQuery] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)
  const debounceRef = useRef<ReturnType<typeof setTimeout>>(null)
  const m = mod()

  const commands: Command[] = [
    {
      id: 'new-thing',
      label: 'New Thing',
      description: 'Quick-add a new Thing',
      shortcut: `${m}N`,
      action: () => {
        closeCommandPalette()
        openQuickAdd()
      },
    },
    {
      id: 'toggle-sidebar',
      label: sidebarOpen ? 'Hide Sidebar' : 'Show Sidebar',
      description: 'Toggle the sidebar',
      shortcut: `${m}B`,
      action: () => {
        closeCommandPalette()
        setSidebarOpen(!sidebarOpen)
      },
    },
    {
      id: 'toggle-briefing',
      label: chatMode === 'planning' ? 'Switch to Normal Chat' : 'Switch to Planning Mode',
      description: 'Toggle briefing / planning chat mode',
      shortcut: `${m}.`,
      action: () => {
        closeCommandPalette()
        setChatMode(chatMode === 'normal' ? 'planning' : 'normal')
      },
    },
    {
      id: 'toggle-calendar',
      label: mainView === 'calendar' ? 'Switch to List View' : 'Switch to Calendar View',
      description: 'Toggle calendar view',
      action: () => {
        closeCommandPalette()
        setMainView(mainView === 'calendar' ? 'list' : 'calendar')
      },
    },
    {
      id: 'focus-chat',
      label: 'Focus Chat Input',
      description: 'Jump to the chat input',
      shortcut: '/',
      action: () => {
        closeCommandPalette()
        focusChatInput()
      },
    },
    {
      id: 'settings',
      label: 'Open Settings',
      description: 'View and edit your preferences',
      action: () => {
        closeCommandPalette()
        openSettings()
      },
    },
  ]

  const { thingQuery, actionsOnly, typeFilter } = parseQuery(query)

  // Recent items for empty state
  const recentThings = !query.trim()
    ? things
        .filter(t => t.active && t.type_hint !== 'preference')
        .sort((a, b) => b.updated_at.localeCompare(a.updated_at))
        .slice(0, 5)
    : []

  // Filter search results by type if needed
  const filteredSearchResults = typeFilter
    ? searchResults.filter(t => t.type_hint === typeFilter)
    : searchResults

  // Things group: either recent (empty query), type-filtered from cache, or search results
  const thingItems: Thing[] = actionsOnly
    ? []
    : query.trim()
      ? typeFilter && !thingQuery
        ? things.filter(t => t.active && t.type_hint === typeFilter).slice(0, 10)
        : filteredSearchResults.slice(0, 10)
      : recentThings

  // Actions group: existing commands filtered by thingQuery
  const actionItems: Command[] = typeFilter
    ? []
    : commands.filter(c =>
        !thingQuery ||
        c.label.toLowerCase().includes(thingQuery.toLowerCase()) ||
        (c.description ?? '').toLowerCase().includes(thingQuery.toLowerCase())
      )

  // Build flat list for keyboard nav
  const flatItems: ResultItem[] = [
    ...thingItems.map(thing => ({ kind: 'thing' as const, thing })),
    ...actionItems.map(command => ({ kind: 'command' as const, command })),
  ]

  const [activeIdx, setActiveIdx] = useState(0)

  // Debounced search
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    if (!thingQuery && !typeFilter) {
      clearSearch()
      return
    }
    if (actionsOnly) return
    // When only a typeFilter is set (no text), thingItems handles filtering client-side
    if (!thingQuery) return
    debounceRef.current = setTimeout(() => {
      searchThings(thingQuery)
    }, 250)
  }, [thingQuery, typeFilter, actionsOnly, searchThings, clearSearch])

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
      clearSearch()
    }
  }, [clearSearch])

  // Focus input on open
  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActiveIdx(i => Math.min(i + 1, flatItems.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActiveIdx(i => Math.max(i - 1, 0))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      const item = flatItems[activeIdx]
      if (item?.kind === 'thing') {
        closeCommandPalette()
        openThingDetail(item.thing.id)
      } else if (item?.kind === 'command') {
        item.command.action()
      }
    } else if (e.key === 'Escape') {
      e.preventDefault()
      closeCommandPalette()
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center pt-[20vh] px-4"
      onMouseDown={e => {
        if (e.target === e.currentTarget) closeCommandPalette()
      }}
    >
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/40 dark:bg-black/60" aria-hidden="true" />

      {/* Panel */}
      <div className="relative w-full max-w-lg bg-white dark:bg-gray-900 rounded-xl shadow-2xl border border-gray-200 dark:border-gray-700 overflow-hidden">
        {/* Search input */}
        <div className="flex items-center gap-2 px-4 py-3 border-b border-gray-200 dark:border-gray-700">
          <svg className="h-4 w-4 text-gray-400 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="m21 21-5.197-5.197m0 0A7.5 7.5 0 1 0 5.196 5.196a7.5 7.5 0 0 0 10.607 10.607Z" />
          </svg>
          <input
            ref={inputRef}
            type="text"
            placeholder="Search everything…"
            value={query}
            onChange={e => { setQuery(e.target.value); setActiveIdx(0) }}
            onKeyDown={handleKeyDown}
            className="flex-1 bg-transparent text-sm text-gray-900 dark:text-gray-100 placeholder-gray-400 dark:placeholder-gray-500 outline-none"
          />
          <kbd className="text-xs text-gray-400 dark:text-gray-500 border border-gray-200 dark:border-gray-700 rounded px-1.5 py-0.5">Esc</kbd>
        </div>

        {/* Result list */}
        <ul className="max-h-72 overflow-y-auto py-1.5" role="listbox">
          {/* Things group */}
          {thingItems.length > 0 && (
            <>
              <li className="px-4 py-1 text-xs font-semibold text-gray-400 dark:text-gray-500 uppercase tracking-wide select-none">
                {!query.trim() ? 'Recent' : 'Things'}
              </li>
              {thingItems.map((thing, idx) => (
                  <li
                    key={thing.id}
                    role="option"
                    aria-selected={idx === activeIdx}
                    className={`flex items-center gap-3 px-4 py-2.5 cursor-pointer text-sm transition-colors ${
                      idx === activeIdx
                        ? 'bg-indigo-50 dark:bg-indigo-950 text-indigo-700 dark:text-indigo-300'
                        : 'text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800'
                    }`}
                    onMouseEnter={() => setActiveIdx(idx)}
                    onMouseDown={e => {
                      e.preventDefault()
                      closeCommandPalette()
                      openThingDetail(thing.id)
                    }}
                  >
                    <span className="text-base shrink-0">{typeIcon(thing.type_hint, thingTypes)}</span>
                    <div className="min-w-0">
                      <span className="font-medium truncate block">{thing.title}</span>
                      {thing.type_hint && (
                        <span className="text-xs text-gray-400 dark:text-gray-500">{thing.type_hint}</span>
                      )}
                    </div>
                  </li>
              ))}
            </>
          )}

          {/* Actions group */}
          {actionItems.length > 0 && (
            <>
              <li className="px-4 py-1 text-xs font-semibold text-gray-400 dark:text-gray-500 uppercase tracking-wide select-none">
                {actionsOnly ? 'Actions' : 'Quick Actions'}
              </li>
              {actionItems.map((cmd, idx) => {
                const gIdx = thingItems.length + idx
                return (
                  <li
                    key={cmd.id}
                    role="option"
                    aria-selected={gIdx === activeIdx}
                    className={`flex items-center justify-between gap-3 px-4 py-2.5 cursor-pointer text-sm transition-colors ${
                      gIdx === activeIdx
                        ? 'bg-indigo-50 dark:bg-indigo-950 text-indigo-700 dark:text-indigo-300'
                        : 'text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800'
                    }`}
                    onMouseEnter={() => setActiveIdx(gIdx)}
                    onMouseDown={e => { e.preventDefault(); cmd.action() }}
                  >
                    <div>
                      <span className="font-medium">{cmd.label}</span>
                      {cmd.description && (
                        <span className="ml-2 text-xs text-gray-400 dark:text-gray-500">{cmd.description}</span>
                      )}
                    </div>
                    {cmd.shortcut && (
                      <kbd className="shrink-0 text-xs text-gray-400 dark:text-gray-500 border border-gray-200 dark:border-gray-700 rounded px-1.5 py-0.5 font-mono">
                        {cmd.shortcut}
                      </kbd>
                    )}
                  </li>
                )
              })}
            </>
          )}

          {/* Empty state */}
          {flatItems.length === 0 && !searchLoading && (
            <li className="px-4 py-3 text-sm text-gray-400 dark:text-gray-500">No results found</li>
          )}
          {searchLoading && (
            <li className="px-4 py-3 text-sm text-gray-400 dark:text-gray-500">Searching…</li>
          )}
        </ul>

        {/* Footer hint */}
        <div className="border-t border-gray-100 dark:border-gray-800 px-4 py-2 flex items-center gap-3 text-xs text-gray-400 dark:text-gray-500">
          <span><kbd className="font-mono">↑↓</kbd> navigate</span>
          <span><kbd className="font-mono">↵</kbd> select</span>
          <span><kbd className="font-mono">Esc</kbd> close</span>
          <span className="ml-auto"><kbd className="font-mono">&gt;</kbd> actions <kbd className="font-mono">#type</kbd> filter</span>
        </div>
      </div>
    </div>
  )
}
