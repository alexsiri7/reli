import {
  enqueuePendingOp,
  getAllPendingOps,
  deletePendingOp,
  type PendingOp,
} from './idb'

export type { PendingOp }

/**
 * Queue an API operation to be replayed when back online.
 */
export async function queueOperation(
  url: string,
  method: PendingOp['method'],
  body?: unknown,
): Promise<number> {
  return enqueuePendingOp({
    url,
    method,
    body,
    timestamp: new Date().toISOString(),
    status: 'pending',
    retries: 0,
  })
}

/**
 * Get all pending operations in FIFO order (by auto-increment id).
 */
export async function getPendingOps(): Promise<PendingOp[]> {
  return getAllPendingOps()
}

/**
 * Remove a completed or permanently-failed operation from the queue.
 */
export async function removePendingOp(id: number): Promise<void> {
  return deletePendingOp(id)
}

/**
 * Get the number of pending operations.
 */
export async function getPendingCount(): Promise<number> {
  const ops = await getAllPendingOps()
  return ops.length
}
