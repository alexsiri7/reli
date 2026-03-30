import { useEffect, useMemo } from 'react'
import { useShallow } from 'zustand/react/shallow'
import { useStore } from '../store'
import type { Relationship, ThingType } from '../store'
import { typeIcon, formatTimestamp, formatDate, isOverdue, importanceLabel } from '../utils'
import { PreferencePatterns } from './PreferencePatterns'

// Type hint → accent color mapping (Cognitive Atelier palette)
const TYPE_COLORS: Record<string, { bg: string; text: string; dark: string }> = {
  project:    { bg: 'bg-emerald-100', text: 'text-emerald-700', dark: 'dark:bg-emerald-900/40 dark:text-emerald-300' },
  event:      { bg: 'bg-amber-100',   text: 'text-amber-700',   dark: 'dark:bg-amber-900/40 dark:text-amber-300' },
  person:     { bg: 'bg-teal-100',    text: 'text-teal-700',    dark: 'dark:bg-teal-900/40 dark:text-teal-300' },
  people:     { bg: 'bg-teal-100',    text: 'text-teal-700',    dark: 'dark:bg-teal-900/40 dark:text-teal-300' },
  idea:       { bg: 'bg-rose-100',    text: 'text-rose-700',    dark: 'dark:bg-rose-900/40 dark:text-rose-300' },
  task:       { bg: 'bg-indigo-100',  text: 'text-indigo-700',  dark: 'dark:bg-indigo-900/40 dark:text-indigo-300' },
  note:       { bg: 'bg-slate-100',   text: 'text-slate-700',   dark: 'dark:bg-slate-800 dark:text-slate-300' },
  preference: { bg: 'bg-purple-100',  text: 'text-purple-700',  dark: 'dark:bg-purple-900/40 dark:text-purple-300' },
}

function typeColor(hint: string | null | undefined) {
  if (!hint) return { bg: 'bg-gray-100', text: 'text-gray-600', dark: 'dark:bg-gray-800 dark:text-gray-300' }
  return TYPE_COLORS[hint.toLowerCase()] ?? { bg: 'bg-gray-100', text: 'text-gray-600', dark: 'dark:bg-gray-800 dark:text-gray-300' }
}

