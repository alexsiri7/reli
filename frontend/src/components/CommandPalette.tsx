import { useState, useEffect, useRef, useCallback } from 'react'
import { useShallow } from 'zustand/react/shallow'
import { useStore } from '../store'
import { typeIcon } from '../utils'

const isMac = typeof navigator !== 'undefined' && /Mac|iPhone|iPad|iPod/.test(navigator.platform)
const MOD = isMac ? '⌘' : 'Ctrl'

interface Action {
  id: string
  label: string
  shortcut?: string
  icon: string
  run: () => void
}

function fuzzyMatch(query: string, text: string): boolean {
  if (!query) return true
  const q = query.toLowerCase()
  const t = text.toLowerCase()
  if (t.includes(q)) return true
  // character-by-character fuzzy
  let qi = 0
  for (let i = 0; i < t.length && qi < q.length; i++) {
    if (t[i] === q[qi]) qi++
  }
  return qi === q.length
}

function fuzzyScore(query: string, text: string): number {
  const q = query.toLowerCase()
  const t = text.toLowerCase()
  if (t.startsWith(q)) return 3
  if (t.includes(q)) return 2
  return 1
}

export function CommandPalette() {
  const {
    commandPaletteOpen,
    closeCommandPalette,
    things,
    openThingDetail,
    openSettings,
    openFeedback,
    setMainView,
  } = useStore(
    useShallow(s => ({
      commandPaletteOpen: s.commandPaletteOpen,
      closeCommandPalette: s.closeCommandPalette,
      things: s.things,
      openThingDetail: s.openThingDetail,
      openSettings: s.openSettings,
      openFeedback: s.openFeedback,
      setMainView: s.setMainView,
    }))
  )

  const [query, setQuery] = useState('')
  const [selectedIndex, setSelectedIndex] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)
  const listRef = useRef<HTMLDivElement>(null)

  // Reset on open
  useEffect(() => {
    if (commandPaletteOpen) {
      setQuery('')
      setSelectedIndex(0)
      setTimeout(() => inputRef.current?.focus(), 0)
    }
  }, [commandPaletteOpen])

  const close = useCallback(() => {
    closeCommandPalette()
  }, [closeCommandPalette])

  // Available actions
  const actions: Action[] = [
    {
      id: 'list',
      label: 'Switch to List view',
      icon: '📋',
      shortcut: undefined,
      run: () => { setMainView('list'); close() },
    },
    {
      id: 'graph',
      label: 'Switch to Graph view',
      icon: '🕸️',
      run: () => { setMainView('graph'); close() },
    },
    {
      id: 'calendar',
      label: 'Switch to Calendar view',
      icon: '📅',
      run: () => { setMainView('calendar'); close() },
    },
    {
      id: 'settings',
      label: 'Open Settings',
      icon: '⚙️',
      run: () => { openSettings(); close() },
    },
    {
      id: 'feedback',
      label: 'Send Feedback',
      icon: '💬',
      run: () => { openFeedback(); close() },
    },
    {
      id: 'new-thing',
      label: 'New Thing…',
      icon: '✨',
      shortcut: `${MOD}+N`,
      run: () => {
        close()
        window.dispatchEvent(new CustomEvent('reli:focus-chat', { detail: { prefill: 'Add a new ' } }))
      },
    },
    {
      id: 'toggle-sidebar',
      label: 'Toggle Sidebar',
      icon: '◀',
      shortcut: `${MOD}+B`,
      run: () => {
        window.dispatchEvent(new CustomEvent('reli:toggle-sidebar'))
        close()
      },
    },
    {
      id: 'focus-chat',
      label: 'Focus Chat Input',
      icon: '💬',
      shortcut: '/',
      run: () => {
        close()
        window.dispatchEvent(new CustomEvent('reli:focus-chat'))
      },
    },
  ]

  // Parse prefix filters
  const isActionFilter = query.startsWith('>')
  const typeFilter = query.match(/^#(\w+)/)
  const cleanQuery = isActionFilter
    ? query.slice(1).trim()
    : typeFilter
    ? query.slice(typeFilter[0].length).trim()
    : query

  // Filter and score things
  const thingResults = isActionFilter
    ? []
    : things
        .filter(t => {
          if (typeFilter && typeFilter[1] && t.type_hint?.toLowerCase() !== typeFilter[1].toLowerCase()) return false
          return fuzzyMatch(cleanQuery, t.title)
        })
        .map(t => ({ ...t, score: fuzzyScore(cleanQuery, t.title) }))
        .sort((a, b) => b.score - a.score || a.title.localeCompare(b.title))
        .slice(0, 8)

  // Filter actions
  const actionResults = actions.filter(a =>
    !cleanQuery || fuzzyMatch(cleanQuery, a.label)
  )

  // Recent things when empty (no query)
  const recentThings = !query
    ? [...things]
        .filter(t => t.last_referenced)
        .sort((a, b) =>
          new Date(b.last_referenced!).getTime() - new Date(a.last_referenced!).getTime()
        )
        .slice(0, 5)
    : []

  const displayThings = query ? thingResults : recentThings
  const displayActions = query ? (isActionFilter ? actionResults : actionResults.slice(0, 3)) : actionResults.slice(0, 3)

  // Flat list for keyboard navigation
  interface FlatItem {
    kind: 'thing' | 'action'
    index: number
    run: () => void
  }
  const flatItems: FlatItem[] = [
    ...displayThings.map((t, i) => ({
      kind: 'thing' as const,
      index: i,
      run: () => { openThingDetail(t.id); close() },
    })),
    ...displayActions.map((a, i) => ({
      kind: 'action' as const,
      index: displayThings.length + i,
      run: a.run,
    })),
  ]

  // Clamp selectedIndex
  const clampedIndex = Math.min(selectedIndex, flatItems.length - 1)

  // Scroll selected item into view
  useEffect(() => {
    const el = listRef.current?.querySelector(`[data-idx="${clampedIndex}"]`)
    el?.scrollIntoView({ block: 'nearest' })
  }, [clampedIndex])

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') {
      e.preventDefault()
      close()
    } else if (e.key === 'ArrowDown') {
      e.preventDefault()
      setSelectedIndex(i => Math.min(i + 1, flatItems.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setSelectedIndex(i => Math.max(i - 1, 0))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      flatItems[clampedIndex]?.run()
    }
  }

  // Reset selection when results change
  useEffect(() => {
    setSelectedIndex(0)
  }, [query])

  if (!commandPaletteOpen) return null

  return (
    <div
      className="fixed inset-0 z-[200] flex items-start justify-center pt-[15vh] bg-black/40 backdrop-blur-sm"
      onMouseDown={e => { if (e.target === e.currentTarget) close() }}
    >
      <div className="w-full max-w-xl mx-4 bg-white dark:bg-gray-900 rounded-xl shadow-2xl border border-gray-200 dark:border-gray-700 overflow-hidden">
        {/* Search input */}
        <div className="flex items-center gap-2 px-4 py-3 border-b border-gray-200 dark:border-gray-700">
          <svg className="w-4 h-4 text-gray-400 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-4.35-4.35M17 11A6 6 0 1 1 5 11a6 6 0 0 1 12 0Z" />
          </svg>
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={e => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={`Search Things or type > for actions, #type to filter…`}
            className="flex-1 bg-transparent text-sm text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-500 outline-none"
          />
          <kbd className="hidden sm:flex items-center gap-0.5 text-[10px] font-mono text-gray-400 bg-gray-100 dark:bg-gray-800 px-1.5 py-0.5 rounded">
            Esc
          </kbd>
        </div>

        {/* Results */}
        <div ref={listRef} className="max-h-80 overflow-y-auto">
          {/* Things section */}
          {displayThings.length > 0 && (
            <div>
              <div className="px-3 pt-2.5 pb-1 text-[10px] font-semibold uppercase tracking-wider text-gray-400 dark:text-gray-500">
                {query ? 'Things' : 'Recent'}
              </div>
              {displayThings.map((t, i) => {
                const idx = i
                return (
                  <button
                    key={t.id}
                    data-idx={idx}
                    onClick={() => { openThingDetail(t.id); close() }}
                    className={`w-full flex items-center gap-3 px-4 py-2.5 text-left text-sm transition-colors ${
                      clampedIndex === idx
                        ? 'bg-indigo-50 dark:bg-indigo-950/60 text-indigo-700 dark:text-indigo-300'
                        : 'text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800/60'
                    }`}
                    onMouseEnter={() => setSelectedIndex(idx)}
                  >
                    <span className="text-base leading-none">{typeIcon(t.type_hint)}</span>
                    <span className="flex-1 truncate">{t.title}</span>
                    {t.type_hint && (
                      <span className="text-[10px] text-gray-400 dark:text-gray-500 capitalize">{t.type_hint}</span>
                    )}
                  </button>
                )
              })}
            </div>
          )}

          {/* Actions section */}
          {displayActions.length > 0 && (
            <div>
              <div className="px-3 pt-2.5 pb-1 text-[10px] font-semibold uppercase tracking-wider text-gray-400 dark:text-gray-500">
                Actions
              </div>
              {displayActions.map((a, i) => {
                const idx = displayThings.length + i
                return (
                  <button
                    key={a.id}
                    data-idx={idx}
                    onClick={a.run}
                    className={`w-full flex items-center gap-3 px-4 py-2.5 text-left text-sm transition-colors ${
                      clampedIndex === idx
                        ? 'bg-indigo-50 dark:bg-indigo-950/60 text-indigo-700 dark:text-indigo-300'
                        : 'text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800/60'
                    }`}
                    onMouseEnter={() => setSelectedIndex(idx)}
                  >
                    <span className="text-base leading-none">{a.icon}</span>
                    <span className="flex-1">{a.label}</span>
                    {a.shortcut && (
                      <kbd className="text-[10px] font-mono text-gray-400 bg-gray-100 dark:bg-gray-800 px-1.5 py-0.5 rounded">
                        {a.shortcut}
                      </kbd>
                    )}
                  </button>
                )
              })}
            </div>
          )}

          {/* Empty state */}
          {displayThings.length === 0 && displayActions.length === 0 && (
            <div className="px-4 py-8 text-center text-sm text-gray-400 dark:text-gray-500">
              No results for &ldquo;{query}&rdquo;
            </div>
          )}

          {/* Hint row */}
          {!query && (
            <div className="px-4 py-2 border-t border-gray-100 dark:border-gray-800 flex items-center gap-3 text-[10px] text-gray-400 dark:text-gray-500">
              <span><kbd className="font-mono bg-gray-100 dark:bg-gray-800 px-1 rounded">↑↓</kbd> navigate</span>
              <span><kbd className="font-mono bg-gray-100 dark:bg-gray-800 px-1 rounded">↵</kbd> select</span>
              <span><kbd className="font-mono bg-gray-100 dark:bg-gray-800 px-1 rounded">&gt;</kbd> actions</span>
              <span><kbd className="font-mono bg-gray-100 dark:bg-gray-800 px-1 rounded">#type</kbd> filter</span>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
