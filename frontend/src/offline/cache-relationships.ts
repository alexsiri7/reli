import type { Relationship } from '../generated/api-types'
import { putAll, getRelationshipsByFrom, getRelationshipsByTo } from './idb'

/**
 * Cache relationships for a thing after loading its detail view.
 * Uses putAll so duplicates are upserted by key (relationship id).
 */
export async function cacheRelationships(relationships: Relationship[]): Promise<void> {
  if (relationships.length === 0) return
  await putAll('relationships', relationships)
}

/**
 * Retrieve cached relationships for a given thing (both directions).
 */
export async function getCachedRelationships(thingId: string): Promise<Relationship[]> {
  const [fromRels, toRels] = await Promise.all([
    getRelationshipsByFrom(thingId),
    getRelationshipsByTo(thingId),
  ])
  return [...new Map([...fromRels, ...toRels].map(r => [r.id, r])).values()]
}
