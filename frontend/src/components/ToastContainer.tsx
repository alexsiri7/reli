import { useEffect } from 'react'
import { useStore, type Toast } from '../store'
import { useShallow } from 'zustand/react/shallow'

function ToastItem({ toast }: { toast: Toast }) {
  const dismissToast = useStore(s => s.dismissToast)

  useEffect(() => {
    const timer = setTimeout(() => dismissToast(toast.id), toast.duration ?? 4000)
    return () => clearTimeout(timer)
  }, [toast.id, toast.duration, dismissToast])

  const colorMap = {
    info: 'bg-indigo-600 text-white',
    success: 'bg-emerald-600 text-white',
    warning: 'bg-amber-500 text-white',
    error: 'bg-red-600 text-white',
  }

  const color = colorMap[toast.type ?? 'info']

  return (
    <div
      className={`flex items-center gap-2 px-4 py-2.5 rounded-lg shadow-lg text-sm font-medium max-w-xs ${color} animate-slide-up`}
      role="status"
      aria-live="polite"
    >
      <span className="flex-1">{toast.message}</span>
      <button
        onClick={() => dismissToast(toast.id)}
        className="shrink-0 opacity-75 hover:opacity-100 transition-opacity text-lg leading-none"
        aria-label="Dismiss"
      >
        &times;
      </button>
    </div>
  )
}

export function ToastContainer() {
  const toasts = useStore(useShallow(s => s.toasts))
  if (toasts.length === 0) return null
  return (
    <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-[60] flex flex-col gap-2 items-center pointer-events-none">
      {toasts.map(t => (
        <div key={t.id} className="pointer-events-auto">
          <ToastItem toast={t} />
        </div>
      ))}
    </div>
  )
}
