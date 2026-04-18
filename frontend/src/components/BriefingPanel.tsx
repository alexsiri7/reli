import { useState, useCallback } from 'react'
import { useShallow } from 'zustand/react/shallow'
import { useStore } from '../store'
import type { SweepFinding, BriefingItem, LearnedPreference, CalendarEvent } from '../store'
import { NudgeBanner } from './NudgeBanner'

const FINDING_TYPE_CONFIG: Record<string, { icon: string; color: string }> = {
  approaching_date: { icon: '\u23F0', color: 'bg-events' },
  stale: { icon: '\u{1F4A4}', color: 'bg-on-surface-variant' },
  neglected: { icon: '\u{1F6A8}', color: 'bg-ideas' },
  overdue_checkin: { icon: '\u{1F4C5}', color: 'bg-ideas' },
  orphan: { icon: '\u{1F50D}', color: 'bg-primary' },
  inconsistency: { icon: '\u26A0\uFE0F', color: 'bg-events' },
  open_question: { icon: '\u2753', color: 'bg-people' },
  connection: { icon: '\u{1F517}', color: 'bg-projects' },
}

function formatGreetingDate(): string {
  return new Date().toLocaleDateString('en-US', {
    weekday: 'long',
    month: 'long',
    day: 'numeric',
  })
}

function getGreeting(): string {
  const hour = new Date().getHours()
  if (hour < 12) return 'Good Morning'
  if (hour < 17) return 'Good Afternoon'
  return 'Good Evening'
}

function getTomorrowISO(): string {
  const d = new Date()
  d.setDate(d.getDate() + 1)
  return d.toISOString().slice(0, 10)
}

function SectionCard({ title, accent, children }: {
  title: string
  accent: string
  children: React.ReactNode
}) {
  return (
    <section className="px-6 pb-6">
      <p className={`text-label font-semibold mb-2 ${accent}`}>{title}</p>
      <div className="space-y-2">{children}</div>
    </section>
  )
}

export function TodayEventRow({ event }: { event: CalendarEvent }) {
  const parsed = new Date(event.start)
  const startTime = event.all_day
    ? 'All day'
    : isNaN(parsed.getTime())
      ? event.start
      : parsed.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })
  return (
    <div className="flex items-start gap-3 py-2 px-4">
      <span className="text-xs text-on-surface-variant tabular-nums shrink-0 pt-0.5 w-16">{startTime}</span>
      <div className="flex-1 min-w-0">
        <p className="text-sm text-on-surface leading-snug">{event.summary}</p>
        {event.location && (
          <p className="text-xs text-on-surface-variant mt-0.5 truncate">{event.location}</p>
        )}
      </div>
    </div>
  )
}

