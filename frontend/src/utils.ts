import type { ThingType, TypeHint } from './store'
import { useStore } from './store'

const FALLBACK_ICONS: Record<string, string> = {
  task: '📋',
  note: '📝',
  project: '📁',
  idea: '💡',
  goal: '🎯',
  journal: '📓',
  person: '👤',
  place: '📍',
  event: '📅',
  concept: '🧠',
  reference: '🔗',
}

export function typeIcon(hint: TypeHint | null | undefined, thingTypes?: ThingType[]): string {
  if (!hint) return '📌'
  const key = hint.toLowerCase()
  // Look up from DB-backed types first
  const types = thingTypes ?? useStore.getState().thingTypes
  const match = types.find(t => t.name === key)
  if (match) return match.icon
  return FALLBACK_ICONS[key] ?? '📌'
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return ''
  const d = new Date(iso)
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const target = new Date(d)
  target.setHours(0, 0, 0, 0)
  const diff = Math.round((target.getTime() - today.getTime()) / 86400000)
  if (diff === 0) return 'Today'
  if (diff === 1) return 'Tomorrow'
  if (diff === -1) return 'Yesterday'
  if (diff < 0) return `${Math.abs(diff)}d overdue`
  if (diff < 7) return `In ${diff}d`
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

const PRIORITY_LABELS: Record<number, string> = {
  1: '🔴 Critical',
  2: '🟠 High',
  3: '🟡 Medium',
  4: '🔵 Low',
  5: '⚪ None',
}

export function priorityLabel(p: number): string {
  return PRIORITY_LABELS[p] ?? `Priority ${p}`
}

export function formatTimestamp(iso: string | null | undefined): string {
  if (!iso) return ''
  return new Date(iso).toLocaleString(undefined, {
    month: 'short', day: 'numeric', year: 'numeric',
    hour: 'numeric', minute: '2-digit',
  })
}

export function isOverdue(iso: string | null | undefined): boolean {
  if (!iso) return false
  const d = new Date(iso)
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  return d < today
}
