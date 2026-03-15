import { queueOperation } from './pending-ops'
import type { PendingOp } from './idb'

/**
 * A fetch wrapper for mutations that queues operations when offline.
 *
 * When online: performs the fetch normally and returns the response.
 * When offline: queues the operation to IDB and returns a synthetic
 * Response with status 202 (Accepted) so callers can optimistically
 * handle the result.
 */
export async function mutationFetch(
  url: string,
  init: RequestInit & { method: PendingOp['method'] },
): Promise<Response> {
  if (navigator.onLine) {
    return fetch(url, init)
  }

  // Parse body for storage — queueOperation stores the parsed object
  let body: unknown
  if (init.body && typeof init.body === 'string') {
    try {
      body = JSON.parse(init.body)
    } catch {
      body = init.body
    }
  }

  await queueOperation(url, init.method, body)

  // Return a synthetic "queued" response
  return new Response(JSON.stringify({ queued: true }), {
    status: 202,
    statusText: 'Accepted (queued for sync)',
    headers: { 'Content-Type': 'application/json' },
  })
}
