/// <reference lib="webworker" />
import { cleanupOutdatedCaches, precacheAndRoute } from 'workbox-precaching'

declare let self: ServiceWorkerGlobalScope

// Standard Workbox precaching (injected by VitePWA)
cleanupOutdatedCaches()
precacheAndRoute(self.__WB_MANIFEST)

// Push notification handler
self.addEventListener('push', (event: PushEvent) => {
  let data: { title?: string; body?: string; tag?: string; thing_id?: string; url?: string } = {}
  try {
    data = event.data?.json() ?? {}
  } catch {
    data = { title: 'Reli', body: event.data?.text() ?? '' }
  }

  const title = data.title ?? 'Reli'
  const options: NotificationOptions = {
    body: data.body ?? '',
    icon: '/android-chrome-192.png',
    badge: '/favicon-32.png',
    tag: data.tag ?? 'reli-nudge',
    data: { url: data.url ?? '/', thing_id: data.thing_id },
    requireInteraction: false,
  }

  event.waitUntil(self.registration.showNotification(title, options))
})

// Notification click — navigate to relevant Thing or root
self.addEventListener('notificationclick', (event: NotificationEvent) => {
  event.notification.close()
  const url = (event.notification.data?.url as string) ?? '/'

  event.waitUntil(
    self.clients
      .matchAll({ type: 'window', includeUncontrolled: true })
      .then(clients => {
        const existing = clients.find(c => c.url.includes(self.location.origin))
        if (existing) {
          existing.focus()
          existing.postMessage({ type: 'NAVIGATE', url })
        } else {
          self.clients.openWindow(url)
        }
      })
  )
})
