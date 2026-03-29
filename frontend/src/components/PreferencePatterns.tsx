import { useState, useCallback, useMemo } from 'react'
import { useStore } from '../store'

interface Pattern {
  pattern: string
  confidence: 'emerging' | 'moderate' | 'strong'
  observations: number
  first_observed?: string
  last_observed?: string
}

const CONFIDENCE_STYLES: Record<string, { bg: string; text: string; label: string }> = {
  strong: { bg: 'bg-green-100 dark:bg-green-900/30', text: 'text-green-700 dark:text-green-400', label: 'Strong' },
  moderate: { bg: 'bg-yellow-100 dark:bg-yellow-900/30', text: 'text-yellow-700 dark:text-yellow-400', label: 'Moderate' },
  emerging: { bg: 'bg-blue-100 dark:bg-blue-900/30', text: 'text-blue-700 dark:text-blue-400', label: 'Emerging' },
}

const DEFAULT_STYLE = { bg: 'bg-blue-100 dark:bg-blue-900/30', text: 'text-blue-700 dark:text-blue-400', label: 'Emerging' }

function ConfidenceBadge({ confidence }: { confidence: string }) {
  const style = CONFIDENCE_STYLES[confidence] ?? DEFAULT_STYLE
  return (
    <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium ${style.bg} ${style.text}`}>
      {style.label}
    </span>
  )
}

function PatternRow({
  pattern,
  onDelete,
  onEdit,
}: {
  pattern: Pattern
  onDelete: () => void
  onEdit: (updated: Pattern) => void
}) {
  const [editing, setEditing] = useState(false)
  const [editText, setEditText] = useState(pattern.pattern)

  const handleSave = useCallback(() => {
    const trimmed = editText.trim()
    if (trimmed && trimmed !== pattern.pattern) {
      onEdit({ ...pattern, pattern: trimmed })
    }
    setEditing(false)
  }, [editText, pattern, onEdit])

  return (
    <div className="group flex items-start gap-2 px-2 py-1.5 rounded-md hover:bg-gray-50 dark:hover:bg-gray-800/50 transition-colors">
      <div className="flex-1 min-w-0">
        {editing ? (
          <div className="flex items-center gap-1">
            <input
              type="text"
              value={editText}
              onChange={e => setEditText(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') handleSave(); if (e.key === 'Escape') setEditing(false) }}
              className="flex-1 text-sm px-1.5 py-0.5 rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-900 dark:text-white focus:outline-none focus:ring-1 focus:ring-indigo-500"
              autoFocus
            />
            <button onClick={handleSave} className="text-xs text-indigo-500 hover:text-indigo-700 dark:hover:text-indigo-300 font-medium">Save</button>
            <button onClick={() => setEditing(false)} className="text-xs text-gray-400 hover:text-gray-600 dark:hover:text-gray-300">Cancel</button>
          </div>
        ) : (
          <p className="text-sm text-gray-700 dark:text-gray-300 leading-snug">{pattern.pattern}</p>
        )}
        <div className="flex items-center gap-2 mt-1">
          <ConfidenceBadge confidence={pattern.confidence} />
          <span className="text-[10px] text-gray-400 dark:text-gray-500">
            {pattern.observations} observation{pattern.observations !== 1 ? 's' : ''}
          </span>
          {pattern.last_observed && (
            <span className="text-[10px] text-gray-400 dark:text-gray-500">
              Last: {new Date(pattern.last_observed).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}
            </span>
          )}
        </div>
      </div>
      {!editing && (
        <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity shrink-0">
          <button
            onClick={() => { setEditText(pattern.pattern); setEditing(true) }}
            className="p-1 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
            title="Edit pattern"
          >
            <svg xmlns="http://www.w3.org/2000/svg" className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
            </svg>
          </button>
          <button
            onClick={onDelete}
            className="p-1 text-gray-400 hover:text-red-500 dark:hover:text-red-400"
            title="Remove pattern"
          >
            <svg xmlns="http://www.w3.org/2000/svg" className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
      )}
    </div>
  )
}

export function PreferencePatterns({ thingId, data }: { thingId: string; data: Record<string, unknown> | null }) {
  const updateThing = useStore(s => s.updateThing)
  const [adding, setAdding] = useState(false)
  const [newPattern, setNewPattern] = useState('')

  const patterns: Pattern[] = useMemo(
    () => Array.isArray(data?.patterns) ? (data.patterns as Pattern[]) : [],
    [data],
  )

  const savePatterns = useCallback((updated: Pattern[]) => {
    updateThing(thingId, { data: { ...data, patterns: updated } })
  }, [thingId, data, updateThing])

  const handleDelete = useCallback((index: number) => {
    savePatterns(patterns.filter((_, i) => i !== index))
  }, [patterns, savePatterns])

  const handleEdit = useCallback((index: number, updated: Pattern) => {
    savePatterns(patterns.map((p, i) => i === index ? updated : p))
  }, [patterns, savePatterns])

  const handleAdd = useCallback(() => {
    const trimmed = newPattern.trim()
    if (!trimmed) return
    const now = new Date().toISOString().split('T')[0]
    savePatterns([...patterns, {
      pattern: trimmed,
      confidence: 'strong',
      observations: 1,
      first_observed: now,
      last_observed: now,
    }])
    setNewPattern('')
    setAdding(false)
  }, [newPattern, patterns, savePatterns])

  // Non-pattern data fields
  const otherEntries = data ? Object.entries(data).filter(([key]) => key !== 'patterns') : []

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-semibold text-gray-400 dark:text-gray-400 uppercase tracking-wider">
          Learned Patterns ({patterns.length})
        </h3>
        {!adding && (
          <button
            onClick={() => setAdding(true)}
            className="text-xs text-indigo-500 hover:text-indigo-700 dark:text-indigo-400 dark:hover:text-indigo-300 font-medium"
          >
            + Add
          </button>
        )}
      </div>

      {patterns.length === 0 && !adding && (
        <p className="text-xs text-gray-400 dark:text-gray-500 italic px-2">
          As we talk, I'll learn how you like to work. You can always edit what I've picked up.
        </p>
      )}

      <div className="space-y-0.5">
        {patterns.map((p, i) => (
          <PatternRow
            key={`${p.pattern}-${i}`}
            pattern={p}
            onDelete={() => handleDelete(i)}
            onEdit={(updated) => handleEdit(i, updated)}
          />
        ))}
      </div>

      {adding && (
        <div className="flex items-center gap-1 px-2">
          <input
            type="text"
            value={newPattern}
            onChange={e => setNewPattern(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') handleAdd(); if (e.key === 'Escape') setAdding(false) }}
            placeholder="e.g., Prefers concise responses"
            className="flex-1 text-sm px-2 py-1 rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-900 dark:text-white placeholder-gray-400 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            autoFocus
          />
          <button onClick={handleAdd} className="text-xs text-indigo-500 hover:text-indigo-700 dark:hover:text-indigo-300 font-medium px-2 py-1">Add</button>
          <button onClick={() => { setAdding(false); setNewPattern('') }} className="text-xs text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 px-1 py-1">Cancel</button>
        </div>
      )}

      {otherEntries.length > 0 && (
        <div className="space-y-1.5 pt-2 border-t border-gray-100 dark:border-gray-800">
          {otherEntries.map(([key, value]) => (
            <div key={key} className="text-sm px-2">
              <span className="font-medium text-gray-500 dark:text-gray-400">{key}:</span>{' '}
              <span className="text-gray-700 dark:text-gray-300">
                {typeof value === 'string' ? value : JSON.stringify(value)}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
