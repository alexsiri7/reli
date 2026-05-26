import { useState } from 'react'

const HOW_IT_WORKS = [
  { emoji: '🧠', titleColor: 'text-projects', title: 'Knowledge Graph', description: "Everything Reli knows is stored as typed Things with relationships. People, events, tasks, preferences — all linked so Reli can reason across your whole life." },
  { emoji: '🔗', titleColor: 'text-primary',  title: 'Claude via MCP',  description: "Through MCP, any agent can tap into Reli's intelligence — your preferences, patterns, and relationships that make every AI interaction smarter about you." },
  { emoji: '📋', titleColor: 'text-events',   title: 'Daily Briefing',  description: "Reli's nightly sweep thinks about your life — detecting gaps, aggregating patterns, and assembling briefings prioritized by urgency and your habits." },
]

const KEY_CONCEPTS = [
  { color: 'projects', letter: 'T', title: 'Things',         description: 'People, events, tasks, preferences — everything is a typed Thing in your knowledge graph.' },
  { color: 'people',   letter: 'R', title: 'Relationships',  description: 'Things are connected by relationships, letting Reli reason across domains and contexts.' },
  { color: 'events',   letter: 'B', title: 'Briefings',      description: "Prioritized by urgency and your patterns, not just chronological. What actually needs your attention." },
  { color: 'ideas',    letter: '?', title: 'Open Questions', description: "Gaps Reli detects in its understanding — things it needs to ask you to build a complete picture." },
]

const STEPS = [
  { title: 'Sign in',        description: 'Sign in with your Google account' },
  { title: 'Open Claude',    description: 'Open Claude Desktop on your computer' },
  { title: 'Add MCP server', description: 'Connect Reli as an MCP server in Claude' },
  { title: 'Start talking',  description: 'Have a conversation and let Reli learn' },
]

interface SignInButtonProps {
  loading: boolean
  onLogin: () => void
  className?: string
}

function SignInButton({ loading, onLogin, className = '' }: SignInButtonProps) {
  return (
    <button
      onClick={onLogin}
      disabled={loading}
      className={`flex items-center justify-center gap-3 px-6 py-3 bg-white dark:bg-gray-700 border border-gray-300 dark:border-gray-600 rounded-lg shadow-sm hover:bg-gray-50 dark:hover:bg-gray-600 transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${className}`}
    >
      <svg className="h-5 w-5" viewBox="0 0 24 24" aria-hidden="true">
        <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z" fill="#4285F4" />
        <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853" />
        <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" fill="#FBBC05" />
        <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335" />
      </svg>
      <span className="text-sm font-medium text-gray-700 dark:text-gray-200">
        {loading ? 'Redirecting...' : 'Sign in with Google'}
      </span>
    </button>
  )
}

export function LandingPage() {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(() => {
    const params = new URLSearchParams(window.location.search)
    return params.get('error') === 'invite_only'
      ? 'This app is invite-only. Your Google account is not on the access list.'
      : null
  })

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
    <div className="min-h-screen bg-canvas">
      {/* Nav */}
      <nav className="flex items-center justify-between px-6 py-4 max-w-6xl mx-auto">
        <div className="flex items-center gap-3">
          <img src="/logo.svg" alt="Reli" className="h-8 w-8 rounded-lg" />
          <span className="text-lg font-semibold text-on-surface">Reli</span>
        </div>
        <SignInButton loading={loading} onLogin={handleLogin} />
      </nav>

      {/* Hero */}
      <section className="px-6 py-20 max-w-4xl mx-auto text-center">
        <h1 className="text-display font-bold text-on-surface mb-6">
          Your second brain for Claude
        </h1>
        <p className="text-xl text-on-surface-variant max-w-2xl mx-auto mb-10 leading-relaxed">
          Not a chatbot with memory bolted on, but a system that genuinely models you and gets better over time.
        </p>
        <SignInButton loading={loading} onLogin={handleLogin} className="mx-auto" />
      </section>

      {/* How it works */}
      <section className="px-6 py-16 max-w-6xl mx-auto">
        <h2 className="text-headline font-semibold text-on-surface text-center mb-12">
          How it works
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
          {HOW_IT_WORKS.map(({ emoji, titleColor, title, description }) => (
            <div key={title} className="bg-surface-container-low rounded-xl p-6 border border-white/5">
              <div className="text-3xl mb-4">{emoji}</div>
              <h3 className={`text-title font-semibold ${titleColor} mb-2`}>{title}</h3>
              <p className="text-body text-on-surface-variant">{description}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Key concepts */}
      <section className="px-6 py-16 max-w-6xl mx-auto">
        <h2 className="text-headline font-semibold text-on-surface text-center mb-12">
          Key concepts
        </h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
          {KEY_CONCEPTS.map(({ color, letter, title, description }) => (
            <div key={title} className="bg-surface-container-low rounded-xl p-6 border border-white/5">
              <div className={`w-10 h-10 rounded-lg bg-${color}/20 flex items-center justify-center mb-4`}>
                <span className={`text-${color} text-lg font-bold`}>{letter}</span>
              </div>
              <h3 className="text-title font-semibold text-on-surface mb-2">{title}</h3>
              <p className="text-body text-on-surface-variant">{description}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Getting started */}
      <section className="px-6 py-16 max-w-4xl mx-auto">
        <h2 className="text-headline font-semibold text-on-surface text-center mb-12">
          Get started
        </h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
          {STEPS.map(({ title, description }, i) => (
            <div key={title} className="text-center">
              <div className="w-12 h-12 rounded-full bg-primary-container flex items-center justify-center mx-auto mb-4">
                <span className="text-on-primary-container font-bold">{i + 1}</span>
              </div>
              <h3 className="text-title font-semibold text-on-surface mb-1">{title}</h3>
              <p className="text-body text-on-surface-variant">{description}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Footer CTA */}
      <section className="px-6 py-20 max-w-4xl mx-auto text-center">
        <h2 className="text-headline font-semibold text-on-surface mb-4">
          Ready to get started?
        </h2>
        <p className="text-on-surface-variant mb-8">
          Your personal AI that actually knows you.
        </p>
        {error && (
          <div className="mb-6 mx-auto max-w-md px-3 py-2 text-sm text-red-700 dark:text-red-300 bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-700 rounded-lg">
            {error}
          </div>
        )}
        <SignInButton loading={loading} onLogin={handleLogin} className="mx-auto" />
      </section>
    </div>
  )
}
