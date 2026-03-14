import { useCallback, useEffect, useState } from 'react'

const BASE = '/api'

interface GmailMessage {
  id: string
  thread_id: string
  subject: string
  sender: string
  to: string
  date: string
  snippet: string
  body: string | null
  labels: string[]
}

interface GmailStatus {
  connected: boolean
  email: string | null
}

function formatSender(from: string): string {
  // "John Doe <john@example.com>" → "John Doe"
  const match = from.match(/^"?([^"<]+)"?\s*</)
  return match ? match[1].trim() : from
}

function formatDate(iso: string): string {
  const date = new Date(iso)
  if (isNaN(date.getTime())) return ''
  const now = new Date()
  const isToday =
    date.getFullYear() === now.getFullYear() &&
    date.getMonth() === now.getMonth() &&
    date.getDate() === now.getDate()
  if (isToday) return date.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
  const diff = now.getTime() - date.getTime()
  if (diff < 7 * 86400000) return date.toLocaleDateString(undefined, { weekday: 'short' })
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

function MessageDetail({ message, onBack }: { message: GmailMessage; onBack: () => void }) {
  return (
    <div className="flex flex-col h-full">
      <button
        onClick={onBack}
        className="flex items-center gap-1 text-xs text-indigo-600 dark:text-indigo-400 hover:underline px-4 pt-3 pb-1"
      >
        <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
        </svg>
        Back
      </button>
      <div className="px-4 py-2 border-b border-gray-200 dark:border-gray-700">
        <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">{message.subject}</h3>
        <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
          From: {message.sender}
        </p>
        <p className="text-xs text-gray-400 dark:text-gray-500">
          {new Date(message.date).toLocaleString()}
        </p>
      </div>
      <div className="flex-1 overflow-y-auto px-4 py-3">
        <pre className="text-xs text-gray-700 dark:text-gray-300 whitespace-pre-wrap font-sans leading-relaxed">
          {message.body || message.snippet}
        </pre>
      </div>
    </div>
  )
}

export function GmailPanel() {
  const [status, setStatus] = useState<GmailStatus | null>(null)
  const [messages, setMessages] = useState<GmailMessage[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [selectedMsg, setSelectedMsg] = useState<GmailMessage | null>(null)
  const [notConfigured, setNotConfigured] = useState(false)

  const checkStatus = useCallback(async () => {
    try {
      const res = await fetch(`${BASE}/gmail/status`)
      if (res.status === 501) {
        setNotConfigured(true)
        return
      }
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data: GmailStatus = await res.json()
      setStatus(data)
    } catch {
      // ignore - status check is best-effort
    }
  }, [])

  const fetchMessages = useCallback(async (query?: string) => {
    setLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams()
      if (query) params.set('q', query)
      params.set('max_results', '20')
      const res = await fetch(`${BASE}/gmail/messages?${params}`)
      if (res.status === 401) {
        setStatus({ connected: false, email: null })
        return
      }
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data: GmailMessage[] = await res.json()
      setMessages(data)
    } catch (e) {
      setError(String(e))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    checkStatus()
  }, [checkStatus])

  useEffect(() => {
    if (status?.connected) fetchMessages()
  }, [status?.connected, fetchMessages])

  const handleConnect = async () => {
    try {
      const res = await fetch(`${BASE}/gmail/auth-url`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      window.location.href = data.auth_url
    } catch (e) {
      setError(String(e))
    }
  }

  const handleDisconnect = async () => {
    try {
      await fetch(`${BASE}/gmail/disconnect`, { method: 'DELETE' })
      setStatus({ connected: false, email: null })
      setMessages([])
    } catch (e) {
      setError(String(e))
    }
  }

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault()
    fetchMessages(search || undefined)
  }

  const handleMessageClick = async (msg: GmailMessage) => {
    // Fetch full message with body
    try {
      const res = await fetch(`${BASE}/gmail/messages/${msg.id}`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const full: GmailMessage = await res.json()
      setSelectedMsg(full)
    } catch {
      setSelectedMsg(msg)
    }
  }

  if (notConfigured) return null

  if (!status) {
    return (
      <div className="px-4 py-3 text-xs text-gray-400 dark:text-gray-500">
        Checking Gmail...
      </div>
    )
  }

  if (!status.connected) {
    return (
      <section className="py-3 border-t border-gray-100 dark:border-gray-800">
        <h2 className="px-4 pb-2 text-xs font-semibold text-gray-400 dark:text-gray-500 uppercase tracking-widest">
          Gmail
        </h2>
        <div className="px-4">
          <button
            onClick={handleConnect}
            className="w-full flex items-center justify-center gap-2 px-3 py-2 text-xs font-medium rounded-lg border border-gray-200 dark:border-gray-700 text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
          >
            <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none">
              <path d="M20 18h-2V9.25L12 13 6 9.25V18H4V6h1.2l6.8 4.25L18.8 6H20v12z" fill="currentColor"/>
            </svg>
            Connect Gmail
          </button>
        </div>
      </section>
    )
  }

  if (selectedMsg) {
    return (
      <section className="py-2 border-t border-gray-100 dark:border-gray-800 flex flex-col" style={{ maxHeight: '50vh' }}>
        <MessageDetail message={selectedMsg} onBack={() => setSelectedMsg(null)} />
      </section>
    )
  }

  return (
    <section className="py-2 border-t border-gray-100 dark:border-gray-800">
      <div className="px-4 pb-1 flex items-center justify-between">
        <h2 className="text-xs font-semibold text-gray-400 dark:text-gray-500 uppercase tracking-widest">
          Gmail
        </h2>
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-gray-400 dark:text-gray-500 truncate max-w-[120px]">
            {status.email}
          </span>
          <button
            onClick={handleDisconnect}
            className="text-[10px] text-red-400 hover:text-red-500 dark:text-red-500 dark:hover:text-red-400"
            title="Disconnect Gmail"
          >
            Disconnect
          </button>
        </div>
      </div>

      {/* Search */}
      <form onSubmit={handleSearch} className="px-4 pb-2">
        <div className="flex gap-1">
          <input
            type="text"
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Search emails..."
            className="flex-1 text-xs px-2 py-1.5 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-300 placeholder-gray-400 dark:placeholder-gray-500 outline-none focus:ring-1 focus:ring-indigo-500"
          />
          <button
            type="submit"
            className="px-2 py-1.5 text-xs rounded-lg bg-indigo-600 text-white hover:bg-indigo-700 transition-colors"
          >
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
          </button>
        </div>
      </form>

      {error && (
        <div className="px-4 pb-2 text-xs text-red-500">{error}</div>
      )}

      {loading ? (
        <div className="flex justify-center py-4">
          <span className="w-4 h-4 border-2 border-gray-300 border-t-indigo-600 rounded-full animate-spin" />
        </div>
      ) : messages.length === 0 ? (
        <div className="px-4 py-3 text-xs text-gray-400 dark:text-gray-500 text-center">
          No emails found
        </div>
      ) : (
        <div className="max-h-64 overflow-y-auto">
          {messages.map(msg => (
            <button
              key={msg.id}
              onClick={() => handleMessageClick(msg)}
              className="w-full text-left px-4 py-2 hover:bg-gray-100 dark:hover:bg-gray-800/50 transition-colors border-b border-gray-50 dark:border-gray-800/50 last:border-0"
            >
              <div className="flex items-baseline justify-between gap-2">
                <span className="text-xs font-medium text-gray-700 dark:text-gray-300 truncate">
                  {formatSender(msg.sender)}
                </span>
                <span className="text-[10px] text-gray-400 dark:text-gray-500 shrink-0">
                  {formatDate(msg.date)}
                </span>
              </div>
              <div className="text-xs text-gray-600 dark:text-gray-400 truncate mt-0.5">
                {msg.subject}
              </div>
              <div className="text-[11px] text-gray-400 dark:text-gray-500 truncate mt-0.5">
                {msg.snippet}
              </div>
            </button>
          ))}
        </div>
      )}
    </section>
  )
}
