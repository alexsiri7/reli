/**
 * Authenticated fetch wrapper.
 * Sends credentials (cookies) with all requests for JWT session auth.
 * Redirects to login on 401 responses.
 */

export async function apiFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const res = await fetch(input, { ...init, credentials: 'same-origin' })
  if (res.status === 401 && !String(input).includes('/api/auth/')) {
    // Session expired or not authenticated — trigger re-check
    const { useStore } = await import('./store')
    useStore.getState().fetchCurrentUser()
  }
  return res
}
