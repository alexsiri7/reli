import type { Thing, SweepFinding } from '../store'
import { setCacheEntry, getCacheEntry } from './idb'

interface CachedBriefing {
  things: Thing[]
  findings: SweepFinding[]
}

const CACHE_KEY = 'briefing'

export async function cacheBriefing(things: Thing[], findings: SweepFinding[]): Promise<void> {
  await setCacheEntry(CACHE_KEY, { things, findings })
}

export async function getCachedBriefing(): Promise<CachedBriefing | undefined> {
  return getCacheEntry<CachedBriefing>(CACHE_KEY)
}
