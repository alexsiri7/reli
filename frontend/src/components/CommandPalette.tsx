import { useEffect, useRef, useState, useCallback } from 'react'
import { useShallow } from 'zustand/react/shallow'
import { useStore, type Thing } from '../store'
import { typeIcon } from '../utils'

interface Action {
  id: string
  label: string
  description?: string
  icon: string
  onSelect: () => void
  keywords?: string
}

function fuzzyMatch(query: string, text: string): boolean {
  if (!query) return true
  const q = query.toLowerCase()
  const t = text.toLowerCase()
  // Simple subsequence match
  let qi = 0
  for (let i = 0; i < t.length && qi < q.length; i++) {
    if (t[i] === q[qi]) qi++
  }
  return qi === q.length
}

export function CommandPalette({ onClose }: { onClose: () => void }) {
  const [query, setQuery] = useState('')
  const [selectedIndex, setSelectedIndex] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)
  const listRef = useRef<HTMLDivElement>(null)

  const { things, thingTypes, openThingDetail, openSettings, openFeedback, sendMessage, setMobileView } = useStore(
    useShallow(s => ({
      things: s.things,
      thingTypes: s.thingTypes,
      openThingDetail: s.openThingDetail,
      openSettings: s.openSettings,
      openFeedback: s.openFeedback,
      sendMessage: s.sendMessage,
      setMobileView: s.setMobileView,
    }))
  )

  const actions: Action[] = [
    {
      id: 'settings',
      label: 'Open Settings',
      icon: '⚙️',
      keywords: 'settings preferences config',
      onSelect: () => { openSettings(); onClose() },
    },
    {
      id: 'feedback',
      label: 'Send Feedback',
      icon: '💬',
      keywords: 'feedback report bug',
      onSelect: () => { openFeedback(); onClose() },
    },
    {
      id: 'chat',
      label: 'Go to Chat',
      icon: '🗨️',
      keywords: 'chat message assistant ai',
      onSelect: () => { setMobileView('chat'); onClose() },
    },
    {
      id: 'things',
      label: 'Go to Things',
      icon: '📋',
      keywords: 'things list sidebar',
      onSelect: () => { setMobileView('things'); onClose() },
    },
  ]

  // If query looks like a quick-add command, offer to add it
  const isQuickAdd = query.startsWith('>')
  const quickAddText = isQuickAdd ? query.slice(1).trim() : ''

  const filteredThings: Thing[] = query && !isQuickAdd
    ? things.filter(t => fuzzyMatch(query, t.title) || (t.type_hint && fuzzyMatch(query, t.type_hint)))
    : []

  const filteredActions: Action[] = !isQuickAdd
    ? actions.filter(a => !query || fuzzyMatch(query, a.label) || (a.keywords && fuzzyMatch(query, a.keywords)))
    : []

  const quickAddAction: Action | null = isQuickAdd && quickAddText ? {
    id: 'quick-add',
    label: `Add: "${quickAddText}"`,
    icon: '➕',
    description: 'Create via chat',
    onSelect: () => {
      sendMessage(`Add a new thing: ${quickAddText}`)
      setMobileView('chat')
      onClose()
    },
  } : null

  const allItems: Array<{ type: 'thing'; thing: Thing } | { type: 'action'; action: Action }> = [
    ...(quickAddAction ? [{ type: 'action' as const, action: quickAddAction }] : []),
    ...filteredActions.map(a => ({ type: 'action' as const, action: a })),
    ...filteredThings.map(t => ({ type: 'thing' as const, thing: t })),
  ]

  // Reset selection when list changes
  useEffect(() => {
    setSelectedIndex(0)
  }, [query])

  // Focus input on mount
  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  const handleSelect = useCallback((idx: number) => {
    const item = allItems[idx]
    if (!item) return
    if (item.type === 'action') {
      item.action.onSelect()
    } else {
      openThingDetail(item.thing.id)
      onClose()
    }
  }, [allItems, openThingDetail, onClose])

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Escape') {
      onClose()
    } else if (e.key === 'ArrowDown') {
      e.preventDefault()
      setSelectedIndex(i => Math.min(i + 1, allItems.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setSelectedIndex(i => Math.max(i - 1, 0))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      handleSelect(selectedIndex)
    }
  }, [allItems.length, selectedIndex, handleSelect, onClose])

  // Scroll selected item into view
  useEffect(() => {
    const list = listRef.current
    if (!list) return
    const selected = list.querySelector('[data-selected="true"]') as HTMLElement | null
    if (selected) {
      selected.scrollIntoView({ block: 'nearest' })
    }
  }, [selectedIndex])

  return (
    <div
      className="fixed inset-0 z-[100] flex items-start justify-center pt-[15vh] px-4"
      onClick={onClose}
    >
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/50 dark:bg-black/70" />

      {/* Palette */}
      <div
        className="relative w-full max-w-lg bg-white dark:bg-gray-900 rounded-xl shadow-2xl border border-gray-200 dark:border-gray-700 overflow-hidden"
        onClick={e => e.stopPropagation()}
      >
        {/* Search input */}
        <div className="flex items-center gap-2 px-4 py-3 border-b border-gray-200 dark:border-gray-800">
          <svg className="w-4 h-4 text-gray-400 dark:text-gray-500 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={e => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Search things or actions… (> to add)"
            className="flex-1 bg-transparent text-sm text-gray-900 dark:text-gray-100 placeholder-gray-400 dark:placeholder-gray-500 outline-none"
          />
          <kbd className="hidden sm:flex items-center text-[10px] text-gray-400 dark:text-gray-500 font-mono border border-gray-200 dark:border-gray-700 rounded px-1 py-0.5">
            esc
          </kbd>
        </div>

        {/* Results */}
        <div ref={listRef} className="max-h-80 overflow-y-auto py-1">
          {allItems.length === 0 && (
            <div className="px-4 py-8 text-center text-sm text-gray-400 dark:text-gray-500">
              {query ? 'No results found' : 'Type to search things or actions'}
            </div>
          )}

          {/* Quick-add hint when no query */}
          {!query && (
            <div className="px-4 py-2 text-xs text-gray-400 dark:text-gray-500 border-b border-gray-100 dark:border-gray-800">
              Tip: type <span className="font-mono bg-gray-100 dark:bg-gray-800 px-1 rounded">&gt; text</span> to quickly add a new thing
            </div>
          )}

          {filteredActions.length > 0 && !isQuickAdd && (
            <div className="py-1">
              <div className="px-3 py-1 text-[10px] font-semibold text-gray-400 dark:text-gray-500 uppercase tracking-wider">
                Actions
              </div>
              {filteredActions.map(action => {
                const idx = allItems.findIndex(i => i.type === 'action' && i.action.id === action.id)
                return (
                  <button
                    key={action.id}
                    data-selected={idx === selectedIndex ? 'true' : 'false'}
                    onClick={() => handleSelect(idx)}
                    onMouseEnter={() => setSelectedIndex(idx)}
                    className={`w-full flex items-center gap-3 px-4 py-2 text-sm transition-colors ${
                      idx === selectedIndex
                        ? 'bg-indigo-50 dark:bg-indigo-950 text-indigo-700 dark:text-indigo-300'
                        : 'text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800'
                    }`}
                  >
                    <span className="text-base w-5 text-center shrink-0">{action.icon}</span>
                    <span className="flex-1 text-left">{action.label}</span>
                    {action.description && (
                      <span className="text-xs text-gray-400 dark:text-gray-500">{action.description}</span>
                    )}
                  </button>
                )
              })}
            </div>
          )}

          {quickAddAction && (
            <button
              data-selected={selectedIndex === 0 ? 'true' : 'false'}
              onClick={() => handleSelect(0)}
              onMouseEnter={() => setSelectedIndex(0)}
              className={`w-full flex items-center gap-3 px-4 py-2 text-sm transition-colors ${
                selectedIndex === 0
                  ? 'bg-indigo-50 dark:bg-indigo-950 text-indigo-700 dark:text-indigo-300'
                  : 'text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800'
              }`}
            >
              <span className="text-base w-5 text-center shrink-0">{quickAddAction.icon}</span>
              <span className="flex-1 text-left">{quickAddAction.label}</span>
              <span className="text-xs text-gray-400 dark:text-gray-500">via chat</span>
            </button>
          )}

          {filteredThings.length > 0 && (
            <div className="py-1">
              {!isQuickAdd && filteredActions.length > 0 && (
                <div className="px-3 py-1 text-[10px] font-semibold text-gray-400 dark:text-gray-500 uppercase tracking-wider mt-1">
                  Things
                </div>
              )}
              {filteredThings.map(thing => {
                const idx = allItems.findIndex(i => i.type === 'thing' && i.thing.id === thing.id)
                return (
                  <button
                    key={thing.id}
                    data-selected={idx === selectedIndex ? 'true' : 'false'}
                    onClick={() => handleSelect(idx)}
                    onMouseEnter={() => setSelectedIndex(idx)}
                    className={`w-full flex items-center gap-3 px-4 py-2 text-sm transition-colors ${
                      idx === selectedIndex
                        ? 'bg-indigo-50 dark:bg-indigo-950 text-indigo-700 dark:text-indigo-300'
                        : 'text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800'
                    }`}
                  >
                    <span className="text-base w-5 text-center shrink-0">
                      {typeIcon(thing.type_hint, thingTypes)}
                    </span>
                    <span className="flex-1 text-left truncate">{thing.title}</span>
                    {thing.type_hint && (
                      <span className="text-xs text-gray-400 dark:text-gray-500 capitalize shrink-0">
                        {thing.type_hint}
                      </span>
                    )}
                  </button>
                )
              })}
            </div>
          )}
        </div>

        {/* Footer hint */}
        <div className="px-4 py-2 border-t border-gray-100 dark:border-gray-800 flex items-center gap-4 text-[10px] text-gray-400 dark:text-gray-500">
          <span className="flex items-center gap-1">
            <kbd className="font-mono border border-gray-200 dark:border-gray-700 rounded px-1">↑↓</kbd>
            navigate
          </span>
          <span className="flex items-center gap-1">
            <kbd className="font-mono border border-gray-200 dark:border-gray-700 rounded px-1">↵</kbd>
            select
          </span>
          <span className="flex items-center gap-1">
            <kbd className="font-mono border border-gray-200 dark:border-gray-700 rounded px-1">esc</kbd>
            close
          </span>
        </div>
      </div>
    </div>
  )
}
