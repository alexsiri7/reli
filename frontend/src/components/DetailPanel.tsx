import { useEffect, useMemo } from 'react'
import { useShallow } from 'zustand/react/shallow'
import { useStore } from '../store'
import type { Relationship, ThingType } from '../store'
import { typeIcon, formatTimestamp, formatDate, isOverdue, importanceLabel } from '../utils'
import { PreferencePatterns } from './PreferencePatterns'

const RELATIONSHIP_OPPOSITES: Record<string, string> = {
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

const CONTACT_DATA_KEYS = new Set(['email', 'phone', 'role', 'title', 'position'])

const REL_DIRECTION = '→'

/** Map type_hint to design-system accent color classes */
function typeColorClasses(typeHint: string | null): { bg: string; text: string } {
  switch (typeHint?.toLowerCase()) {
    case 'project':
      return { bg: 'bg-projects/15', text: 'text-projects' }
    case 'event':
      return { bg: 'bg-events/15', text: 'text-events' }
    case 'person':
      return { bg: 'bg-people/15', text: 'text-people' }
    case 'idea':
      return { bg: 'bg-ideas/15', text: 'text-ideas' }
    default:
      return { bg: 'bg-primary/15', text: 'text-primary' }
  }
}

export function DetailPanel() {
  const {
    detailThingId, detailThing, detailRelationships, detailHistory,
    detailLoading, closeThingDetail, navigateThingDetail, goBackThingDetail,
    things, thingTypes, nudges, openChatWithContext,
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
    nudges: s.nudges,
    openChatWithContext: s.openChatWithContext,
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
    const thingIds = new Set(things.map(t => t.id))
    const groups = new Map<string, { rel: Relationship; otherId: string; direction: string }[]>()
    for (const rel of detailRelationships) {
      // parent-of/child-of shown in dedicated Parent/Children sections
      if (rel.relationship_type === 'parent-of' || rel.relationship_type === 'child-of') continue
      const isFrom = rel.from_thing_id === detailThingId
      const otherId = isFrom ? rel.to_thing_id : rel.from_thing_id
      // Filter out relationships pointing to non-existent Things (orphans)
      if (!thingIds.has(otherId)) continue
      const rawType = rel.relationship_type
      const displayType = isFrom ? rawType : (RELATIONSHIP_OPPOSITES[rawType] ?? rawType)
      if (!groups.has(displayType)) groups.set(displayType, [])
      groups.get(displayType)!.push({ rel, otherId, direction: REL_DIRECTION })
    }
    return groups
  }, [detailRelationships, detailThingId, things])

  // Parent/children derived from relationships (parent-of type) — must be before early return
  const children = useMemo(() => {
    if (!detailThing || !detailRelationships) return []
    const childIds = detailRelationships
      .filter(r => r.from_thing_id === detailThing.id && r.relationship_type === 'parent-of')
      .map(r => r.to_thing_id)
    return things.filter(t => childIds.includes(t.id))
  }, [detailThing, detailRelationships, things])
  const parent = useMemo(() => {
    if (!detailThing || !detailRelationships) return null
    const parentRel = detailRelationships.find(
      r => r.to_thing_id === detailThing.id && r.relationship_type === 'parent-of'
    )
    return parentRel ? things.find(t => t.id === parentRel.from_thing_id) ?? null : null
  }, [detailThing, detailRelationships, things])

  const suggestion = nudges.find(n => n.thing_id === detailThingId) ?? null

  if (!detailThingId) {
    return (
      <div className="hidden md:flex w-80 shrink-0 flex-col items-center justify-center gap-3 bg-surface dark:bg-surface text-center px-6">
        <svg className="w-12 h-12 text-on-surface-variant/30" viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
          <rect x="6" y="10" width="36" height="28" rx="3" stroke="currentColor" strokeWidth="2" fill="none"/>
          <line x1="6" y1="18" x2="42" y2="18" stroke="currentColor" strokeWidth="2"/>
          <rect x="12" y="23" width="10" height="3" rx="1" fill="currentColor" opacity="0.3"/>
          <rect x="12" y="29" width="24" height="2" rx="1" fill="currentColor" opacity="0.2"/>
          <rect x="12" y="33" width="18" height="2" rx="1" fill="currentColor" opacity="0.2"/>
        </svg>
        <p className="text-sm text-on-surface-variant/50">
          Click any Thing in the sidebar to see its details and relationships.
        </p>
      </div>
    )
  }

  const thing = detailThing
  const canGoBack = detailHistory.length > 0

  // Resolve a Thing by ID — check local store first, fall back to minimal display
  const resolveThing = (id: string) => things.find(t => t.id === id)

  // Separate notes from other data entries
  const notes = thing?.data?.notes != null ? String(thing.data.notes) : null
  const dataEntries = thing?.data
    ? Object.entries(thing.data).filter(([key]) =>
        key !== 'notes' &&
        key !== 'agenda_items' &&
        !(thing.type_hint === 'person' && CONTACT_DATA_KEYS.has(key))
      )
    : []

  const formatRelType = (type: string) =>
    type.replace(/_/g, ' ').replace(/^\w/, c => c.toUpperCase())

  const colors = typeColorClasses(thing?.type_hint ?? null)
  const checkinOverdue = thing?.checkin_date ? isOverdue(thing.checkin_date) : false

  return (
    <>
      {/* Backdrop for mobile — glassmorphism */}
      <div
        onClick={closeThingDetail}
        className="fixed inset-0 z-50 bg-canvas/60 backdrop-blur-sm md:hidden"
      />

      {/* Panel — desktop: inline flex child on left; mobile: fixed overlay from left */}
      <div className="fixed left-0 top-0 bottom-0 z-50 w-full max-w-md bg-surface shadow-xl flex flex-col overflow-hidden animate-slide-in-left md:relative md:z-auto md:w-80 md:max-w-none md:shrink-0 md:shadow-none md:animate-none">
        {/* Header — minimal toolbar */}
        <div className="flex items-center gap-2 px-4 py-3 shrink-0">
          {canGoBack && (
            <button
              onClick={goBackThingDetail}
              className="p-1.5 rounded-lg text-on-surface-variant hover:bg-surface-container-high hover:text-on-surface transition-colors"
              aria-label="Go back"
              title="Go back"
            >
              <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
              </svg>
            </button>
          )}
          <div className="flex-1 min-w-0">
            {!thing && !detailLoading && (
              <span className="text-body text-on-surface-variant">Not found</span>
            )}
          </div>
          <button
            onClick={closeThingDetail}
            className="p-1.5 rounded-lg text-on-surface-variant hover:bg-surface-container-high hover:text-on-surface transition-colors"
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
            <div className="p-6 space-y-4 animate-pulse">
              <div className="h-3 bg-surface-container-high rounded w-24" />
              <div className="h-7 bg-surface-container-high rounded w-3/4" />
              <div className="h-4 bg-surface-container-high rounded w-1/2" />
              <div className="h-4 bg-surface-container-high rounded w-5/6" />
            </div>
          ) : thing ? (
            <div className="px-6 pb-6 space-y-6">
              {/* Type badge + created date */}
              <div className="flex items-center gap-3">
                {thing.type_hint && (
                  <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-label font-semibold capitalize ${colors.bg} ${colors.text}`}>
                    {typeIcon(thing.type_hint, thingTypes)} {thing.type_hint}
                  </span>
                )}
                <span className="text-label text-on-surface-variant">
                  {formatTimestamp(thing.created_at)}
                </span>
              </div>

              {/* Title — editorial headline */}
              <h2 className="text-headline font-bold text-on-surface leading-tight">
                {thing.title}
              </h2>

              {/* Importance + check-in date */}
              <div className="flex items-center gap-3 text-body text-on-surface-variant">
                <span>{importanceLabel(thing.importance)}</span>
                {thing.checkin_date && (
                  <span className={`inline-flex items-center gap-1 ${checkinOverdue ? 'text-ideas font-semibold' : ''}`}>
                    <span className="shrink-0">{checkinOverdue ? '\u26a0' : '\ud83d\udcc5'}</span>
                    <span>{formatDate(thing.checkin_date)}</span>
                  </span>
                )}
              </div>

              {/* ── CONTACT CARD (person type) ── */}
              {thing.type_hint === 'person' && (
                <ContactCard title={thing.title} data={thing.data} />
              )}

              {/* ── AGENDA (event / meeting type) ── */}
              {(thing.type_hint === 'event' || thing.type_hint === 'meeting') &&
               Array.isArray(thing.data?.agenda_items) &&
               (thing.data!.agenda_items as string[]).length > 0 && (
                <section className="space-y-3">
                  <h3 className="text-label font-semibold text-on-surface-variant tracking-widest">Agenda</h3>
                  <div className="rounded-xl bg-surface-container-high p-4">
                    <ul className="space-y-3">
                      {(thing.data!.agenda_items as string[]).map((item, i) => (
                        <li key={i} className="flex items-start gap-3">
                          <span className="w-1.5 h-1.5 rounded-full bg-primary mt-2 flex-shrink-0" />
                          <span className="text-body text-on-surface">{item}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                </section>
              )}

              {/* ── NOTES ── */}
              {thing.type_hint === 'preference' ? (
                <PreferencePatterns thingId={thing.id} data={thing.data} />
              ) : notes ? (
                <section className="space-y-3">
                  <h3 className="text-label font-semibold text-on-surface-variant tracking-widest">Notes</h3>
                  <div className="rounded-xl bg-surface-container-high p-4">
                    <p className="text-body text-on-surface whitespace-pre-wrap">{notes}</p>
                  </div>
                </section>
              ) : null}

              {/* Other data fields (non-notes) */}
              {dataEntries.length > 0 && thing.type_hint !== 'preference' && (
                <section className="space-y-3">
                  <h3 className="text-label font-semibold text-on-surface-variant tracking-widest">Details</h3>
                  <div className="rounded-xl bg-surface-container-high p-4 space-y-2">
                    {dataEntries.map(([key, value]) => (
                      <div key={key} className="text-body">
                        <span className="font-medium text-on-surface-variant">{key}:</span>{' '}
                        <span className="text-on-surface">
                          {typeof value === 'string' ? value : JSON.stringify(value)}
                        </span>
                      </div>
                    ))}
                  </div>
                </section>
              )}

              {/* ── OPEN QUESTIONS ── (rose/ideas accent) */}
              {thing.open_questions && thing.open_questions.length > 0 && (
                <section className="space-y-3">
                  <h3 className="text-label font-semibold text-ideas tracking-widest">Open Questions</h3>
                  <div className="rounded-xl bg-ideas/10 p-4 space-y-2">
                    {thing.open_questions.map((q, i) => (
                      <div key={i} className="flex items-start gap-2 text-body">
                        <span className="shrink-0 text-ideas font-bold mt-0.5">?</span>
                        <span className="text-on-surface">{q}</span>
                      </div>
                    ))}
                  </div>
                </section>
              )}

              {/* ── RELI SUGGESTION ── */}
              {suggestion && (
                <div className="rounded-xl bg-surface-container-highest/30 p-4 border-l-4 border-secondary space-y-3">
                  <div className="flex items-start gap-3">
                    <span className="shrink-0 text-secondary text-lg">✨</span>
                    <div className="min-w-0">
                      <p className="text-label font-semibold text-secondary tracking-widest uppercase mb-1">Reli Suggestion</p>
                      <p className="text-body text-on-surface-variant">{suggestion.message}</p>
                    </div>
                  </div>
                  <button
                    onClick={() => openChatWithContext(thing.id, thing.title)}
                    className="w-full px-4 py-2 text-xs font-bold uppercase tracking-widest text-secondary border border-secondary/30 rounded-lg hover:bg-secondary/10 transition-colors"
                  >
                    {suggestion.primary_action_label ?? 'Prepare Now'}
                  </button>
                </div>
              )}

              {/* ── PARENT ── */}
              {parent && (
                <section className="space-y-3">
                  <h3 className="text-label font-semibold text-on-surface-variant tracking-widest">Parent</h3>
                  <ThingLink
                    id={parent.id}
                    title={parent.title}
                    typeHint={parent.type_hint}
                    thingTypes={thingTypes}
                    onClick={navigateThingDetail}
                  />
                </section>
              )}

              {/* ── CHILDREN ── */}
              {children.length > 0 && (
                <section className="space-y-3">
                  <h3 className="text-label font-semibold text-on-surface-variant tracking-widest">
                    Children ({children.length})
                  </h3>
                  <div className="space-y-1">
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
                </section>
              )}

              {/* ── RELATIONSHIPS ── */}
              {groupedRels.size > 0 && (
                <section className="space-y-3">
                  <h3 className="text-label font-semibold text-on-surface-variant tracking-widest">Relationships</h3>
                  <div className="space-y-4">
                    {Array.from(groupedRels.entries()).map(([type, items]) => (
                      <div key={type} className="space-y-1">
                        <p className="text-label text-on-surface-variant italic">
                          {formatRelType(type)}
                        </p>
                        {items.map(({ rel, otherId, direction }) => {
                          const other = resolveThing(otherId)
                          return (
                            <div key={rel.id} className="flex items-center gap-1.5">
                              <span className="text-on-surface-variant text-xs shrink-0">{direction}</span>
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
                                  className="text-body text-primary hover:underline truncate"
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
                </section>
              )}

              {/* Timestamps footer */}
              <div className="space-y-1 pt-4">
                <p className="text-label text-on-surface-variant">
                  Created {formatTimestamp(thing.created_at)}
                </p>
                {thing.updated_at !== thing.created_at && (
                  <p className="text-label text-on-surface-variant">
                    Updated {formatTimestamp(thing.updated_at)}
                  </p>
                )}
                {thing.last_referenced && (
                  <p className="text-label text-on-surface-variant">
                    Last discussed {formatTimestamp(thing.last_referenced)}
                  </p>
                )}
              </div>
            </div>
          ) : (
            <div className="p-6 text-body text-on-surface-variant text-center">
              Thing not found
            </div>
          )}
        </div>
      </div>
    </>
  )
}

function ContactCard({ title, data }: { title: string; data: Record<string, unknown> | null }) {
  const email = data?.email != null ? String(data.email) : null
  const phone = data?.phone != null ? String(data.phone) : null
  const rawRole = data?.role ?? data?.title ?? data?.position ?? null
  const role = rawRole != null ? String(rawRole) : null
  const initials = title
    .split(/\s+/)
    .filter(Boolean)
    .map(w => w[0]!.toUpperCase())
    .slice(0, 2)
    .join('')

  return (
    <div className="rounded-xl bg-surface-container-highest/30 p-6 border border-people/20 flex flex-col items-center text-center gap-3">
      <div className="w-16 h-16 rounded-full bg-people/20 flex items-center justify-center text-people font-bold text-xl ring-2 ring-people/20">
        {initials}
      </div>
      <div>
        <p className="text-body font-bold text-on-surface">{title}</p>
        {role && <p className="text-label text-on-surface-variant mt-0.5">{role}</p>}
      </div>
      {(email || phone) && (
        <div className="flex gap-2">
          {email && (
            <button
              aria-label="Send Email"
              onClick={() => window.open(`mailto:${email}`)}
              className="p-2 rounded-lg bg-surface-container-highest text-people hover:bg-people hover:text-on-primary transition-colors"
            >
              <svg xmlns="http://www.w3.org/2000/svg" className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <rect x="2" y="4" width="20" height="16" rx="2"/>
                <path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7"/>
              </svg>
            </button>
          )}
          {phone && (
            <button
              aria-label="Schedule Call"
              onClick={() => window.open(`tel:${phone}`)}
              className="p-2 rounded-lg bg-surface-container-highest text-people hover:bg-people hover:text-on-primary transition-colors"
            >
              <svg xmlns="http://www.w3.org/2000/svg" className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07A19.5 19.5 0 0 1 4.69 12a19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 3.6 1.27h3a2 2 0 0 1 2 1.72c.127.96.361 1.903.7 2.81a2 2 0 0 1-.45 2.11L7.91 8.92a16 16 0 0 0 6.17 6.17l.92-.95a2 2 0 0 1 2.11-.45c.907.339 1.85.573 2.81.7A2 2 0 0 1 21.92 16.92z"/>
              </svg>
            </button>
          )}
        </div>
      )}
    </div>
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
      className="flex items-center gap-2 w-full text-left px-3 py-1.5 rounded-lg hover:bg-surface-container-high transition-colors group"
    >
      <span className="text-sm shrink-0">{typeIcon(typeHint, thingTypes)}</span>
      <span className="text-body text-on-surface group-hover:text-primary truncate transition-colors">
        {title}
      </span>
      {typeHint && (
        <span className="ml-auto text-label text-on-surface-variant capitalize shrink-0">
          {typeHint}
        </span>
      )}
    </button>
  )
}
