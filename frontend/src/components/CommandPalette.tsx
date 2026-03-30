import { useEffect, useRef, useState } from 'react'
import { useStore } from '../store'

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

export function CommandPalette() {
  const closeCommandPalette = useStore(s => s.closeCommandPalette)
  const openQuickAdd = useStore(s => s.openQuickAdd)
  const setSidebarOpen = useStore(s => s.setSidebarOpen)
  const sidebarOpen = useStore(s => s.sidebarOpen)
  const setChatMode = useStore(s => s.setChatMode)
  const chatMode = useStore(s => s.chatMode)
  const focusChatInput = useStore(s => s.focusChatInput)
  const openSettings = useStore(s => s.openSettings)

  const [query, setQuery] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)
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

  const filtered = query.trim()
    ? commands.filter(
        c =>
          c.label.toLowerCase().includes(query.toLowerCase()) ||
          (c.description ?? '').toLowerCase().includes(query.toLowerCase()),
      )
    : commands

  const [activeIdx, setActiveIdx] = useState(0)

  // Focus input on open
  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  const runCommand = (cmd: Command) => {
    cmd.action()
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActiveIdx(i => Math.min(i + 1, filtered.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActiveIdx(i => Math.max(i - 1, 0))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      if (filtered[activeIdx]) runCommand(filtered[activeIdx])
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
            placeholder="Search commands…"
            value={query}
            onChange={e => { setQuery(e.target.value); setActiveIdx(0) }}
            onKeyDown={handleKeyDown}
            className="flex-1 bg-transparent text-sm text-gray-900 dark:text-gray-100 placeholder-gray-400 dark:placeholder-gray-500 outline-none"
          />
          <kbd className="text-xs text-gray-400 dark:text-gray-500 border border-gray-200 dark:border-gray-700 rounded px-1.5 py-0.5">Esc</kbd>
        </div>

        {/* Command list */}
        <ul className="max-h-72 overflow-y-auto py-1.5" role="listbox">
          {filtered.length === 0 ? (
            <li className="px-4 py-3 text-sm text-gray-400 dark:text-gray-500">No commands found</li>
          ) : (
            filtered.map((cmd, idx) => (
              <li
                key={cmd.id}
                role="option"
                aria-selected={idx === activeIdx}
                className={`flex items-center justify-between gap-3 px-4 py-2.5 cursor-pointer text-sm transition-colors ${
                  idx === activeIdx
                    ? 'bg-indigo-50 dark:bg-indigo-950 text-indigo-700 dark:text-indigo-300'
                    : 'text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800'
                }`}
                onMouseEnter={() => setActiveIdx(idx)}
                onMouseDown={e => {
                  e.preventDefault()
                  runCommand(cmd)
                }}
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
            ))
          )}
        </ul>

        {/* Footer hint */}
        <div className="border-t border-gray-100 dark:border-gray-800 px-4 py-2 flex items-center gap-3 text-xs text-gray-400 dark:text-gray-500">
          <span><kbd className="font-mono">↑↓</kbd> navigate</span>
          <span><kbd className="font-mono">↵</kbd> run</span>
          <span><kbd className="font-mono">Esc</kbd> close</span>
          <span className="ml-auto">{m}K to open</span>
        </div>
      </div>
    </div>
  )
}
