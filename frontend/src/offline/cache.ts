import type { Thing, ThingType, Relationship, SweepFinding, LearnedPreference } from '../generated/api-types'
import type { CalendarEvent } from '../types'
import { putAll, getAll, clearStore, getRelationshipsByFrom, getRelationshipsByTo, setCacheEntry, getCacheEntry } from './idb'

// ── Simple clear-and-replace caches (things, thingTypes) ────────────────────

type CrudStore = 'things' | 'thingTypes'

function createCache<T>(storeName: CrudStore) {
  return {
    cache: async (items: T[]) => {
      await clearStore(storeName)
      // @ts-expect-error putAll generic type mismatch
      await putAll(storeName, items)
    },
    getCached: () => getAll(storeName) as Promise<T[]>,
  }
}

export const { cache: cacheThings, getCached: getCachedThings } = createCache<Thing>('things')
export const { cache: cacheThingTypes, getCached: getCachedThingTypes } = createCache<ThingType>('thingTypes')

// ── Relationships (upsert, bi-directional index lookup) ─────────────────────

export async function cacheRelationships(relationships: Relationship[]): Promise<void> {
  if (relationships.length === 0) return
  await putAll('relationships', relationships)
}

export async function getCachedRelationships(thingId: string): Promise<Relationship[]> {
  const [fromRels, toRels] = await Promise.all([
    getRelationshipsByFrom(thingId),
    getRelationshipsByTo(thingId),
  ])
  const byId = new Map([...fromRels, ...toRels].map(r => [r.id, r]))
  return [...byId.values()]
}

// ── Briefing (KV cache, composite value) ────────────────────────────────────

interface CachedBriefing {
  things: Thing[]
  findings: SweepFinding[]
  learnedPreferences: LearnedPreference[]
}

export async function cacheBriefing(
  things: Thing[],
  findings: SweepFinding[],
  learnedPreferences: LearnedPreference[],
): Promise<void> {
  await setCacheEntry('briefing', { things, findings, learnedPreferences })
}

export async function getCachedBriefing(): Promise<CachedBriefing | undefined> {
  return getCacheEntry<CachedBriefing>('briefing')
}

// ── Calendar events (KV cache) ──────────────────────────────────────────────

export async function cacheCalendarEvents(events: CalendarEvent[]): Promise<void> {
  await setCacheEntry('calendarEvents', events)
}

export async function getCachedCalendarEvents(): Promise<CalendarEvent[]> {
  return (await getCacheEntry<CalendarEvent[]>('calendarEvents')) ?? []
}
