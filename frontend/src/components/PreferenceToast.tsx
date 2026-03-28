import { useStore } from '../store'

export function PreferenceToastContainer() {
  const toasts = useStore(s => s.preferenceToasts)
  const removePreferenceToast = useStore(s => s.removePreferenceToast)

  if (toasts.length === 0) return null

  return (
    <div className="fixed bottom-20 md:bottom-4 left-1/2 -translate-x-1/2 z-50 flex flex-col gap-2 items-center pointer-events-none">
      {toasts.map(toast => (
        <div
          key={toast.id}
          className="pointer-events-auto flex items-center gap-2 px-4 py-2.5 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-full shadow-lg text-sm text-gray-700 dark:text-gray-200 animate-fade-in-up"
          onClick={() => removePreferenceToast(toast.id)}
          role="status"
        >
          <span>🧠</span>
          <span>{toast.message}</span>
          <span className="text-xs text-gray-400 dark:text-gray-500 capitalize">({toast.confidence})</span>
        </div>
      ))}
    </div>
  )
}
