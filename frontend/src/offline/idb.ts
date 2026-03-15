import { openDB, type DBSchema, type IDBPDatabase } from 'idb'
import type {
  Thing,
  ThingType,
  Relationship,
  ChatMessage,
} from '../store'

// --- Pending operation types ---

export type PendingOpStatus = 'pending' | 'in_flight' | 'failed'

export interface PendingOp {
  id?: number
  url: string
  method: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
  body?: unknown
  timestamp: string
  status: PendingOpStatus
  retries: number
}

// --- IndexedDB schema ---

export interface ReliDB extends DBSchema {
  things: {
    key: string
    value: Thing
  }
  thingTypes: {
    key: string
    value: ThingType
  }
  relationships: {
    key: string
    value: Relationship
    indexes: {
      by_from_thing_id: string
      by_to_thing_id: string
    }
  }
  chatMessages: {
    key: string | number
    value: ChatMessage
    indexes: {
      by_session_id: string
    }
  }
  pendingOps: {
    key: number
    value: PendingOp
    autoIncrement: true
  }
}

const DB_NAME = 'reli'
const DB_VERSION = 1

let dbPromise: Promise<IDBPDatabase<ReliDB>> | null = null

export function getDB(): Promise<IDBPDatabase<ReliDB>> {
  if (!dbPromise) {
    dbPromise = openDB<ReliDB>(DB_NAME, DB_VERSION, {
      upgrade(db) {
        db.createObjectStore('things', { keyPath: 'id' })
        db.createObjectStore('thingTypes', { keyPath: 'id' })

        const relStore = db.createObjectStore('relationships', {
          keyPath: 'id',
        })
        relStore.createIndex('by_from_thing_id', 'from_thing_id')
        relStore.createIndex('by_to_thing_id', 'to_thing_id')

        const chatStore = db.createObjectStore('chatMessages', {
          keyPath: 'id',
        })
        chatStore.createIndex('by_session_id', 'session_id')

        db.createObjectStore('pendingOps', {
          keyPath: 'id',
          autoIncrement: true,
        })
      },
    })
  }
  return dbPromise
}

// --- Generic CRUD helpers ---

export async function getAll<S extends 'things' | 'thingTypes' | 'relationships' | 'chatMessages'>(
  store: S,
): Promise<ReliDB[S]['value'][]> {
  const db = await getDB()
  return db.getAll(store)
}

export async function getByKey<S extends 'things' | 'thingTypes' | 'relationships' | 'chatMessages'>(
  store: S,
  key: ReliDB[S]['key'],
): Promise<ReliDB[S]['value'] | undefined> {
  const db = await getDB()
  return db.get(store, key)
}

export async function put<S extends 'things' | 'thingTypes' | 'relationships' | 'chatMessages'>(
  store: S,
  value: ReliDB[S]['value'],
): Promise<ReliDB[S]['key']> {
  const db = await getDB()
  return db.put(store, value)
}

export async function del<S extends 'things' | 'thingTypes' | 'relationships' | 'chatMessages'>(
  store: S,
  key: ReliDB[S]['key'],
): Promise<void> {
  const db = await getDB()
  return db.delete(store, key)
}

// --- Indexed queries ---

export async function getRelationshipsByFrom(fromThingId: string): Promise<Relationship[]> {
  const db = await getDB()
  return db.getAllFromIndex('relationships', 'by_from_thing_id', fromThingId)
}

export async function getRelationshipsByTo(toThingId: string): Promise<Relationship[]> {
  const db = await getDB()
  return db.getAllFromIndex('relationships', 'by_to_thing_id', toThingId)
}

export async function getChatMessagesBySession(sessionId: string): Promise<ChatMessage[]> {
  const db = await getDB()
  return db.getAllFromIndex('chatMessages', 'by_session_id', sessionId)
}

// --- Pending ops queue ---

export async function enqueuePendingOp(op: Omit<PendingOp, 'id'>): Promise<number> {
  const db = await getDB()
  return db.add('pendingOps', op as PendingOp)
}

export async function getAllPendingOps(): Promise<PendingOp[]> {
  const db = await getDB()
  return db.getAll('pendingOps')
}

export async function deletePendingOp(id: number): Promise<void> {
  const db = await getDB()
  return db.delete('pendingOps', id)
}

export async function clearPendingOps(): Promise<void> {
  const db = await getDB()
  return db.clear('pendingOps')
}

// --- Bulk operations ---

export async function putAll<S extends 'things' | 'thingTypes' | 'relationships' | 'chatMessages'>(
  store: S,
  values: ReliDB[S]['value'][],
): Promise<void> {
  const db = await getDB()
  const tx = db.transaction(store, 'readwrite')
  for (const value of values) {
    tx.store.put(value)
  }
  await tx.done
}

export async function clearStore(store: 'things' | 'thingTypes' | 'relationships' | 'chatMessages' | 'pendingOps'): Promise<void> {
  const db = await getDB()
  return db.clear(store)
}
