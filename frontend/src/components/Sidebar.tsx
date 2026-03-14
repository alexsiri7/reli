import { useState, useEffect } from 'react'
import { useShallow } from 'zustand/react/shallow'
import { useStore } from '../store'
import { ThingCard } from './ThingCard'

export function Sidebar() {
  const { things, briefing, loading } = useStore(useShallow(s => ({ things: s.things, briefing: s.briefing, loading: s.loading })))

  const [isOpen, setIsOpen] = useState(() =>
    typeof window !== 'undefined' ? window.innerWidth >= 768 : true
  )

  useEffect(() => {
    const mql = window.matchMedia('(min-width: 768px)')
    const handler = (e: MediaQueryListEvent) => setIsOpen(e.matches)
    mql.addEventListener('change', handler)
    return () => mql.removeEventListener('change', handler)
  }, [])

  const today = new Date()
  today.setHours(0, 0, 0, 0)

  const upcoming = things
    .filter(t => t.checkin_date != null)
    .sort((a, b) => {
      const da = new Date(a.checkin_date!).getTime()
      const db = new Date(b.checkin_date!).getTime()
      return da - db
    })

  const active = things.filter(t => t.checkin_date == null)

  return (
    <>
      {/* Toggle button — visible when sidebar is closed */}
      {!isOpen && (
        <button
          onClick={() => setIsOpen(true)}
          aria-label="Open sidebar"
          className="fixed top-3 left-3 z-50 p-2 rounded-lg bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 shadow-md text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors md:static md:m-0 md:border-0 md:shadow-none md:rounded-none md:bg-gray-50 md:dark:bg-gray-950 md:border-r md:border-gray-200 md:dark:border-gray-800 md:px-2 md:py-3"
        >
          <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M4 6h16M4 12h16M4 18h16" />
          </svg>
        </button>
      )}

      {/* Backdrop — mobile only, when sidebar is open */}
      {isOpen && (
        <div
          onClick={() => { if (window.innerWidth < 768) setIsOpen(false) }}
          className="fixed inset-0 z-40 bg-black/30 transition-opacity md:hidden"
        />
      )}

      {/* Sidebar panel */}
      <aside
        className={`
          fixed inset-y-0 left-0 z-50 w-72 flex flex-col border-r border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-gray-950 overflow-y-auto
          transform transition-transform duration-200 ease-in-out
          ${isOpen ? 'translate-x-0' : '-translate-x-full'}
          md:static md:z-auto md:shrink-0
          ${isOpen ? '' : 'md:-translate-x-full md:hidden'}
        `}
      >
        {/* Header */}
        <div className="px-4 py-3 border-b border-gray-200 dark:border-gray-800 flex items-center justify-between">
          <div>
            <h1 className="text-lg font-bold text-gray-900 dark:text-white tracking-tight">Reli</h1>
            <p className="text-xs text-gray-400 dark:text-gray-500 mt-0.5">
              {new Date().toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric' })}
            </p>
          </div>
          <button
            onClick={() => setIsOpen(false)}
            aria-label="Close sidebar"
            className="p-1.5 rounded-lg text-gray-400 dark:text-gray-500 hover:bg-gray-200 dark:hover:bg-gray-800 hover:text-gray-600 dark:hover:text-gray-300 transition-colors"
          >
            <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
            </svg>
          </button>
        </div>

        {loading && things.length === 0 && (
          <div className="px-4 py-3 space-y-2 animate-pulse">
            <div className="h-4 bg-gray-200 dark:bg-gray-700 rounded w-3/4"></div>
            <div className="h-4 bg-gray-200 dark:bg-gray-700 rounded w-1/2"></div>
            <div className="h-4 bg-gray-200 dark:bg-gray-700 rounded w-5/6"></div>
          </div>
        )}

        {/* Daily Briefing */}
        {briefing.length > 0 && (
          <section className="py-2 border-b border-gray-100 dark:border-gray-800">
            <h2 className="px-4 pb-1 text-xs font-semibold text-gray-400 dark:text-gray-500 uppercase tracking-widest">
              📅 Daily Briefing
            </h2>
            {briefing.map(t => <ThingCard key={t.id} thing={t} />)}
          </section>
        )}

        {/* Upcoming Check-ins */}
        {upcoming.length > 0 && (
          <section className="py-2">
            <h2 className="px-4 pb-1 text-xs font-semibold text-gray-400 dark:text-gray-500 uppercase tracking-widest">
              Upcoming Check-ins
            </h2>
            {upcoming.map(t => <ThingCard key={t.id} thing={t} />)}
          </section>
        )}

        {/* Active Things (no check-in date) */}
        {active.length > 0 && (
          <section className="py-2 border-t border-gray-100 dark:border-gray-800">
            <h2 className="px-4 pb-1 text-xs font-semibold text-gray-400 dark:text-gray-500 uppercase tracking-widest">
              Active Things
            </h2>
            {active.map(t => <ThingCard key={t.id} thing={t} />)}
          </section>
        )}

        {!loading && things.length === 0 && (
          <div className="px-4 py-6 text-sm text-gray-400 dark:text-gray-500 text-center">
            Start by typing in the chat…
          </div>
        )}
      </aside>
    </>
  )
}