export function DueTodayRow({ item, onDone, onSnooze, onChat }: {
  item: BriefingItem
  onDone: (id: string) => void
  onSnooze: (id: string) => void
  onChat: (id: string, title: string) => void
}) {
  return (
    <div className="group rounded-xl bg-surface-container-low hover:bg-surface-container-high/60 transition-colors overflow-hidden">
      <div className="flex items-start gap-3 py-3 px-4">
        <div className="flex-1 min-w-0">
          <p className="text-sm text-on-surface font-medium leading-snug">{item.thing.title}</p>
          {item.reasons.length > 0 && (
            <p className="text-xs text-on-surface-variant mt-0.5 truncate">{item.reasons[0]}</p>
          )}
          <div className="flex items-center gap-2 mt-1.5 md:opacity-0 md:group-hover:opacity-100 transition-opacity">
            <button
              onClick={() => onDone(item.thing.id)}
              className="text-xs text-primary hover:text-primary/80 font-medium"
            >
              Done
            </button>
            <button
              onClick={() => onSnooze(item.thing.id)}
              className="text-xs text-on-surface-variant hover:text-on-surface"
            >
              Snooze
            </button>
            <button
              onClick={() => onChat(item.thing.id, item.thing.title)}
              className="text-xs text-on-surface-variant hover:text-on-surface"
            >
              Chat
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

function FindingCard({ finding, onDismiss, onSnooze, onAct }: {
  finding: SweepFinding
  onDismiss: (id: string) => void
  onSnooze: (id: string) => void
  onAct: (finding: SweepFinding) => void
}) {
  const typeConfig = FINDING_TYPE_CONFIG[finding.finding_type]
  const icon = typeConfig?.icon ?? '\u{1F4CB}'
  const dotColor = typeConfig?.color ?? 'bg-primary'
  return (
    <div className="group rounded-xl bg-surface-container-low hover:bg-surface-container-high/60 transition-colors overflow-hidden">
      <div className="flex items-start gap-3 py-3 px-4">
        <div className={`w-1 self-stretch rounded-full shrink-0 ${dotColor}`} />
        <div className="flex items-center gap-2 mt-0.5 shrink-0">
          <span className="text-sm">{icon}</span>
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-sm text-on-surface leading-snug">{finding.message}</p>
          {finding.thing && (
            <p className="text-xs text-on-surface-variant mt-0.5 truncate">
              {finding.thing.title}
            </p>
          )}
          <div className="flex items-center gap-2 mt-1.5 md:opacity-0 md:group-hover:opacity-100 transition-opacity">
            {finding.thing_id && (
              <button
                onClick={() => onAct(finding)}
                className="text-xs text-primary hover:text-primary/80 font-medium"
              >
                Open
              </button>
            )}
            <button
              onClick={() => onSnooze(finding.id)}
              className="text-xs text-on-surface-variant hover:text-on-surface"
            >
              Snooze
            </button>
            <button
              onClick={() => onDismiss(finding.id)}
              className="text-xs text-on-surface-variant hover:text-ideas"
            >
              Dismiss
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

const CONFIDENCE_COLORS: Record<string, string> = {
  strong: 'bg-green-500',
  moderate: 'bg-yellow-500',
  emerging: 'bg-blue-400',
}

export function LearnedPreferenceCard({
  pref,
  onFeedback,
}: {
  pref: LearnedPreference
  onFeedback: (id: string, accurate: boolean) => void
}) {
  const [feedbackSent, setFeedbackSent] = useState<boolean | null>(null)
  const dotColor = CONFIDENCE_COLORS[pref.confidence_label] ?? 'bg-primary'

  const handleFeedback = useCallback((accurate: boolean) => {
    if (feedbackSent !== null) return
    setFeedbackSent(accurate)
    onFeedback(pref.id, accurate)
  }, [feedbackSent, onFeedback, pref.id])

  return (
    <div className="group rounded-xl bg-surface-container-low hover:bg-surface-container-high/60 transition-colors overflow-hidden">
      <div className="flex items-start gap-3 py-3 px-4">
        <div className={`w-1 self-stretch rounded-full shrink-0 ${dotColor}`} />
        <span className="text-sm mt-0.5 shrink-0">{'\u{1F9E0}'}</span>
        <div className="flex-1 min-w-0">
          <p className="text-sm text-on-surface leading-snug">{pref.title}</p>
          <div className="flex items-center gap-2 mt-1.5">
            <span className="text-xs text-on-surface-variant capitalize">{pref.confidence_label}</span>
            {feedbackSent === null ? (
              <>
                <button
                  onClick={() => handleFeedback(true)}
                  className="text-xs text-primary hover:text-primary/80 font-medium"
                >
                  That&apos;s right
                </button>
                <button
                  onClick={() => handleFeedback(false)}
                  className="text-xs text-on-surface-variant hover:text-ideas"
                >
                  Not really
                </button>
              </>
            ) : (
              <span className="text-xs text-on-surface-variant">
                {feedbackSent ? 'Thanks!' : 'Got it'}
              </span>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

function StatCard({ label, value, suffix, accent }: { label: string; value: number | string; suffix?: string; accent?: string }) {
  return (
    <div className="glass rounded-xl p-4 flex-1 min-w-0 text-center">
      <div className="flex items-baseline justify-center gap-0.5">
        <p className={`text-3xl font-bold tabular-nums ${accent ?? 'text-on-surface'}`}>{value}</p>
        {suffix && <span className={`text-sm font-medium ${accent ?? 'text-on-surface-variant'}`}>{suffix}</span>}
      </div>
      <p className="text-label text-on-surface-variant mt-1">{label}</p>
    </div>
  )
}

export function BriefingPanel() {
  const {
    theOneThing, secondaryItems, briefingStats, findings, learnedPreferences, nudges,
    morningBriefing, calendarEvents, error,
    setRightView, dismissFinding, snoozeFinding, actOnFinding,
    submitPreferenceFeedback, updateThing, snoozeThing, openChatWithContext,
  } = useStore(
    useShallow(s => ({
      theOneThing: s.theOneThing,
      secondaryItems: s.secondaryItems,
      briefingStats: s.briefingStats,
      findings: s.findings,
      learnedPreferences: s.learnedPreferences,
      nudges: s.nudges,
      morningBriefing: s.morningBriefing,
      calendarEvents: s.calendarEvents,
      error: s.error,
      setRightView: s.setRightView,
      dismissFinding: s.dismissFinding,
      snoozeFinding: s.snoozeFinding,
      actOnFinding: s.actOnFinding,
      submitPreferenceFeedback: s.submitPreferenceFeedback,
      updateThing: s.updateThing,
      snoozeThing: s.snoozeThing,
      openChatWithContext: s.openChatWithContext,
    }))
  )

  const handleSnooze = (id: string) => snoozeFinding(id, getTomorrowISO())

  const handleDoneThing = (id: string) => {
    updateThing(id, { active: false })
  }

  const handleSnoozeThing = (id: string) => snoozeThing(id, getTomorrowISO())

  const todayISO = new Date().toLocaleDateString('en-CA')  // YYYY-MM-DD in local TZ
  const todayEvents = calendarEvents.filter(e => e.start.slice(0, 10) === todayISO)

  const dueTodayItems = [
    ...(theOneThing ? [theOneThing] : []),
    ...secondaryItems,
  ]

  const hasContent = dueTodayItems.length > 0 || findings.length > 0 || learnedPreferences.length > 0 || todayEvents.length > 0

  return (
    <div className="flex-1 flex flex-col bg-canvas min-w-0 min-h-0">
      {/* Header bar — hidden on mobile (bottom tab bar handles navigation) */}
      <div className="hidden md:flex px-5 py-3 border-b border-surface-container-high bg-surface shrink-0 items-center justify-between">
        <p className="text-label text-on-surface-variant">Daily Briefing</p>
        <button
          onClick={() => setRightView('chat')}
          className="flex items-center gap-1.5 text-xs text-on-surface-variant hover:text-on-surface transition-colors"
          title="Switch to Chat"
        >
          <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M8.625 12a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0H8.25m4.125 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0H12m4.125 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0h-.375M21 12c0 4.556-4.03 8.25-9 8.25a9.764 9.764 0 0 1-2.555-.337A5.972 5.972 0 0 1 5.41 20.97a5.969 5.969 0 0 1-.474-.065 4.48 4.48 0 0 0 .978-2.025c.09-.457-.133-.901-.467-1.226C3.93 16.178 3 14.189 3 12c0-4.556 4.03-8.25 9-8.25s9 3.694 9 8.25Z" />
          </svg>
          Chat
        </button>
      </div>

      {/* Mobile header — logo and Reli branding */}
      <div className="md:hidden px-5 pt-4 pb-2 bg-canvas shrink-0 flex items-center gap-2">
        <div className="w-7 h-7 rounded bg-primary-container flex items-center justify-center">
          <img src="/logo.svg" alt="Reli" className="h-4 w-4" />
        </div>
        <span className="text-lg font-bold text-on-surface tracking-tight">Reli</span>
      </div>

      <div className="flex-1 overflow-y-auto">
        {nudges.length > 0 && (
          <section className="px-6 pt-4">
            {nudges.map(nudge => (
              <NudgeBanner key={nudge.id} nudge={nudge} />
            ))}
          </section>
        )}
        {error && (
          <div className="mx-6 mt-3 px-4 py-2 rounded-xl bg-error/10 text-error text-sm">
            {error}
          </div>
        )}
        {/* Greeting */}
        <section className="px-6 pt-8 pb-4">
          <h1 className="text-display text-on-surface font-bold">{getGreeting()}</h1>
          <p className="md:hidden text-[10px] font-bold text-on-surface-variant uppercase tracking-[0.2em] mt-1">
            {formatGreetingDate()}
          </p>
          <p className="hidden md:block text-body text-on-surface-variant mt-1">{formatGreetingDate()}</p>
        </section>

        {/* NLP Summary */}
        {morningBriefing?.content.summary && (
          <section className="px-6 pb-4">
            <p className="text-body text-on-surface-variant italic leading-relaxed">
              {morningBriefing.content.summary}
            </p>
          </section>
        )}

        {/* Today's Schedule — only when calendar events exist for today */}
        {todayEvents.length > 0 && (
          <SectionCard title="Today's Schedule" accent="text-green-500">
            <div className="rounded-xl bg-surface-container-low overflow-hidden">
              {todayEvents.map(e => <TodayEventRow key={e.id} event={e} />)}
            </div>
          </SectionCard>
        )}

        {/* Due Today */}
        {dueTodayItems.length > 0 && (
          <SectionCard title="Due Today" accent="text-indigo-400">
            {dueTodayItems.map(item => (
              <DueTodayRow
                key={item.thing.id}
                item={item}
                onDone={handleDoneThing}
                onSnooze={handleSnoozeThing}
                onChat={openChatWithContext}
              />
            ))}
          </SectionCard>
        )}

        {/* Needs Attention */}
        {findings.length > 0 && (
          <SectionCard title="Needs Attention" accent="text-amber-500">
            {findings.slice(0, 6).map(f => (
              <FindingCard
                key={f.id}
                finding={f}
                onDismiss={dismissFinding}
                onSnooze={handleSnooze}
                onAct={actOnFinding}
              />
            ))}
          </SectionCard>
        )}

        {/* I Noticed */}
        {learnedPreferences.length > 0 && (
          <SectionCard title="I Noticed" accent="text-purple-400">
            {learnedPreferences.map(pref => (
              <LearnedPreferenceCard
                key={pref.id}
                pref={pref}
                onFeedback={submitPreferenceFeedback}
              />
            ))}
          </SectionCard>
        )}

        {/* Stats footer */}
        {briefingStats && (
          <section className="px-6 pb-20 md:pb-8">
            {/* Mobile stats — border-top, 3-col grid, gradient text */}
            <div className="md:hidden grid grid-cols-3 gap-4 py-6 border-t border-white/5">
              <div className="text-center">
                <p className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant mb-1">Active</p>
                <p className="text-2xl font-black bg-gradient-to-br from-primary-container to-primary bg-clip-text text-transparent">{briefingStats.active_things}</p>
              </div>
              <div className="text-center">
                <p className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant mb-1">Due</p>
                <p className="text-2xl font-black text-events">{briefingStats.checkin_due}</p>
              </div>
              <div className="text-center">
                <p className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant mb-1">Overdue</p>
                <p className="text-2xl font-black text-ideas">{briefingStats.overdue}</p>
              </div>
            </div>
            {/* Desktop stats — existing glass cards */}
            <div className="hidden md:flex gap-3">
              <StatCard label="Active Things" value={briefingStats.active_things} />
              <StatCard label="Check-in Due" value={briefingStats.checkin_due} accent="text-events" />
              <StatCard label="Overdue" value={briefingStats.overdue} accent="text-ideas" />
            </div>
          </section>
        )}

        {/* Empty state */}
        {!hasContent && (
          <div className="flex flex-col items-center justify-center h-64 text-center px-6">
            <p className="text-4xl mb-3">{'\u2600\uFE0F'}</p>
            <p className="text-sm font-medium text-on-surface">Your morning briefing</p>
            <p className="text-xs text-on-surface-variant mt-1">
              Your morning briefing shows up here once you have Things with check-in dates.
            </p>
          </div>
        )}
      </div>
    </div>
  )
}
