import type { AppliedChanges } from '../types'

export function preferenceConfidenceLabel(data: unknown): string {
  if (!data || typeof data !== 'object') return ''
  const d = data as Record<string, unknown>
  if (typeof d.confidence === 'number') {
    const c = d.confidence as number
    if (c >= 0.7) return 'strong'
    if (c >= 0.5) return 'moderate'
    return 'emerging'
  }
  if (Array.isArray(d.patterns) && d.patterns.length > 0) {
    const first = d.patterns[0] as Record<string, unknown>
    return String(first.confidence ?? 'emerging')
  }
  return ''
}

type PreferenceToast = { id: string; title: string; confidenceLabel: string; action: 'created' | 'updated' }

export function parsePreferenceToasts(
  changes: AppliedChanges | null | undefined
): PreferenceToast[] {
  if (!changes) return []
  const toasts: PreferenceToast[] = []
  const ts = Date.now()
  const checkItem = (item: Record<string, unknown>, action: 'created' | 'updated') => {
    if ((item.type_hint as string | undefined) !== 'preference') return
    let data = item.data
    if (typeof data === 'string') {
      try { data = JSON.parse(data) } catch { data = null }
    }
    toasts.push({
      id: `pref-toast-${ts}-${item.id}`,
      title: String(item.title ?? ''),
      confidenceLabel: preferenceConfidenceLabel(data),
      action,
    })
  }
  for (const c of changes.created ?? []) checkItem(c as Record<string, unknown>, 'created')
  for (const u of changes.updated ?? []) checkItem(u as Record<string, unknown>, 'updated')
  return toasts
}
