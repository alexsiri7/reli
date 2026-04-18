import type { Thing, SweepFinding, LearnedPreference } from '../store'
import { setCacheEntry, getCacheEntry } from './idb'

interface CachedBriefing {
  things: Thing[]
  findings: SweepFinding[]
  learnedPreferences: LearnedPreference[]
}

const CACHE_KEY = 'briefing'

export async function cacheBriefing(
  things: Thing[],
  findings: SweepFinding[],
  learnedPreferences: LearnedPreference[],
): Promise<void> {
  await setCacheEntry(CACHE_KEY, { things, findings, learnedPreferences })
}

export async function getCachedBriefing(): Promise<CachedBriefing | undefined> {
  return getCacheEntry<CachedBriefing>(CACHE_KEY)
}
