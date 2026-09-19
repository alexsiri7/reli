// Kill switch for the pre-v4 PWA's service worker (#1513). That worker precached the old
// index.html and answered every navigation from cache, and a registration can only be evicted by a
// byte-different script at the same URL or a 404 there. This is that script: it installs, unregisters
// itself, drops every cache and reloads the open tabs onto the live bundle. It claims the tabs first:
// matchAll only lists the clients this worker controls, and a stuck tab is still the old worker's
// until claimed. Keep it forever — a browser that has not visited since 2026-09-10 still needs it.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      await self.clients.claim();
      await self.registration.unregister();
      for (const key of await caches.keys()) await caches.delete(key);
      for (const client of await self.clients.matchAll({ type: "window" })) client.navigate(client.url);
    })(),
  );
});
