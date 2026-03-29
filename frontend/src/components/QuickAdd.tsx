import { useEffect, useRef, useState } from 'react'
import { useStore } from '../store'

export function QuickAdd() {
  const closeQuickAdd = useStore(s => s.closeQuickAdd)
  const createThing = useStore(s => s.createThing)

  const [title, setTitle] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    const trimmed = title.trim()
    if (!trimmed) return
    setSaving(true)
    setError(null)
    try {
      await createThing(trimmed)
      closeQuickAdd()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create')
      setSaving(false)
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') {
      e.preventDefault()
      closeQuickAdd()
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center pt-[20vh] px-4"
      onMouseDown={e => {
        if (e.target === e.currentTarget) closeQuickAdd()
      }}
    >
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/40 dark:bg-black/60" aria-hidden="true" />

      {/* Panel */}
      <div className="relative w-full max-w-md bg-white dark:bg-gray-900 rounded-xl shadow-2xl border border-gray-200 dark:border-gray-700 overflow-hidden">
        <form onSubmit={handleSubmit}>
          <div className="px-4 py-3 border-b border-gray-200 dark:border-gray-700">
            <p className="text-xs font-medium text-gray-500 dark:text-gray-400 mb-1.5">New Thing</p>
            <input
              ref={inputRef}
              type="text"
              placeholder="What's on your mind?"
              value={title}
              onChange={e => setTitle(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={saving}
              className="w-full bg-transparent text-sm text-gray-900 dark:text-gray-100 placeholder-gray-400 dark:placeholder-gray-500 outline-none"
            />
          </div>
          {error && (
            <p className="px-4 py-2 text-xs text-red-500">{error}</p>
          )}
          <div className="px-4 py-2.5 flex items-center justify-between gap-2">
            <span className="text-xs text-gray-400 dark:text-gray-500">Press Enter to save · Esc to cancel</span>
            <button
              type="submit"
              disabled={!title.trim() || saving}
              className="px-3 py-1.5 text-xs font-medium rounded-lg bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {saving ? 'Saving…' : 'Add'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