// Simple connection map: SVG radial layout showing center + connected nodes
function ConnectionMapSVG({
  centerTitle,
  connectedNodes,
}: {
  centerTitle: string
  connectedNodes: { id: string; title: string; typeHint: string | null }[]
}) {
  if (connectedNodes.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-xs text-gray-400 dark:text-gray-500">
        No connections
      </div>
    )
  }

  const W = 200
  const H = 180
  const cx = W / 2
  const cy = H / 2
  const r = Math.min(cx, cy) - 36
  const centerR = 14
  const nodeR = 10

  const nodes = connectedNodes.slice(0, 8)
  const angleStep = (2 * Math.PI) / Math.max(nodes.length, 1)

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-full" aria-label="Connection map">
      {/* Links */}
      {nodes.map((_, i) => {
        const angle = i * angleStep - Math.PI / 2
        const nx = cx + r * Math.cos(angle)
        const ny = cy + r * Math.sin(angle)
        return (
          <line
            key={i}
            x1={cx} y1={cy} x2={nx} y2={ny}
            stroke="currentColor"
            strokeWidth="1"
            className="text-gray-300 dark:text-gray-600"
          />
        )
      })}
      {/* Satellite nodes */}
      {nodes.map((node, i) => {
        const angle = i * angleStep - Math.PI / 2
        const nx = cx + r * Math.cos(angle)
        const ny = cy + r * Math.sin(angle)
        const colors = typeColor(node.typeHint)
        const label = node.title.length > 10 ? node.title.slice(0, 9) + '…' : node.title
        return (
          <g key={node.id}>
            <circle cx={nx} cy={ny} r={nodeR} className={`fill-current ${colors.text}`} opacity="0.6" />
            <text
              x={nx}
              y={ny + nodeR + 8}
              textAnchor="middle"
              fontSize="6"
              className="fill-current text-gray-500 dark:text-gray-400"
            >
              {label}
            </text>
          </g>
        )
      })}
      {/* Center node */}
      <circle cx={cx} cy={cy} r={centerR} className="fill-current text-indigo-500" opacity="0.8" />
      <text
        x={cx}
        y={cy + centerR + 9}
        textAnchor="middle"
        fontSize="6"
        fontWeight="bold"
        className="fill-current text-gray-600 dark:text-gray-300"
      >
        {centerTitle.length > 12 ? centerTitle.slice(0, 11) + '…' : centerTitle}
      </text>
    </svg>
  )
}

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

  if (!detailThingId) {
    return (
      <div className="hidden md:flex w-80 shrink-0 flex-col items-center justify-center gap-3 border-r border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 text-center px-6">
        <svg className="w-12 h-12 text-gray-200 dark:text-gray-700" viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
          <rect x="6" y="10" width="36" height="28" rx="3" stroke="currentColor" strokeWidth="2" fill="none"/>
          <line x1="6" y1="18" x2="42" y2="18" stroke="currentColor" strokeWidth="2"/>
          <rect x="12" y="23" width="10" height="3" rx="1" fill="currentColor" opacity="0.3"/>
          <rect x="12" y="29" width="24" height="2" rx="1" fill="currentColor" opacity="0.2"/>
          <rect x="12" y="33" width="18" height="2" rx="1" fill="currentColor" opacity="0.2"/>
        </svg>
        <p className="text-sm text-gray-400 dark:text-gray-500">
          Click any Thing in the sidebar to see its details and relationships.
        </p>
      </div>
    )
  }

  const thing = detailThing
  const canGoBack = detailHistory.length > 0

  // Resolve a Thing by ID — check local store first
  const resolveThing = (id: string) => things.find(t => t.id === id)

  // Parent/children from the store
  const children = thing ? things.filter(t => t.parent_id === thing.id) : []
  const parent = thing?.parent_id ? things.find(t => t.id === thing.parent_id) : null

  const dataEntries = thing?.data ? Object.entries(thing.data) : []
  // Separate curator notes from other data fields
  const notesValue = thing?.data?.notes
  const otherDataEntries = dataEntries.filter(([key]) => key !== 'notes')

  // Format relationship type for display
  const formatRelType = (type: string) =>
    type.replace(/_/g, ' ').replace(/^\w/, c => c.toUpperCase())

  // All connected thing IDs for the connection map
  const connectedNodes = useMemo(() => {
    const result: { id: string; title: string; typeHint: string | null }[] = []
    const seen = new Set<string>()
    for (const [, items] of groupedRels) {
      for (const { otherId } of items) {
        if (seen.has(otherId)) continue
        seen.add(otherId)
        const t = resolveThing(otherId)
        if (t) result.push({ id: t.id, title: t.title, typeHint: t.type_hint })
      }
    }
    return result
  }, [groupedRels]) // eslint-disable-line react-hooks/exhaustive-deps

  const colors = typeColor(thing?.type_hint)

  return (
    <>
      {/* Backdrop for mobile */}
      <div
        onClick={closeThingDetail}
        className="fixed inset-0 z-50 bg-black/20 md:hidden"
      />

      {/* Panel */}
      <div className="fixed left-0 top-0 bottom-0 z-50 w-full max-w-md bg-white dark:bg-gray-900 border-r border-gray-200 dark:border-gray-800 shadow-xl flex flex-col overflow-hidden animate-slide-in-left md:relative md:z-auto md:w-80 md:max-w-none md:shrink-0 md:shadow-none md:animate-none md:border-r">

        {/* Header — minimal chrome */}
        <div className="flex items-center gap-2 px-4 py-3 shrink-0 border-b border-gray-100 dark:border-gray-800">
          {canGoBack && (
            <button
              onClick={goBackThingDetail}
              className="p-1.5 rounded-lg text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 hover:text-gray-600 dark:hover:text-gray-300 transition-colors"
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
              <span className="text-xs font-medium text-gray-400 dark:text-gray-500 uppercase tracking-wider">Detail view</span>
            ) : detailLoading ? (
              <div className="h-4 w-24 bg-gray-200 dark:bg-gray-700 rounded animate-pulse" />
            ) : (
              <span className="text-sm text-gray-400">Not found</span>
            )}
          </div>
          <button
            onClick={closeThingDetail}
            className="p-1.5 rounded-lg text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 hover:text-gray-600 dark:hover:text-gray-300 transition-colors"
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
            <div className="p-5 space-y-4 animate-pulse">
              <div className="flex gap-2">
                <div className="h-5 w-16 bg-gray-200 dark:bg-gray-700 rounded-full" />
                <div className="h-5 w-20 bg-gray-200 dark:bg-gray-700 rounded-full" />
              </div>
              <div className="h-8 bg-gray-200 dark:bg-gray-700 rounded w-3/4" />
              <div className="h-4 bg-gray-200 dark:bg-gray-700 rounded w-1/2" />
              <div className="h-4 bg-gray-200 dark:bg-gray-700 rounded w-5/6" />
              <div className="h-4 bg-gray-200 dark:bg-gray-700 rounded w-2/3" />
            </div>
          ) : thing ? (
            <div className="flex flex-col">

              {/* ── Editorial Header ──────────────────────────────── */}
              <div className="px-5 pt-5 pb-4 space-y-3">
                {/* Type badge + created date */}
                <div className="flex items-center gap-2 flex-wrap">
                  {thing.type_hint && (
                    <span className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold capitalize ${colors.bg} ${colors.text} ${colors.dark}`}>
                      {typeIcon(thing.type_hint, thingTypes)} {thing.type_hint}
                    </span>
                  )}
                  <span className="text-xs text-gray-400 dark:text-gray-500">
                    {formatTimestamp(thing.created_at)}
                  </span>
                  <span className="text-xs text-gray-400 dark:text-gray-500">
                    {importanceLabel(thing.importance)}
                  </span>
                </div>

                {/* Headline title */}
                <h2 className="font-bold text-gray-900 dark:text-white leading-tight" style={{ fontSize: '1.75rem' }}>
                  {thing.title}
                </h2>

                {/* Check-in date */}
                {thing.checkin_date && (() => {
                  const overdue = isOverdue(thing.checkin_date)
                  const dateLabel = formatDate(thing.checkin_date)
                  return (
                    <div className="flex items-center gap-1.5 text-sm">
                      <span className="shrink-0">📅</span>
                      <span className={overdue ? 'text-red-500 font-semibold' : 'text-gray-600 dark:text-gray-300'}>
                        {overdue ? '⚠ ' : ''}{dateLabel}
                      </span>
                    </div>
                  )
                })()}

                {/* Relationship avatars — inline chips below headline */}
                {connectedNodes.length > 0 && (
                  <div className="flex items-center gap-1.5 flex-wrap">
                    <span className="text-xs text-gray-400 dark:text-gray-500">Connected to</span>
                    {connectedNodes.slice(0, 5).map(node => {
                      const nc = typeColor(node.typeHint)
                      return (
                        <button
                          key={node.id}
                          onClick={() => navigateThingDetail(node.id)}
                          className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs ${nc.bg} ${nc.text} ${nc.dark} hover:opacity-80 transition-opacity`}
                        >
                          <span>{typeIcon(node.typeHint, thingTypes)}</span>
                          <span className="truncate max-w-[6rem]">{node.title}</span>
                        </button>
                      )
                    })}
                    {connectedNodes.length > 5 && (
                      <span className="text-xs text-gray-400 dark:text-gray-500">+{connectedNodes.length - 5} more</span>
                    )}
                  </div>
                )}
              </div>

              {/* ── Curator Notes ────────────────────────────────── */}
              {notesValue != null && (
                <section className="px-5 py-4 bg-gray-50 dark:bg-gray-800/50">
                  <h3 className="text-[0.6875rem] font-semibold text-gray-400 dark:text-gray-500 uppercase tracking-[0.05em] mb-2">
                    Curator Notes
                  </h3>
                  <p className="text-gray-700 dark:text-gray-200 leading-relaxed" style={{ fontSize: '0.875rem', lineHeight: '1.6' }}>
                    {typeof notesValue === 'string' ? notesValue : JSON.stringify(notesValue)}
                  </p>
                </section>
              )}

              {/* ── Preference patterns or data fields ───────────── */}
              {thing.type_hint === 'preference' ? (
                <div className="px-5 py-4">
                  <PreferencePatterns thingId={thing.id} data={thing.data} />
                </div>
              ) : otherDataEntries.length > 0 ? (
                <section className="px-5 py-4">
                  <h3 className="text-[0.6875rem] font-semibold text-gray-400 dark:text-gray-500 uppercase tracking-[0.05em] mb-2">
                    Details
                  </h3>
                  <div className="space-y-1.5">
                    {otherDataEntries.map(([key, value]) => (
                      <div key={key} className="text-sm">
                        <span className="font-medium text-gray-500 dark:text-gray-400">{key}:</span>{' '}
                        <span className="text-gray-700 dark:text-gray-300">
                          {typeof value === 'string' ? value : JSON.stringify(value)}
                        </span>
                      </div>
                    ))}
                  </div>
                </section>
              ) : null}

              {/* ── Open Questions ───────────────────────────────── */}
              {thing.open_questions && thing.open_questions.length > 0 && (
                <section className="mx-5 my-2 rounded-xl bg-red-50 dark:bg-red-900/20 border border-red-100 dark:border-red-800/40 p-4">
                  <h3 className="text-[0.6875rem] font-semibold text-red-500 dark:text-red-400 uppercase tracking-[0.05em] mb-2">
                    Open Questions
                  </h3>
                  <ul className="space-y-1.5">
                    {thing.open_questions.map((q, i) => (
                      <li key={i} className="flex items-start gap-2 text-sm text-red-700 dark:text-red-300">
                        <span className="shrink-0 mt-0.5 text-red-400 dark:text-red-500 font-bold">?</span>
                        <span>{q}</span>
                      </li>
                    ))}
                  </ul>
                </section>
              )}

              {/* ── Relationships: 2-col Nodes + Connection Map ──── */}
              {groupedRels.size > 0 && (
                <div className="px-5 py-4 grid grid-cols-2 gap-3">
                  {/* Nodes column */}
                  <div>
                    <h3 className="text-[0.6875rem] font-semibold text-gray-400 dark:text-gray-500 uppercase tracking-[0.05em] mb-2">
                      Nodes
                    </h3>
                    <div className="space-y-1">
                      {parent && (
                        <ThingLink
                          id={parent.id}
                          title={parent.title}
                          typeHint={parent.type_hint}
                          thingTypes={thingTypes}
                          onClick={navigateThingDetail}
                          label="Parent"
                        />
                      )}
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
                      {Array.from(groupedRels.entries()).flatMap(([type, items]) =>
                        items.map(({ rel, otherId }) => {
                          const other = resolveThing(otherId)
                          return other ? (
                            <ThingLink
                              key={rel.id}
                              id={other.id}
                              title={other.title}
                              typeHint={other.type_hint}
                              thingTypes={thingTypes}
                              onClick={navigateThingDetail}
                              label={formatRelType(type)}
                            />
                          ) : null
                        })
                      )}
                    </div>
                  </div>

                  {/* Connection map column */}
                  <div>
                    <h3 className="text-[0.6875rem] font-semibold text-gray-400 dark:text-gray-500 uppercase tracking-[0.05em] mb-2">
                      Connection Map
                    </h3>
                    <div className="rounded-lg overflow-hidden bg-gray-50 dark:bg-gray-800/60" style={{ height: 180 }}>
                      <ConnectionMapSVG
                        centerTitle={thing.title}
                        connectedNodes={connectedNodes}
                      />
                    </div>
                  </div>
                </div>
              )}

              {/* ── Standalone parent / children (no named relationships) ─ */}
              {(parent || children.length > 0) && groupedRels.size === 0 && (
                <div className="px-5 pb-4 space-y-3">
                  {parent && (
                    <div>
                      <h3 className="text-[0.6875rem] font-semibold text-gray-400 dark:text-gray-500 uppercase tracking-[0.05em] mb-1.5">
                        Parent
                      </h3>
                      <ThingLink
                        id={parent.id}
                        title={parent.title}
                        typeHint={parent.type_hint}
                        thingTypes={thingTypes}
                        onClick={navigateThingDetail}
                      />
                    </div>
                  )}
                  {children.length > 0 && (
                    <div>
                      <h3 className="text-[0.6875rem] font-semibold text-gray-400 dark:text-gray-500 uppercase tracking-[0.05em] mb-1.5">
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
                </div>
              )}

              {/* ── Activity Stream ──────────────────────────────── */}
              <section className="px-5 py-4 border-t border-gray-100 dark:border-gray-800">
                <h3 className="text-[0.6875rem] font-semibold text-gray-400 dark:text-gray-500 uppercase tracking-[0.05em] mb-3">
                  Activity Stream
                </h3>
                <ol className="space-y-2.5">
                  {thing.last_referenced && (
                    <li className="flex items-start gap-2.5 text-xs text-gray-500 dark:text-gray-400">
                      <span className="shrink-0 mt-0.5 w-4 h-4 rounded-full bg-indigo-100 dark:bg-indigo-900/40 text-indigo-500 flex items-center justify-center text-[9px]">◯</span>
                      <span>Last discussed {formatTimestamp(thing.last_referenced)}</span>
                    </li>
                  )}
                  {thing.updated_at !== thing.created_at && (
                    <li className="flex items-start gap-2.5 text-xs text-gray-500 dark:text-gray-400">
                      <span className="shrink-0 mt-0.5 w-4 h-4 rounded-full bg-gray-100 dark:bg-gray-800 text-gray-400 flex items-center justify-center text-[9px]">✓</span>
                      <span>Updated {formatTimestamp(thing.updated_at)}</span>
                    </li>
                  )}
                  <li className="flex items-start gap-2.5 text-xs text-gray-500 dark:text-gray-400">
                    <span className="shrink-0 mt-0.5 w-4 h-4 rounded-full bg-gray-100 dark:bg-gray-800 text-gray-400 flex items-center justify-center text-[9px]">+</span>
                    <span>Created {formatTimestamp(thing.created_at)}</span>
                  </li>
                </ol>
              </section>

            </div>
          ) : (
            <div className="p-5 text-sm text-gray-400 dark:text-gray-500 text-center">
              Thing not found
            </div>
          )}
        </div>
      </div>
    </>
  )
}

function ThingLink({
  id, title, typeHint, thingTypes, onClick, label,
}: {
  id: string
  title: string
  typeHint: string | null
  thingTypes: ThingType[]
  onClick: (id: string) => void
  label?: string
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
      {(label ?? typeHint) && (
        <span className="ml-auto text-[10px] text-gray-400 dark:text-gray-400 capitalize shrink-0">
          {label ?? typeHint}
        </span>
      )}
    </button>
  )
}
