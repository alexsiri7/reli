import { apiFetch, BASE } from './api'
import { validateResponse } from './schemas'
import type { ReliState } from './store'
import type { z } from 'zod'

/**
 * Best-effort fetch action for the Zustand store.
 * Handles: set loading → apiFetch → validateResponse → set data → finally clear loading.
 */
export async function simpleFetch<T>(
  endpoint: string,
  schema: z.ZodType<T>,
  dataKey: keyof ReliState,
  set: (partial: Partial<ReliState>) => void,
  loadingKey?: keyof ReliState,
): Promise<void> {
  if (loadingKey) set({ [loadingKey]: true })
  try {
    const res = await apiFetch(`${BASE}${endpoint}`)
    if (!res.ok) return
    const data = validateResponse(schema, await res.json(), endpoint)
    set({ [dataKey]: data })
  } catch {
    // best-effort
  } finally {
    if (loadingKey) set({ [loadingKey]: false })
  }
}
