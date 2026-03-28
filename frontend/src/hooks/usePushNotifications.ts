import { useCallback, useEffect, useState } from 'react'

const BASE = '/api'

interface PushNotificationState {
  supported: boolean
  permission: NotificationPermission
  subscribed: boolean
  loading: boolean
  error: string | null
}

interface NotificationTypeSettings {
  calendar: boolean
  tasks: boolean
  insights: boolean
}

const DEFAULT_TYPES: NotificationTypeSettings = {
  calendar: true,
  tasks: true,
  insights: true,
}

function urlBase64ToUint8Array(base64String: string): ArrayBuffer {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4)
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/')
  const rawData = window.atob(base64)
  const bytes = new Uint8Array(rawData.length)
  for (let i = 0; i < rawData.length; i++) {
    bytes[i] = rawData.charCodeAt(i)
  }
  return bytes.buffer as ArrayBuffer
}

export function usePushNotifications() {
  const [state, setState] = useState<PushNotificationState>({
    supported: 'Notification' in window && 'serviceWorker' in navigator && 'PushManager' in window,
    permission: 'Notification' in window ? Notification.permission : 'denied',
    subscribed: false,
    loading: false,
    error: null,
  })

  const [notifTypes, setNotifTypes] = useState<NotificationTypeSettings>(() => {
    try {
      const stored = localStorage.getItem('reli_notif_types')
      return stored ? { ...DEFAULT_TYPES, ...JSON.parse(stored) } : DEFAULT_TYPES
    } catch {
      return DEFAULT_TYPES
    }
  })

  const saveNotifTypes = useCallback((types: NotificationTypeSettings) => {
    setNotifTypes(types)
    localStorage.setItem('reli_notif_types', JSON.stringify(types))
  }, [])

  // Check existing subscription on mount
  useEffect(() => {
    if (!state.supported) return

    navigator.serviceWorker.ready.then(reg => {
      reg.pushManager.getSubscription().then(sub => {
        setState(s => ({ ...s, subscribed: !!sub }))
      })
    }).catch(() => {
      // SW not yet ready
    })
  }, [state.supported])

  const requestPermissionAndSubscribe = useCallback(async () => {
    if (!state.supported) return

    setState(s => ({ ...s, loading: true, error: null }))

    try {
      const permission = await Notification.requestPermission()
      setState(s => ({ ...s, permission }))

      if (permission !== 'granted') {
        setState(s => ({ ...s, loading: false, error: 'Notification permission denied.' }))
        return
      }

      // Fetch VAPID public key
      const keyRes = await fetch(`${BASE}/push/vapid-key`)
      if (!keyRes.ok) throw new Error('Push not available on this server')
      const { public_key: vapidPublicKey } = await keyRes.json()

      const reg = await navigator.serviceWorker.ready
      const subscription = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(vapidPublicKey),
      })

      const subJson = subscription.toJSON()
      const keys = subJson.keys as { p256dh: string; auth: string }

      const enabledTypes = Object.entries(notifTypes)
        .filter(([, v]) => v)
        .map(([k]) => k)

      await fetch(`${BASE}/push/subscribe`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          endpoint: subJson.endpoint,
          p256dh: keys.p256dh,
          auth: keys.auth,
          notification_types: enabledTypes,
        }),
      })

      setState(s => ({ ...s, subscribed: true, loading: false }))
    } catch (err) {
      setState(s => ({ ...s, loading: false, error: err instanceof Error ? err.message : 'Failed to enable notifications' }))
    }
  }, [state.supported, notifTypes])

  const unsubscribe = useCallback(async () => {
    setState(s => ({ ...s, loading: true }))
    try {
      const reg = await navigator.serviceWorker.ready
      const sub = await reg.pushManager.getSubscription()
      if (sub) {
        const endpoint = sub.endpoint
        await sub.unsubscribe()
        await fetch(`${BASE}/push/subscribe?endpoint=${encodeURIComponent(endpoint)}`, {
          method: 'DELETE',
        })
      }
      setState(s => ({ ...s, subscribed: false, loading: false }))
    } catch {
      setState(s => ({ ...s, loading: false }))
    }
  }, [])

  const toggleType = useCallback((type: keyof NotificationTypeSettings) => {
    saveNotifTypes({ ...notifTypes, [type]: !notifTypes[type] })
  }, [notifTypes, saveNotifTypes])

  return {
    ...state,
    notifTypes,
    toggleType,
    requestPermissionAndSubscribe,
    unsubscribe,
  }
}
