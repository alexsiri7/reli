import { useState } from 'react'
import { useShallow } from 'zustand/react/shallow'
import { useStore } from '../store'
import type { MergeSuggestion } from '../store'
import { typeIcon } from '../utils'

function MergeCard({ suggestion, onMerge, onDismiss, merging }: {
  suggestion: MergeSuggestion
  onMerge: (keepId: string, removeId: string) => void
  onDismiss: (aId: string, bId: string) => void
  merging: boolean
}) {
  const [keepChoice, setKeepChoice] = useState<'a' | 'b' | null>(null)
  const { thingTypes } = useStore(useShallow(s => ({ thingTypes: s.thingTypes })))

  const handleMerge = () => {
    if (!keepChoice) return
    const keepId = keepChoice === 'a' ? suggestion.thing_a.id : suggestion.thing_b.id
    const removeId = keepChoice === 'a' ? suggestion.thing_b.id : suggestion.thing_a.id
    onMerge(keepId, removeId)
  }

  return (
    <div className="px-4 py-2 hover:bg-gray-100 dark:hover:bg-gray-900 transition-colors">
      <p className="text-xs text-gray-400 dark:text-gray-500 mb-1.5">{suggestion.reason}</p>
      <div className="flex flex-col gap-1">
        <label className="flex items-center gap-2 cursor-pointer group">
          <input
            type="radio"
            name={`merge-${suggestion.thing_a.id}-${suggestion.thing_b.id}`}
            checked={keepChoice === 'a'}
            onChange={() => setKeepChoice('a')}
            className="accent-indigo-500"
          />
          <span className="text-sm shrink-0">{typeIcon(suggestion.thing_a.type_hint, thingTypes)}</span>
          <span className="text-sm text-gray-700 dark:text-gray-300 truncate group-hover:text-gray-900 dark:group-hover:text-gray-100">
            {suggestion.thing_a.title}
          </span>
        </label>
        <label className="flex items-center gap-2 cursor-pointer group">
          <input
            type="radio"
            name={`merge-${suggestion.thing_a.id}-${suggestion.thing_b.id}`}
            checked={keepChoice === 'b'}
            onChange={() => setKeepChoice('b')}
            className="accent-indigo-500"
          />
          <span className="text-sm shrink-0">{typeIcon(suggestion.thing_b.type_hint, thingTypes)}</span>
          <span className="text-sm text-gray-700 dark:text-gray-300 truncate group-hover:text-gray-900 dark:group-hover:text-gray-100">
            {suggestion.thing_b.title}
          </span>
        </label>
      </div>
      <div className="flex items-center gap-2 mt-2">
        <button
          onClick={handleMerge}
          disabled={!keepChoice || merging}
          className="text-xs font-medium text-indigo-500 dark:text-indigo-400 hover:text-indigo-700 dark:hover:text-indigo-300 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {merging ? 'Merging...' : 'Merge'}
        </button>
        <button
          onClick={() => onDismiss(suggestion.thing_a.id, suggestion.thing_b.id)}
          className="text-xs text-gray-400 dark:text-gray-500 hover:text-gray-600 dark:hover:text-gray-300"
        >
          Dismiss
        </button>
      </div>
    </div>
  )
}

export function MergeSuggestions() {
  const { mergeSuggestions, mergeInProgress, executeMerge, dismissMergeSuggestion } = useStore(
    useShallow(s => ({
      mergeSuggestions: s.mergeSuggestions,
      mergeInProgress: s.mergeInProgress,
      executeMerge: s.executeMerge,
      dismissMergeSuggestion: s.dismissMergeSuggestion,
    }))
  )

  if (mergeSuggestions.length === 0) return null

  return (
    <section className="py-2 border-b border-gray-100 dark:border-gray-800">
      <h2 className="px-4 pb-1 text-xs font-semibold text-amber-500 dark:text-amber-400 uppercase tracking-widest flex items-center gap-1.5">
        <span>Merge Suggestions</span>
        <span className="ml-auto text-[10px] font-normal tabular-nums text-gray-400 dark:text-gray-500">
          {mergeSuggestions.length}
        </span>
      </h2>
      {mergeSuggestions.map(s => (
        <MergeCard
          key={`${s.thing_a.id}-${s.thing_b.id}`}
          suggestion={s}
          onMerge={executeMerge}
          onDismiss={dismissMergeSuggestion}
          merging={mergeInProgress}
        />
      ))}
    </section>
  )
}
