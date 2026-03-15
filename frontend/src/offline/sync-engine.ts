import { getPendingOps, removePendingOp, type PendingOp } from './pending-ops'
import { getDB } from './idb'

const MAX_RETRIES = 3

type SyncEventType = 'sync:start' | 'sync:op-ok' | 'sync:op-fail' | 'sync:done'

interface SyncEvent {
  type: SyncEventType
  op?: PendingOp
  remaining?: number
  error?: string
}

type SyncListener = (event: SyncEvent) => void

const listeners = new Set<SyncListener>()
let syncing = false

export function onSyncEvent(listener: SyncListener): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

function emit(event: SyncEvent) {
  for (const listener of listeners) {
    try {
      listener(event)
    } catch {
      // listener errors should not break sync
    }
  }
}

async function updateOpRetries(op: PendingOp, retries: number): Promise<void> {
  const db = await getDB()
  await db.put('pendingOps', { ...op, retries, status: 'failed' })
}

async function replayOp(op: PendingOp): Promise<boolean> {
  const init: RequestInit = { method: op.method }
  if (op.body !== undefined) {
    init.headers = { 'Content-Type': 'application/json' }
    init.body = JSON.stringify(op.body)
  }

  const res = await fetch(op.url, init)

  if (res.ok) return true

  // 4xx: client error, discard (non-retryable)
  if (res.status >= 400 && res.status < 500) return true

  // 5xx: server error, retry up to MAX_RETRIES
  return false
}

/**
 * Replay all pending operations in FIFO order.
 * Called automatically when the browser fires the 'online' event.
 */
export async function syncPendingOps(): Promise<void> {
  if (syncing) return
  syncing = true

  const ops = await getPendingOps()
  if (ops.length === 0) {
    syncing = false
    return
  }

  emit({ type: 'sync:start', remaining: ops.length })

  let remaining = ops.length

  for (const op of ops) {
    try {
      const ok = await replayOp(op)
      if (ok) {
        await removePendingOp(op.id!)
        remaining--
        emit({ type: 'sync:op-ok', op, remaining })
      } else {
        const retries = op.retries + 1
        if (retries >= MAX_RETRIES) {
          // Max retries exceeded — discard
          await removePendingOp(op.id!)
          remaining--
          emit({
            type: 'sync:op-fail',
            op,
            remaining,
            error: `Max retries (${MAX_RETRIES}) exceeded`,
          })
        } else {
          await updateOpRetries(op, retries)
          emit({
            type: 'sync:op-fail',
            op,
            remaining,
            error: `Server error, retry ${retries}/${MAX_RETRIES}`,
          })
        }
      }
    } catch (e) {
      // Network error during replay — stop trying (we might be offline again)
      emit({
        type: 'sync:op-fail',
        op,
        remaining,
        error: String(e),
      })
      break
    }
  }

  emit({ type: 'sync:done', remaining })
  syncing = false
}

/**
 * Install the online event listener to trigger sync automatically.
 * Call once at app startup. Returns a cleanup function.
 */
export function initSyncEngine(): () => void {
  const handler = () => {
    syncPendingOps()
  }

  window.addEventListener('online', handler)

  // If already online and there might be queued ops from a previous session, sync now
  if (navigator.onLine) {
    syncPendingOps()
  }

  return () => {
    window.removeEventListener('online', handler)
  }
}
