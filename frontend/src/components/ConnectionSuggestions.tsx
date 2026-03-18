import { useShallow } from 'zustand/react/shallow'
import { useStore } from '../store'
import type { ConnectionSuggestion } from '../store'
import { typeIcon } from '../utils'

function ConnectionCard({ suggestion, onAccept, onDismiss, onDefer, accepting }: {
  suggestion: ConnectionSuggestion
  onAccept: (id: string) => void
  onDismiss: (id: string) => void
  onDefer: (id: string) => void
  accepting: boolean
}) {
  const { thingTypes, openThingDetail } = useStore(useShallow(s => ({
    thingTypes: s.thingTypes,
    openThingDetail: s.openThingDetail,
  })))

  return (
    <div className="px-4 py-2 hover:bg-gray-100 dark:hover:bg-gray-900 transition-colors">
      <div className="flex items-center gap-1.5 mb-1">
        <span
          className="text-sm cursor-pointer hover:underline truncate flex items-center gap-1"
          onClick={() => openThingDetail(suggestion.from_thing.id)}
          title={suggestion.from_thing.title}
        >
          <span className="shrink-0">{typeIcon(suggestion.from_thing.type_hint, thingTypes)}</span>
          <span className="text-gray-700 dark:text-gray-300 truncate">{suggestion.from_thing.title}</span>
        </span>
        <span className="text-xs text-gray-400 shrink-0">&harr;</span>
        <span
          className="text-sm cursor-pointer hover:underline truncate flex items-center gap-1"
          onClick={() => openThingDetail(suggestion.to_thing.id)}
          title={suggestion.to_thing.title}
        >
          <span className="shrink-0">{typeIcon(suggestion.to_thing.type_hint, thingTypes)}</span>
          <span className="text-gray-700 dark:text-gray-300 truncate">{suggestion.to_thing.title}</span>
        </span>
      </div>
      <p className="text-xs text-gray-400 dark:text-gray-400 mb-1.5">
        <span className="font-medium text-gray-500 dark:text-gray-400">{suggestion.suggested_relationship_type}</span>
        {' — '}{suggestion.reason}
      </p>
      <div className="flex items-center gap-2">
        <button
          onClick={() => onAccept(suggestion.id)}
          disabled={accepting}
          className="text-xs font-medium text-indigo-500 dark:text-indigo-400 hover:text-indigo-700 dark:hover:text-indigo-300 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {accepting ? 'Connecting...' : 'Connect'}
        </button>
        <button
          onClick={() => onDefer(suggestion.id)}
          className="text-xs text-gray-400 dark:text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
        >
          Later
        </button>
        <button
          onClick={() => onDismiss(suggestion.id)}
          className="text-xs text-gray-400 dark:text-gray-400 hover:text-red-500 dark:hover:text-red-400"
        >
          Dismiss
        </button>
      </div>
    </div>
  )
}

export function ConnectionSuggestions() {
  const { connectionSuggestions, connectionAcceptInProgress, acceptConnectionSuggestion, dismissConnectionSuggestion, deferConnectionSuggestion } = useStore(
    useShallow(s => ({
      connectionSuggestions: s.connectionSuggestions,
      connectionAcceptInProgress: s.connectionAcceptInProgress,
      acceptConnectionSuggestion: s.acceptConnectionSuggestion,
      dismissConnectionSuggestion: s.dismissConnectionSuggestion,
      deferConnectionSuggestion: s.deferConnectionSuggestion,
    }))
  )

  if (connectionSuggestions.length === 0) return null

  return (
    <section className="py-2 border-b border-gray-100 dark:border-gray-800">
      <h2 className="px-4 pb-1 text-xs font-semibold text-indigo-500 dark:text-indigo-400 uppercase tracking-widest flex items-center gap-1.5">
        <span>Suggested Connections</span>
        <span className="ml-auto text-[10px] font-normal tabular-nums text-gray-400 dark:text-gray-400">
          {connectionSuggestions.length}
        </span>
      </h2>
      {connectionSuggestions.map(s => (
        <ConnectionCard
          key={s.id}
          suggestion={s}
          onAccept={acceptConnectionSuggestion}
          onDismiss={dismissConnectionSuggestion}
          onDefer={deferConnectionSuggestion}
          accepting={connectionAcceptInProgress}
        />
      ))}
    </section>
  )
}
