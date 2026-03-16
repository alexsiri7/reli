import { useState } from 'react'

export function LoginPage() {
  const [loading, setLoading] = useState(false)
  const params = new URLSearchParams(window.location.search)
  const [error, setError] = useState<string | null>(
    params.get('error') === 'invite_only'
      ? 'This app is invite-only. Your Google account is not on the access list.'
      : null
  )

  const handleLogin = async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch('/api/auth/google', { credentials: 'same-origin' })
      if (!res.ok) {
        const data = await res.json().catch(() => ({ detail: 'Login unavailable' }))
        setError(data.detail || 'Login failed')
        return
      }
      const data = await res.json()
      if (data.auth_url) {
        window.location.href = data.auth_url
      }
    } catch {
      setError('Could not connect to server')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex items-center justify-center min-h-screen bg-gray-50 dark:bg-gray-900">
      <div className="w-full max-w-sm px-6 py-8 bg-white dark:bg-gray-800 rounded-xl shadow-lg border border-gray-200 dark:border-gray-700">
        <div className="flex flex-col items-center gap-3 mb-8">
          <img src="/logo.svg" alt="Reli" className="h-12 w-12 rounded-lg" />
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Reli</h1>
          <p className="text-sm text-gray-500 dark:text-gray-400 text-center">
            Your personal relationship manager
          </p>
        </div>

        {error && (
          <div className="mb-4 px-3 py-2 text-sm text-red-700 dark:text-red-300 bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-700 rounded-lg">
            {error}
          </div>
        )}

        <button
          onClick={handleLogin}
          disabled={loading}
          className="w-full flex items-center justify-center gap-3 px-4 py-2.5 bg-white dark:bg-gray-700 border border-gray-300 dark:border-gray-600 rounded-lg shadow-sm hover:bg-gray-50 dark:hover:bg-gray-600 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <svg className="h-5 w-5" viewBox="0 0 24 24">
            <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z" fill="#4285F4" />
            <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853" />
            <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" fill="#FBBC05" />
            <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335" />
          </svg>
          <span className="text-sm font-medium text-gray-700 dark:text-gray-200">
            {loading ? 'Redirecting...' : 'Sign in with Google'}
          </span>
        </button>
      </div>
    </div>
  )
}
