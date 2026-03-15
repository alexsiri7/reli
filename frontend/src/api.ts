/**
 * Authenticated fetch wrapper.
 * Reads the API key injected by the backend into window.__RELI_API_KEY__
 * and includes it as X-API-Key header on all requests.
 */

declare global {
  interface Window {
    __RELI_API_KEY__?: string
  }
}

export function apiFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const apiKey = window.__RELI_API_KEY__
  if (!apiKey) {
    return fetch(input, init)
  }
  const headers = new Headers(init?.headers)
  headers.set('X-API-Key', apiKey)
  return fetch(input, { ...init, headers })
}
