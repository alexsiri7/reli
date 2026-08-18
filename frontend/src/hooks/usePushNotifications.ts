import { useEffect, useRef, useCallback, useState } from 'react'
import { useStore } from '../store'
import { useShallow } from 'zustand/react/shallow'

// ── Types ─────────────────────────────────────────────────────────────────────

export interface NotificationPrefs {
  enabled: boolean
  calendarEvents: boolean
  urgentTasks: boolean
  insights: boolean
}

const DEFAULT_PREFS: NotificationPrefs = {
  enabled: false,
  calendarEvents: true,
  urgentTasks: true,
  insights: true,
}

const PREFS_KEY = 'reli-notification-prefs'
// Set of "<type>:<id>" keys already notified this browser session
const firedThisSession = new Set<string>()

// ── Helpers ───────────────────────────────────────────────────────────────────

function loadPrefs(): NotificationPrefs {
  try {
    return { ...DEFAULT_PREFS, ...JSON.parse(localStorage.getItem(PREFS_KEY) ?? '{}') }
  } catch {
    return DEFAULT_PREFS
  }
}

function savePrefsToStorage(prefs: NotificationPrefs) {
  localStorage.setItem(PREFS_KEY, JSON.stringify(prefs))
}

async function showNotification(
  title: string,
  options: NotificationOptions & { data?: { thingId?: string; view?: 'chat'; url?: string } },
) {
  if (!('Notification' in window) || Notification.permission !== 'granted') return

  // Prefer SW-based notification so notificationclick fires even if page is backgrounded
  if ('serviceWorker' in navigator) {
    const reg = await navigator.serviceWorker.ready.catch(() => null)
    if (reg?.showNotification) {
      reg.showNotification(title, options)
      return
    }
  }
  new Notification(title, options)
}

// ── Hook ──────────────────────────────────────────────────────────────────────

export function usePushNotifications() {
  const [permission, setPermission] = useState<NotificationPermission>(
    typeof Notification !== 'undefined' ? Notification.permission : 'default',
  )
  const [prefs, setPrefsState] = useState<NotificationPrefs>(loadPrefs)

  const { calendarEvents, findings, proactiveSurfaces, openThingDetail } = useStore(
    useShallow(s => ({
      calendarEvents: s.calendarEvents,
      findings: s.findings,
      proactiveSurfaces: s.proactiveSurfaces,
      openThingDetail: s.openThingDetail,
    })),
  )

  // Keep a ref so interval callbacks always see latest prefs/permission
  const prefsRef = useRef(prefs)
  prefsRef.current = prefs
  const permissionRef = useRef(permission)
  permissionRef.current = permission

  // ── Permission request ─────────────────────────────────────────────────────
  const requestPermission = useCallback(async (): Promise<NotificationPermission> => {
    if (!('Notification' in window)) return 'denied'
    const result = await Notification.requestPermission()
    setPermission(result)
    if (result === 'granted') {
      const updated = { ...prefsRef.current, enabled: true }
      setPrefsState(updated)
      savePrefsToStorage(updated)
    }
    return result
  }, [])

  // ── Preferences update ─────────────────────────────────────────────────────
  const updatePrefs = useCallback((patch: Partial<NotificationPrefs>) => {
    setPrefsState(prev => {
      const next = { ...prev, ...patch }
      savePrefsToStorage(next)
      return next
    })
  }, [])

  // ── SW message handler (notification click → navigate) ─────────────────────
  useEffect(() => {
    if (!('serviceWorker' in navigator)) return
    const handler = (event: MessageEvent) => {
      if (event.data?.type !== 'NOTIFICATION_CLICK') return
      const { thingId } = event.data as { thingId?: string; view?: string }
      if (thingId) openThingDetail(thingId)
    }
    navigator.serviceWorker.addEventListener('message', handler)
    return () => navigator.serviceWorker.removeEventListener('message', handler)
  }, [openThingDetail])

  // ── Calendar event notifications (check every minute) ─────────────────────
  useEffect(() => {
    const check = () => {
      if (
        !prefsRef.current.enabled ||
        !prefsRef.current.calendarEvents ||
        permissionRef.current !== 'granted'
      ) return

      const now = Date.now()

      for (const event of calendarEvents) {
        if (event.all_day) continue
        const startMs = new Date(event.start).getTime()
        const minutesUntil = (startMs - now) / 60_000

        // Notify when 29–31 minutes away (catches the minute the check runs)
        if (minutesUntil < 29 || minutesUntil > 31) continue

        const key = `calendar:${event.id}`
        if (firedThisSession.has(key)) continue
        firedThisSession.add(key)

        const timeStr = new Date(event.start).toLocaleTimeString(undefined, {
          hour: 'numeric',
          minute: '2-digit',
        })
        showNotification(`Upcoming: ${event.summary}`, {
          body: `Starts at ${timeStr}${event.location ? ` · ${event.location}` : ''}`,
          icon: '/favicon-32.png',
          badge: '/favicon-32.png',
          tag: key,
          data: { view: undefined, url: window.location.origin + '/' },
        })
      }
    }

    check() // run immediately on data change
    const id = setInterval(check, 60_000)
    return () => clearInterval(id)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [calendarEvents])

  // ── Urgent task (findings) notifications ──────────────────────────────────
  useEffect(() => {
    if (
      !prefs.enabled ||
      !prefs.urgentTasks ||
      permission !== 'granted'
    ) return

    // Fire for high-priority findings not yet notified this session
    const urgent = findings.filter(
      f => !f.dismissed && f.priority >= 3 && (f.finding_type === 'overdue_checkin' || f.finding_type === 'approaching_date'),
    )

    for (const finding of urgent.slice(0, 3)) {
      const key = `finding:${finding.id}`
      if (firedThisSession.has(key)) continue
      firedThisSession.add(key)

      showNotification('Reli: Action needed', {
        body: finding.message,
        icon: '/favicon-32.png',
        badge: '/favicon-32.png',
        tag: key,
        data: {
          thingId: finding.thing_id ?? undefined,
          url: window.location.origin + '/',
        },
      })
    }
  }, [findings, prefs.enabled, prefs.urgentTasks, permission])

  // ── High-priority proactive insight notifications ─────────────────────────
  useEffect(() => {
    if (
      !prefs.enabled ||
      !prefs.insights ||
      permission !== 'granted'
    ) return

    for (const surface of proactiveSurfaces.slice(0, 2)) {
      const key = `insight:${surface.thing.id}:${surface.date_key}`
      if (firedThisSession.has(key)) continue
      firedThisSession.add(key)

      const daysLabel =
        surface.days_away === 0
          ? 'today'
          : surface.days_away === 1
          ? 'tomorrow'
          : `in ${surface.days_away} days`

      showNotification(`Reli: ${surface.thing.title}`, {
        body: `${surface.reason} — ${daysLabel}`,
        icon: '/favicon-32.png',
        badge: '/favicon-32.png',
        tag: key,
        data: {
          thingId: surface.thing.id,
          url: window.location.origin + '/',
        },
      })
    }
  }, [proactiveSurfaces, prefs.enabled, prefs.insights, permission])

  return { permission, prefs, requestPermission, updatePrefs }
}
