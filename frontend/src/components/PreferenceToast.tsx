/**
 * PreferenceToast — ephemeral notification shown at bottom of chat
 * when the assistant acts on or learns a preference.
 *
 * Usage: rendered in ChatPanel. Parent uses the usePreferenceToast hook
 * to push toasts and they auto-dismiss after 4s.
 */
import { useEffect, useState } from 'react'

export interface PreferenceToastData {
  id: string
  message: string
  thingId?: string
}

interface Props {
  toast: PreferenceToastData
  onDismiss: (id: string) => void
}

export function PreferenceToast({ toast, onDismiss }: Props) {
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    // Trigger enter animation
    const enterTimer = setTimeout(() => setVisible(true), 10)
    // Auto-dismiss after 4s
    const dismissTimer = setTimeout(() => {
      setVisible(false)
      setTimeout(() => onDismiss(toast.id), 300)
    }, 4000)
    return () => {
      clearTimeout(enterTimer)
      clearTimeout(dismissTimer)
    }
  }, [toast.id, onDismiss])

  return (
    <div
      className={`flex items-center gap-2.5 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl shadow-lg px-3.5 py-2.5 max-w-sm transition-all duration-300 ${
        visible ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-2'
      }`}
    >
      <span className="text-base shrink-0">🧠</span>
      <p className="text-xs text-gray-700 dark:text-gray-300 leading-snug flex-1 min-w-0">
        {toast.message}
      </p>
      <button
        onClick={() => {
          setVisible(false)
          setTimeout(() => onDismiss(toast.id), 300)
        }}
        className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 shrink-0 ml-1"
        aria-label="Dismiss"
      >
        <svg className="w-3.5 h-3.5" viewBox="0 0 20 20" fill="currentColor">
          <path fillRule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clipRule="evenodd" />
        </svg>
      </button>
    </div>
  )
}

export function PreferenceToastContainer({ toasts, onDismiss }: {
  toasts: PreferenceToastData[]
  onDismiss: (id: string) => void
}) {
  if (toasts.length === 0) return null
  return (
    <div className="fixed bottom-20 left-1/2 -translate-x-1/2 z-50 flex flex-col gap-2 items-center pointer-events-none md:bottom-6">
      {toasts.map(t => (
        <div key={t.id} className="pointer-events-auto">
          <PreferenceToast toast={t} onDismiss={onDismiss} />
        </div>
      ))}
    </div>
  )
}
