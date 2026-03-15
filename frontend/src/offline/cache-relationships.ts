import type { Relationship } from '../store'
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
  // Deduplicate in case a relationship references the same thing in both directions
  const seen = new Set<string>()
  const result: Relationship[] = []
  for (const rel of [...fromRels, ...toRels]) {
    if (!seen.has(rel.id)) {
      seen.add(rel.id)
      result.push(rel)
    }
  }
  return result
}
