import { useStore } from '../store'
import { ThingCard } from './ThingCard'

export function Sidebar() {
  const { things, loading } = useStore(s => ({ things: s.things, loading: s.loading }))

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
    <aside className="w-72 shrink-0 flex flex-col border-r border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-gray-950 overflow-y-auto">
      {/* Header */}
      <div className="px-4 py-3 border-b border-gray-200 dark:border-gray-800">
        <h1 className="text-lg font-bold text-gray-900 dark:text-white tracking-tight">Reli</h1>
        <p className="text-xs text-gray-400 dark:text-gray-500 mt-0.5">
          {new Date().toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric' })}
        </p>
      </div>

      {loading && (
        <div className="px-4 py-3 text-xs text-gray-400 dark:text-gray-500">Loading…</div>
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
          No things yet.<br />
          <span className="text-xs">Start a conversation to create some!</span>
        </div>
      )}
    </aside>
  )
}
