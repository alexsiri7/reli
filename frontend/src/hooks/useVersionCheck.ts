import { useEffect, useRef, useState } from 'react'

declare const __APP_BUILD_VERSION__: string

const CHECK_INTERVAL_MS = 60_000

/**
 * Polls /version.json to detect when a new frontend build has been deployed.
 * Returns whether a new version is available and a dismiss handler.
 * The banner reappears on the next successful check after dismissal.
 */
export function useVersionCheck() {
  const [newVersionAvailable, setNewVersionAvailable] = useState(false)
  const dismissedRef = useRef(false)

  useEffect(() => {
    // __APP_BUILD_VERSION__ is injected at build time by the versionJsonPlugin.
    // In dev mode it won't exist, so skip polling entirely.
    if (typeof __APP_BUILD_VERSION__ === 'undefined') return

    const currentVersion = __APP_BUILD_VERSION__

    async function check() {
      try {
        const res = await fetch(`/version.json?_=${Date.now()}`)
        if (!res.ok) return
        const data = await res.json()
        if (data.version && data.version !== currentVersion) {
          if (!dismissedRef.current) {
            setNewVersionAvailable(true)
          }
        }
      } catch {
        // Network error — skip silently
      }
    }

    const interval = setInterval(check, CHECK_INTERVAL_MS)

    // Also check on visibility change (user returns to tab)
    function onVisibilityChange() {
      if (document.visibilityState === 'visible') {
        dismissedRef.current = false
        check()
      }
    }
    document.addEventListener('visibilitychange', onVisibilityChange)

    return () => {
      clearInterval(interval)
      document.removeEventListener('visibilitychange', onVisibilityChange)
    }
  }, [])

  function dismiss() {
    setNewVersionAvailable(false)
    dismissedRef.current = true
  }

  function refresh() {
    window.location.reload()
  }

  return { newVersionAvailable, dismiss, refresh }
}
