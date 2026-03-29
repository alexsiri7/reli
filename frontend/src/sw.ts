/// <reference lib="webworker" />
import { clientsClaim } from 'workbox-core'
import {
  precacheAndRoute,
  cleanupOutdatedCaches,
  createHandlerBoundToURL,
} from 'workbox-precaching'
import {
  NavigationRoute,
  registerRoute,
} from 'workbox-routing'
import {
  StaleWhileRevalidate,
  NetworkOnly,
  CacheFirst,
} from 'workbox-strategies'
import { ExpirationPlugin } from 'workbox-expiration'

declare const self: ServiceWorkerGlobalScope

self.skipWaiting()
clientsClaim()

// Precache and route
precacheAndRoute(self.__WB_MANIFEST)
cleanupOutdatedCaches()

// Navigation fallback (deny API/oauth/mcp paths)
registerRoute(
  new NavigationRoute(createHandlerBoundToURL('index.html'), {
    denylist: [/^\/api\//, /^\/oauth\//, /^\/.well-known\//, /^\/mcp/],
  }),
)

// API read caching
registerRoute(
  /^https?:\/\/[^/]+\/api\/(things|thing-types|briefing)(\?.*)?$/,
  new StaleWhileRevalidate({
    cacheName: 'api-read-cache',
    plugins: [new ExpirationPlugin({ maxEntries: 100, maxAgeSeconds: 60 * 60 * 24 })],
  }),
  'GET',
)

// Relationship caching
registerRoute(
  /^https?:\/\/[^/]+\/api\/things\/[^/]+\/relationships(\?.*)?$/,
  new StaleWhileRevalidate({
    cacheName: 'api-relationships-cache',
    plugins: [new ExpirationPlugin({ maxEntries: 100, maxAgeSeconds: 60 * 60 * 24 })],
  }),
  'GET',
)

// Chat — network only
registerRoute(/^https?:\/\/[^/]+\/api\/chat/, new NetworkOnly(), 'GET')

// Fonts
registerRoute(
  /\.(?:woff2?|ttf|otf|eot)$/,
  new CacheFirst({
    cacheName: 'static-fonts',
    plugins: [new ExpirationPlugin({ maxEntries: 50, maxAgeSeconds: 60 * 60 * 24 * 30 })],
  }),
  'GET',
)

// Images
registerRoute(
  /\.(?:png|jpg|jpeg|gif|webp|svg|ico)$/,
  new CacheFirst({
    cacheName: 'static-images',
    plugins: [new ExpirationPlugin({ maxEntries: 50, maxAgeSeconds: 60 * 60 * 24 * 30 })],
  }),
  'GET',
)

// ── Notification click handler ────────────────────────────────────────────────
// When a browser push notification is clicked, open or focus the Reli app
// and post a message so the React app can navigate to the relevant item.
self.addEventListener('notificationclick', (event: NotificationEvent) => {
  event.notification.close()

  const data = event.notification.data as {
    url?: string
    thingId?: string
    view?: 'chat'
  } | undefined

  const targetUrl = data?.url || self.location.origin + '/'

  event.waitUntil(
    self.clients
      .matchAll({ type: 'window', includeUncontrolled: true })
      .then(clientList => {
        // Try to focus an existing Reli window
        for (const client of clientList) {
          if (
            'focus' in client &&
            new URL(client.url).origin === new URL(self.location.href).origin
          ) {
            client.focus()
            client.postMessage({
              type: 'NOTIFICATION_CLICK',
              thingId: data?.thingId,
              view: data?.view,
            })
            return
          }
        }
        // No existing window — open a new one
        return self.clients.openWindow(targetUrl)
      }),
  )
})
