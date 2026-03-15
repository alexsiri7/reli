import type { CalendarEvent } from '../store'
import { setCacheEntry, getCacheEntry } from './idb'

const CACHE_KEY = 'calendarEvents'

export async function cacheCalendarEvents(events: CalendarEvent[]): Promise<void> {
  await setCacheEntry(CACHE_KEY, events)
}

export async function getCachedCalendarEvents(): Promise<CalendarEvent[]> {
  return (await getCacheEntry<CalendarEvent[]>(CACHE_KEY)) ?? []
}
