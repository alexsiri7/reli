/**
 * Authenticated fetch wrapper.
 * Sends credentials (cookies) with all requests for JWT session auth.
 */

export function apiFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  return fetch(input, { ...init, credentials: 'same-origin' })
}
