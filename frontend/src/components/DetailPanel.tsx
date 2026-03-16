import { useEffect, useMemo } from 'react'
import { useShallow } from 'zustand/react/shallow'
import { useStore } from '../store'
import type { Relationship, ThingType } from '../store'
import { typeIcon, formatTimestamp, formatDate, isOverdue, priorityLabel } from '../utils'

export function DetailPanel() {
  const {
    detailThingId, detailThing, detailRelationships, detailHistory,
    detailLoading, closeThingDetail, navigateThingDetail, goBackThingDetail,
    things, thingTypes,
  } = useStore(useShallow(s => ({
    detailThingId: s.detailThingId,
    detailThing: s.detailThing,
    detailRelationships: s.detailRelationships,
    detailHistory: s.detailHistory,
    detailLoading: s.detailLoading,
    closeThingDetail: s.closeThingDetail,
    navigateThingDetail: s.navigateThingDetail,
    goBackThingDetail: s.goBackThingDetail,
    things: s.things,
    thingTypes: s.thingTypes,
  })))

  // Close on Escape key
  useEffect(() => {
    if (!detailThingId) return
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') closeThingDetail()
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [detailThingId, closeThingDetail])

  // Group relationships by type (must be before early return for hooks rule)
  const groupedRels = useMemo(() => {
    const opposites: Record<string, string> = {
      'child-of': 'parent-of',
      'parent-of': 'child-of',
      'depends-on': 'blocks',
      'blocks': 'depends-on',
      'part-of': 'contains',
      'contains': 'part-of',
      'followed-by': 'preceded-by',
      'preceded-by': 'followed-by',
      'spawned-from': 'spawned',
      'spawned': 'spawned-from',
    }
    const thingIds = new Set(things.map(t => t.id))
    const groups = new Map<string, { rel: Relationship; otherId: string; direction: string }[]>()
    for (const rel of detailRelationships) {
      const isFrom = rel.from_thing_id === detailThingId
      const otherId = isFrom ? rel.to_thing_id : rel.from_thing_id
      // Filter out relationships pointing to non-existent Things (orphans)
      if (!thingIds.has(otherId)) continue
      const rawType = rel.relationship_type
      const displayType = isFrom ? rawType : (opposites[rawType] ?? rawType)
      const direction = '\u2192'
      if (!groups.has(displayType)) groups.set(displayType, [])
      groups.get(displayType)!.push({ rel, otherId, direction })
    }
    return groups
  }, [detailRelationships, detailThingId, things])

  if (!detailThingId) return null

  const thing = detailThing
  const canGoBack = detailHistory.length > 0

  // Resolve a Thing by ID — check local store first, fall back to minimal display
  const resolveThing = (id: string) => things.find(t => t.id === id)

  // Parent/children from the store
  const children = thing ? things.filter(t => t.parent_id === thing.id) : []
  const parent = thing?.parent_id ? things.find(t => t.id === thing.parent_id) : null

  const dataEntries = thing?.data ? Object.entries(thing.data) : []

  // Format relationship type for display: "related_to" -> "Related to"
  const formatRelType = (type: string) =>
    type.replace(/_/g, ' ').replace(/^\w/, c => c.toUpperCase())

  return (
    <>
      {/* Backdrop for mobile */}
      <div
        onClick={closeThingDetail}
        className="fixed inset-0 z-50 bg-black/20 md:hidden"
      />

      {/* Panel — desktop: inline flex child on left; mobile: fixed overlay from left */}
      <div className="fixed left-0 top-0 bottom-0 z-50 w-full max-w-md bg-white dark:bg-gray-900 border-r border-gray-200 dark:border-gray-700 shadow-xl flex flex-col overflow-hidden animate-slide-in-left md:relative md:z-auto md:w-80 md:max-w-none md:shrink-0 md:shadow-none md:animate-none md:border-r">
        {/* Header */}
        <div className="flex items-center gap-2 px-4 py-3 border-b border-gray-200 dark:border-gray-700 shrink-0">
          {canGoBack && (
            <button
              onClick={goBackThingDetail}
              className="p-1.5 rounded-lg text-gray-400 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 hover:text-gray-600 dark:hover:text-gray-300 transition-colors"
              aria-label="Go back"
              title="Go back"
            >
              <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
              </svg>
            </button>
          )}
          <div className="flex-1 min-w-0">
            {thing ? (
              <div className="flex items-center gap-2">
                <span className="text-lg shrink-0">{typeIcon(thing.type_hint, thingTypes)}</span>
                <h2 className="text-sm font-semibold text-gray-900 dark:text-white truncate">{thing.title}</h2>
              </div>
            ) : detailLoading ? (
              <div className="h-5 w-40 bg-gray-200 dark:bg-gray-700 rounded animate-pulse" />
            ) : (
              <span className="text-sm text-gray-400">Not found</span>
            )}
          </div>
          <button
            onClick={closeThingDetail}
            className="p-1.5 rounded-lg text-gray-400 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 hover:text-gray-600 dark:hover:text-gray-300 transition-colors"
            aria-label="Close detail panel"
          >
            <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto">
          {detailLoading ? (
            <div className="p-4 space-y-3 animate-pulse">
              <div className="h-4 bg-gray-200 dark:bg-gray-700 rounded w-3/4" />
              <div className="h-4 bg-gray-200 dark:bg-gray-700 rounded w-1/2" />
              <div className="h-4 bg-gray-200 dark:bg-gray-700 rounded w-5/6" />
              <div className="h-4 bg-gray-200 dark:bg-gray-700 rounded w-2/3" />
            </div>
          ) : thing ? (
            <div className="p-4 space-y-4">
              {/* Type & Priority */}
              <div className="flex items-center gap-3 text-xs">
                {thing.type_hint && (
                  <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-300 capitalize">
                    {typeIcon(thing.type_hint, thingTypes)} {thing.type_hint}
                  </span>
                )}
                <span className="text-gray-500 dark:text-gray-400">{priorityLabel(thing.priority)}</span>
              </div>

              {/* Check-in date */}
              {thing.checkin_date && (() => {
                const overdue = isOverdue(thing.checkin_date)
                const dateLabel = formatDate(thing.checkin_date)
                return (
                  <div className="flex items-center gap-2 text-sm">
                    <span className="shrink-0">📅</span>
                    <span className={overdue ? 'text-red-500 font-semibold' : 'text-gray-600 dark:text-gray-300'}>
                      {overdue ? '⚠ ' : ''}{dateLabel}
                    </span>
                  </div>
                )
              })()}

              {/* Data fields */}
              {dataEntries.length > 0 && (
                <div className="space-y-2">
                  <h3 className="text-xs font-semibold text-gray-400 dark:text-gray-400 uppercase tracking-wider">Details</h3>
                  <div className="space-y-1.5">
                    {dataEntries.map(([key, value]) => (
                      <div key={key} className="text-sm">
                        <span className="font-medium text-gray-500 dark:text-gray-400">{key}:</span>{' '}
                        <span className="text-gray-700 dark:text-gray-300">
                          {typeof value === 'string' ? value : JSON.stringify(value)}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Open questions */}
              {thing.open_questions && thing.open_questions.length > 0 && (
                <div className="space-y-1.5">
                  <h3 className="text-xs font-semibold text-amber-500 dark:text-amber-400 uppercase tracking-wider">Open Questions</h3>
                  <ul className="space-y-1">
                    {thing.open_questions.map((q, i) => (
                      <li key={i} className="text-sm text-amber-700 dark:text-amber-300 flex items-start gap-1.5">
                        <span className="shrink-0 mt-0.5">?</span>
                        <span>{q}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Parent */}
              {parent && (
                <div className="space-y-1.5">
                  <h3 className="text-xs font-semibold text-gray-400 dark:text-gray-400 uppercase tracking-wider">Parent</h3>
                  <ThingLink
                    id={parent.id}
                    title={parent.title}
                    typeHint={parent.type_hint}
                    thingTypes={thingTypes}
                    onClick={navigateThingDetail}
                  />
                </div>
              )}

              {/* Children */}
              {children.length > 0 && (
                <div className="space-y-1.5">
                  <h3 className="text-xs font-semibold text-gray-400 dark:text-gray-400 uppercase tracking-wider">
                    Children ({children.length})
                  </h3>
                  <div className="space-y-0.5">
                    {children.map(c => (
                      <ThingLink
                        key={c.id}
                        id={c.id}
                        title={c.title}
                        typeHint={c.type_hint}
                        thingTypes={thingTypes}
                        onClick={navigateThingDetail}
                      />
                    ))}
                  </div>
                </div>
              )}

              {/* Relationships grouped by type */}
              {groupedRels.size > 0 && (
                <div className="space-y-3">
                  <h3 className="text-xs font-semibold text-gray-400 dark:text-gray-400 uppercase tracking-wider">Relationships</h3>
                  {Array.from(groupedRels.entries()).map(([type, items]) => (
                    <div key={type} className="space-y-0.5">
                      <p className="text-xs font-medium text-gray-500 dark:text-gray-400 italic">
                        {formatRelType(type)}
                      </p>
                      {items.map(({ rel, otherId, direction }) => {
                        const other = resolveThing(otherId)
                        return (
                          <div key={rel.id} className="flex items-center gap-1.5 text-sm">
                            <span className="text-gray-400 dark:text-gray-400 text-xs shrink-0">{direction}</span>
                            {other ? (
                              <ThingLink
                                id={other.id}
                                title={other.title}
                                typeHint={other.type_hint}
                                thingTypes={thingTypes}
                                onClick={navigateThingDetail}
                              />
                            ) : (
                              <button
                                onClick={() => navigateThingDetail(otherId)}
                                className="text-sm text-indigo-600 dark:text-indigo-400 hover:underline truncate"
                              >
                                {otherId}
                              </button>
                            )}
                          </div>
                        )
                      })}
                    </div>
                  ))}
                </div>
              )}

              {/* Timestamps */}
              <div className="space-y-1 pt-2 border-t border-gray-100 dark:border-gray-700">
                <p className="text-xs text-gray-400 dark:text-gray-400">
                  Created {formatTimestamp(thing.created_at)}
                </p>
                {thing.updated_at !== thing.created_at && (
                  <p className="text-xs text-gray-400 dark:text-gray-400">
                    Updated {formatTimestamp(thing.updated_at)}
                  </p>
                )}
                {thing.last_referenced && (
                  <p className="text-xs text-gray-400 dark:text-gray-400">
                    Last discussed {formatTimestamp(thing.last_referenced)}
                  </p>
                )}
              </div>
            </div>
          ) : (
            <div className="p-4 text-sm text-gray-400 dark:text-gray-400 text-center">
              Thing not found
            </div>
          )}
        </div>
      </div>
    </>
  )
}

function ThingLink({
  id, title, typeHint, thingTypes, onClick,
}: {
  id: string
  title: string
  typeHint: string | null
  thingTypes: ThingType[]
  onClick: (id: string) => void
}) {
  return (
    <button
      onClick={() => onClick(id)}
      className="flex items-center gap-1.5 w-full text-left px-2 py-1 rounded-md hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors group"
    >
      <span className="text-sm shrink-0">{typeIcon(typeHint, thingTypes)}</span>
      <span className="text-sm text-gray-700 dark:text-gray-300 group-hover:text-indigo-600 dark:group-hover:text-indigo-400 truncate transition-colors">
        {title}
      </span>
      {typeHint && (
        <span className="ml-auto text-[10px] text-gray-400 dark:text-gray-400 capitalize shrink-0">
          {typeHint}
        </span>
      )}
    </button>
  )
}
