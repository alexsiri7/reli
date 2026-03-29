import type { ThingType, TypeHint } from './store'

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
  preference: '⚙️',
}

export function typeIcon(hint: TypeHint | null | undefined, thingTypes?: ThingType[]): string {
  if (!hint) return '📌'
  const key = hint.toLowerCase()
  // Look up from DB-backed types if provided
  if (thingTypes) {
    const match = thingTypes.find(t => t.name === key)
    if (match) return match.icon
  }
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

const IMPORTANCE_LABELS: Record<number, string> = {
  0: '🔴 Critical',
  1: '🟠 High',
  2: '🟡 Medium',
  3: '🔵 Low',
  4: '⚪ Backlog',
}

export function importanceLabel(p: number): string {
  return IMPORTANCE_LABELS[p] ?? `Importance ${p}`
}

/** @deprecated Use importanceLabel instead */
export function priorityLabel(p: number): string {
  return importanceLabel(p)
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
