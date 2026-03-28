import { useEffect, useRef, useState, useCallback } from 'react'
import { useShallow } from 'zustand/react/shallow'
import { useStore } from '../store'
import type { Thing } from '../store'
import { typeIcon } from '../utils'

const isMac = typeof navigator !== 'undefined' && /Mac|iPhone|iPad|iPod/.test(navigator.platform)
const modKey = isMac ? '⌘' : 'Ctrl'

interface Action {
  id: string
  label: string
  description?: string
  shortcut?: string
  icon: string
  run: () => void
  keywords?: string
}

function fuzzyMatch(query: string, text: string): boolean {
  const q = query.toLowerCase()
  const t = text.toLowerCase()
  if (t.includes(q)) return true
  // Simple fuzzy: all chars of query appear in order in text
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
    toggleSidebar,
    setMainView,
    setMobileView,
    openFeedback,
  } = useStore(
    useShallow(s => ({
      commandPaletteOpen: s.commandPaletteOpen,
      closeCommandPalette: s.closeCommandPalette,
      things: s.things,
      openThingDetail: s.openThingDetail,
      openSettings: s.openSettings,
      toggleSidebar: s.toggleSidebar,
      setMainView: s.setMainView,
      setMobileView: s.setMobileView,
      openFeedback: s.openFeedback,
    }))
  )

  const [query, setQuery] = useState('')
  const [selectedIndex, setSelectedIndex] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)
  const listRef = useRef<HTMLDivElement>(null)

  // Reset when opened
  useEffect(() => {
    if (commandPaletteOpen) {
      setQuery('')
      setSelectedIndex(0)
      setTimeout(() => inputRef.current?.focus(), 0)
    }
  }, [commandPaletteOpen])

  const close = useCallback(() => {
    closeCommandPalette()
    setQuery('')
  }, [closeCommandPalette])

  const actions: Action[] = [
    {
      id: 'new-thing',
      label: 'New Thing',
      description: 'Create a new Thing via chat',
      shortcut: `${modKey}N`,
      icon: '✚',
      keywords: 'add create new thing',
      run: () => {
        close()
        setMobileView('chat')
        setTimeout(() => document.getElementById('chat-input')?.focus(), 50)
      },
    },
    {
      id: 'toggle-sidebar',
      label: 'Toggle Sidebar',
      shortcut: `${modKey}B`,
      icon: '⬤',
      keywords: 'sidebar toggle hide show',
      run: () => { close(); toggleSidebar() },
    },
    {
      id: 'toggle-graph',
      label: 'Switch to Graph View',
      icon: '◎',
      keywords: 'graph view network',
      run: () => { close(); setMainView('graph') },
    },
    {
      id: 'toggle-list',
      label: 'Switch to List View',
      icon: '☰',
      keywords: 'list view things',
      run: () => { close(); setMainView('list') },
    },
    {
      id: 'open-settings',
      label: 'Settings',
      icon: '⚙',
      keywords: 'settings preferences config',
      run: () => { close(); openSettings() },
    },
    {
      id: 'open-feedback',
      label: 'Send Feedback',
      icon: '✉',
      keywords: 'feedback report bug',
      run: () => { close(); openFeedback() },
    },
    {
      id: 'focus-chat',
      label: 'Focus Chat',
      shortcut: '/',
      icon: '💬',
      keywords: 'chat ask question focus input',
      run: () => {
        close()
        setMobileView('chat')
        setTimeout(() => document.getElementById('chat-input')?.focus(), 50)
      },
    },
  ]

  // Parse prefix filters
  const isActionFilter = query.startsWith('>')
  const typeFilterMatch = query.match(/^#(\w*)/)
  const typeFilter = typeFilterMatch ? (typeFilterMatch[1] ?? '').toLowerCase() : null
  const rawQuery = isActionFilter
    ? query.slice(1).trim()
    : typeFilter !== null
    ? query.slice(typeFilterMatch![0].length).trim()
    : query.trim()

  // Filter + score things
  const matchedThings: Thing[] = !isActionFilter
    ? (rawQuery
        ? things
            .filter(t => fuzzyMatch(rawQuery, t.title) || (t.type_hint && fuzzyMatch(rawQuery, t.type_hint)))
            .filter(t => !typeFilter || (t.type_hint ?? '').toLowerCase().includes(typeFilter))
            .sort((a, b) => fuzzyScore(rawQuery, b.title) - fuzzyScore(rawQuery, a.title))
            .slice(0, 7)
        : typeFilter
        ? things.filter(t => (t.type_hint ?? '').toLowerCase().includes(typeFilter)).slice(0, 7)
        : things.slice(0, 5) // recent items when empty
      )
    : []

  const matchedActions: Action[] = !typeFilter
    ? (rawQuery
        ? actions.filter(a =>
            fuzzyMatch(rawQuery, a.label) ||
            (a.keywords && fuzzyMatch(rawQuery, a.keywords))
          )
        : isActionFilter
        ? actions
        : actions
      )
    : []

  type ResultItem =
    | { kind: 'thing'; thing: Thing }
    | { kind: 'action'; action: Action }

  const results: ResultItem[] = [
    ...matchedThings.map(t => ({ kind: 'thing' as const, thing: t })),
    ...matchedActions.map(a => ({ kind: 'action' as const, action: a })),
  ]

  const clampedIndex = Math.min(selectedIndex, Math.max(0, results.length - 1))

  const runSelected = useCallback(() => {
    const item = results[clampedIndex]
    if (!item) return
    if (item.kind === 'thing') {
      close()
      openThingDetail(item.thing.id)
      setMobileView('things')
    } else {
      item.action.run()
    }
  }, [results, clampedIndex, close, openThingDetail, setMobileView])

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Escape') { close(); return }
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setSelectedIndex(i => Math.min(i + 1, results.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setSelectedIndex(i => Math.max(i - 1, 0))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      runSelected()
    }
  }, [close, results.length, runSelected])

  // Scroll selected item into view
  useEffect(() => {
    if (listRef.current) {
      const el = listRef.current.querySelector(`[data-index="${clampedIndex}"]`)
      el?.scrollIntoView({ block: 'nearest' })
    }
  }, [clampedIndex])

  // Reset selection when results change
  useEffect(() => {
    setSelectedIndex(0)
  }, [query])

  if (!commandPaletteOpen) return null

  return (
    <div
      className="fixed inset-0 z-[100] flex items-start justify-center pt-[15vh] bg-black/40 backdrop-blur-sm"
      onClick={close}
    >
      <div
        className="w-full max-w-xl mx-4 bg-white dark:bg-gray-900 rounded-xl shadow-2xl border border-gray-200 dark:border-gray-700 overflow-hidden"
        onClick={e => e.stopPropagation()}
      >
        {/* Search input */}
        <div className="flex items-center gap-3 px-4 py-3 border-b border-gray-100 dark:border-gray-800">
          <svg className="w-4 h-4 text-gray-400 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="m21 21-5.197-5.197m0 0A7.5 7.5 0 1 0 5.196 5.196a7.5 7.5 0 0 0 10.607 10.607Z" />
          </svg>
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={e => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Search things or type > for actions, #type to filter…"
            className="flex-1 bg-transparent text-sm text-gray-900 dark:text-gray-100 placeholder-gray-400 outline-none"
            autoComplete="off"
            spellCheck={false}
          />
          <kbd className="hidden sm:inline-flex text-[10px] text-gray-400 border border-gray-200 dark:border-gray-700 rounded px-1.5 py-0.5 font-mono">Esc</kbd>
        </div>

        {/* Results */}
        <div ref={listRef} className="max-h-80 overflow-y-auto">
          {results.length === 0 && (
            <p className="text-sm text-gray-400 text-center py-8">No results</p>
          )}

          {matchedThings.length > 0 && (
            <div>
              <p className="px-4 pt-3 pb-1 text-[10px] font-semibold uppercase tracking-wider text-gray-400 dark:text-gray-500">
                {rawQuery ? 'Things' : 'Recent Things'}
              </p>
              {matchedThings.map((thing, i) => {
                const idx = i
                const isSelected = idx === clampedIndex
                return (
                  <button
                    key={thing.id}
                    data-index={idx}
                    className={`w-full flex items-center gap-3 px-4 py-2 text-left transition-colors ${
                      isSelected
                        ? 'bg-indigo-50 dark:bg-indigo-900/30'
                        : 'hover:bg-gray-50 dark:hover:bg-gray-800/50'
                    }`}
                    onClick={() => { openThingDetail(thing.id); setMobileView('things'); close() }}
                    onMouseEnter={() => setSelectedIndex(idx)}
                  >
                    <span className="text-base shrink-0">{typeIcon(thing.type_hint)}</span>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-gray-900 dark:text-gray-100 truncate">{thing.title}</p>
                      {thing.type_hint && (
                        <p className="text-xs text-gray-400 capitalize">{thing.type_hint}</p>
                      )}
                    </div>
                    {isSelected && (
                      <kbd className="text-[10px] text-gray-400 border border-gray-200 dark:border-gray-700 rounded px-1.5 py-0.5 font-mono shrink-0">↵</kbd>
                    )}
                  </button>
                )
              })}
            </div>
          )}

          {matchedActions.length > 0 && (
            <div>
              <p className="px-4 pt-3 pb-1 text-[10px] font-semibold uppercase tracking-wider text-gray-400 dark:text-gray-500">
                Actions
              </p>
              {matchedActions.map((action, i) => {
                const idx = matchedThings.length + i
                const isSelected = idx === clampedIndex
                return (
                  <button
                    key={action.id}
                    data-index={idx}
                    className={`w-full flex items-center gap-3 px-4 py-2 text-left transition-colors ${
                      isSelected
                        ? 'bg-indigo-50 dark:bg-indigo-900/30'
                        : 'hover:bg-gray-50 dark:hover:bg-gray-800/50'
                    }`}
                    onClick={action.run}
                    onMouseEnter={() => setSelectedIndex(idx)}
                  >
                    <span className="text-base shrink-0 w-5 text-center">{action.icon}</span>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-gray-900 dark:text-gray-100 truncate">{action.label}</p>
                      {action.description && (
                        <p className="text-xs text-gray-400">{action.description}</p>
                      )}
                    </div>
                    {action.shortcut && (
                      <kbd className="text-[10px] text-gray-400 border border-gray-200 dark:border-gray-700 rounded px-1.5 py-0.5 font-mono shrink-0">{action.shortcut}</kbd>
                    )}
                    {isSelected && !action.shortcut && (
                      <kbd className="text-[10px] text-gray-400 border border-gray-200 dark:border-gray-700 rounded px-1.5 py-0.5 font-mono shrink-0">↵</kbd>
                    )}
                  </button>
                )
              })}
            </div>
          )}
        </div>

        {/* Footer hint */}
        <div className="px-4 py-2 border-t border-gray-100 dark:border-gray-800 flex items-center gap-3 text-[10px] text-gray-400">
          <span><kbd className="font-mono">↑↓</kbd> navigate</span>
          <span><kbd className="font-mono">↵</kbd> select</span>
          <span><kbd className="font-mono">esc</kbd> close</span>
          <span className="ml-auto"><kbd className="font-mono">&gt;</kbd> actions · <kbd className="font-mono">#type</kbd> filter</span>
        </div>
      </div>
    </div>
  )
}
