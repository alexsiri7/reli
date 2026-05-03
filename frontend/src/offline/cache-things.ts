import type { Thing } from '../generated/api-types'
import type { TypeHint } from '../utils'
import { putAll, getAll, clearStore } from './idb'

/**
 * Cache all things to IndexedDB after a successful API fetch.
 * Replaces the entire store contents to stay in sync.
 */
export async function cacheThings(things: Thing[]): Promise<void> {
  await clearStore('things')
  await putAll('things', things)
}

/**
 * Retrieve all cached things from IndexedDB.
 */
export async function getCachedThings(): Promise<Thing[]> {
  return getAll('things')
}

/**
 * Retrieve cached things filtered by type_hint.
 */
export async function getCachedThingsByType(typeHint: TypeHint): Promise<Thing[]> {
  const all = await getAll('things')
  return all.filter(t => t.type_hint === typeHint)
}
