import { useState } from 'react'
import { useStore } from '../store'

const FAB_TYPES = [
  { type: 'task', label: 'Add task', icon: '✅' },
  { type: 'note', label: 'Quick note', icon: '📝' },
  { type: 'idea', label: 'Capture idea', icon: '💡' },
  { type: 'person', label: 'Remember person', icon: '👤' },
] as const

export function MobileFAB() {
  const createThing = useStore(s => s.createThing)
  const [open, setOpen] = useState(false)
  const [activeType, setActiveType] = useState<string | null>(null)
  const [title, setTitle] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleTypeSelect = (type: string) => {
    setActiveType(type)
    setOpen(false)
    setTitle('')
    setError(null)
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    const trimmed = title.trim()
    if (!trimmed) return
    setSaving(true)
    setError(null)
    try {
      await createThing(trimmed, activeType ?? undefined)
      setActiveType(null)
      setTitle('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create')
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      {/* Inline creation form — slides up from bottom when type selected */}
      {activeType !== null && (
        <div className="fixed inset-x-0 bottom-16 z-40 px-4 pb-2">
          <form
            onSubmit={handleSubmit}
            className="bg-surface-container-high rounded-xl shadow-lg border border-on-surface-variant/10 p-3"
          >
            <p className="text-xs font-medium text-on-surface-variant mb-2">
              {FAB_TYPES.find(t => t.type === activeType)?.label}
            </p>
            <input
              autoFocus
              type="text"
              placeholder="Title…"
              value={title}
              onChange={e => setTitle(e.target.value)}
              onKeyDown={e => { if (e.key === 'Escape') setActiveType(null) }}
              disabled={saving}
              className="w-full text-sm bg-transparent text-on-surface placeholder-on-surface-variant/50 outline-none"
            />
            {error && <p className="text-xs text-ideas mt-1">{error}</p>}
            <div className="flex justify-end gap-2 mt-2">
              <button
                type="button"
                onClick={() => setActiveType(null)}
                className="text-xs text-on-surface-variant px-2 py-1"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={!title.trim() || saving}
                className="text-xs font-medium px-3 py-1 rounded-lg bg-primary text-on-primary disabled:opacity-50"
              >
                {saving ? 'Saving…' : 'Add'}
              </button>
            </div>
          </form>
        </div>
      )}

      {/* Type menu — shown when FAB is open */}
      {open && (
        <>
          <div
            className="fixed inset-0 z-30"
            onClick={() => setOpen(false)}
          />
          <div className="fixed bottom-20 right-4 z-40 flex flex-col gap-2 items-end">
            {FAB_TYPES.map(({ type, label, icon }) => (
              <button
                key={type}
                onClick={() => handleTypeSelect(type)}
                className="flex items-center gap-2 px-3 py-2 bg-surface-container-high rounded-full shadow-md text-sm font-medium text-on-surface border border-on-surface-variant/10"
              >
                <span>{icon}</span>
                <span>{label}</span>
              </button>
            ))}
          </div>
        </>
      )}

      {/* FAB button — positioned above tab bar (bottom-20 = 80px = safe clearance above ~56px tab bar) */}
      <button
        onClick={() => { setOpen(v => !v); setActiveType(null) }}
        aria-label="Quick add"
        className="fixed bottom-20 right-4 z-40 w-12 h-12 rounded-full bg-primary text-on-primary shadow-lg flex items-center justify-center text-2xl hover:bg-primary/90 transition-colors"
      >
        <span className={`transition-transform duration-200 ${open ? 'rotate-45' : ''}`}>+</span>
      </button>
    </>
  )
}
