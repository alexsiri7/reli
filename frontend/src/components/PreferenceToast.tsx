import { useEffect } from 'react'
import { useShallow } from 'zustand/react/shallow'
import { useStore } from '../store'

const TOAST_DURATION_MS = 4000

export function PreferenceToast() {
  const { preferenceToasts, dismissPreferenceToast } = useStore(
    useShallow(s => ({
      preferenceToasts: s.preferenceToasts,
      dismissPreferenceToast: s.dismissPreferenceToast,
    }))
  )

  const toast = preferenceToasts[0] ?? null

  useEffect(() => {
    if (!toast) return
    const timer = setTimeout(() => dismissPreferenceToast(toast.id), TOAST_DURATION_MS)
    return () => clearTimeout(timer)
  }, [toast, dismissPreferenceToast])

  if (!toast) return null

  const verb = toast.action === 'created' ? 'Learned' : 'Updated'

  return (
    <div
      role="status"
      aria-live="polite"
      className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 flex items-center gap-2 bg-purple-600 text-white px-4 py-2 rounded-full shadow-lg text-sm"
      onClick={() => dismissPreferenceToast(toast.id)}
    >
      <span>🧠</span>
      <span>
        {verb}: {toast.title}
        {toast.confidenceLabel && <span className="opacity-80"> (now {toast.confidenceLabel})</span>}
      </span>
    </div>
  )
}
