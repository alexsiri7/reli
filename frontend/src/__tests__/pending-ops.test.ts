import 'fake-indexeddb/auto'
import { describe, it, expect, beforeEach } from 'vitest'
import { queueOperation, getPendingOps, removePendingOp, getPendingCount } from '../offline/pending-ops'
import { clearPendingOps } from '../offline/idb'

beforeEach(async () => {
  await clearPendingOps()
})

describe('pending-ops', () => {
  it('returns ops in FIFO order', async () => {
    await queueOperation('/a', 'POST')
    await queueOperation('/b', 'POST')
    const ops = await getPendingOps()
    expect(ops[0]!.url).toBe('/a')
    expect(ops[1]!.url).toBe('/b')
  })

  it('removePendingOp removes only the target op', async () => {
    const id1 = await queueOperation('/first', 'POST')
    await queueOperation('/second', 'POST')
    await removePendingOp(id1)
    const remaining = await getPendingOps()
    expect(remaining).toHaveLength(1)
    expect(remaining[0]!.url).toBe('/second')
  })

  it('clearPendingOps removes all', async () => {
    await queueOperation('/a', 'POST')
    await queueOperation('/b', 'POST')
    await queueOperation('/c', 'POST')
    await clearPendingOps()
    const count = await getPendingCount()
    expect(count).toBe(0)
  })
})
