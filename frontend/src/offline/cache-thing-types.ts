import type { ThingType } from '../store'
import { putAll, getAll, clearStore } from './idb'

/**
 * Cache all thing types to IndexedDB after a successful API fetch.
 * Replaces the entire store contents to stay in sync.
 */
export async function cacheThingTypes(thingTypes: ThingType[]): Promise<void> {
  await clearStore('thingTypes')
  await putAll('thingTypes', thingTypes)
}

/**
 * Retrieve all cached thing types from IndexedDB.
 */
export async function getCachedThingTypes(): Promise<ThingType[]> {
  return getAll('thingTypes')
}
