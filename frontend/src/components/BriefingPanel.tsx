import { useState, useRef, useEffect } from 'react'
import { useShallow } from 'zustand/react/shallow'
import { useStore, serialiseMorningBriefing } from '../store'
import type { SweepFinding, BriefingItem, LearnedPreference, CalendarEvent } from '../store'
import { NudgeBanner } from './NudgeBanner'

const FINDING_TYPE_CONFIG: Record<string, { icon: string; borderClass: string }> = {
  approaching_date: { icon: '\u23F0', borderClass: 'border-events' },
  stale: { icon: '\u{1F4A4}', borderClass: 'border-on-surface-variant' },
  neglected: { icon: '\u{1F6A8}', borderClass: 'border-ideas' },
  overdue_checkin: { icon: '\u{1F4C5}', borderClass: 'border-ideas' },
  orphan: { icon: '\u{1F50D}', borderClass: 'border-primary' },
  inconsistency: { icon: '\u26A0\uFE0F', borderClass: 'border-events' },
  open_question: { icon: '\u2753', borderClass: 'border-people' },
  connection: { icon: '\u{1F517}', borderClass: 'border-projects' },
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

function dateOffsetISO(days: number): string {
  const d = new Date()
  d.setDate(d.getDate() + days)
  return d.toISOString().slice(0, 10)
}

function SectionCard({ title, accent, children, childrenClassName }: {
  title: string
  accent: string
  children: React.ReactNode
  childrenClassName?: string
}) {
  return (
    <section className="px-6 pb-6">
      <p className={`text-label font-semibold mb-2 ${accent}`}>{title}</p>
      <div className={childrenClassName ?? 'space-y-2'}>{children}</div>
    </section>
  )
}

function SnoozeMenu({ onSelect, onClose }: {
  onSelect: (date: string) => void
  onClose: () => void
}) {
  const menuRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) onClose()
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [onClose])

  return (
    <div ref={menuRef} className="absolute z-10 top-full left-0 mt-1 bg-surface-container-high border border-surface-container-highest rounded-xl shadow-lg overflow-hidden text-xs">
      <button className="block w-full text-left px-4 py-2 hover:bg-surface-container-highest"
        onClick={() => { onSelect(dateOffsetISO(1)); onClose() }}>Tomorrow</button>
      <button className="block w-full text-left px-4 py-2 hover:bg-surface-container-highest"
        onClick={() => { onSelect(dateOffsetISO(7)); onClose() }}>Next week</button>
      <label className="block px-4 py-2 hover:bg-surface-container-highest cursor-pointer">
        Pick date…
        <input type="date" className="sr-only" min={dateOffsetISO(1)}
          onChange={e => { if (e.target.value) { onSelect(e.target.value); onClose() } }} />
      </label>
    </div>
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

export function DueTodayRow({ item, onDone, onSnooze, onChat, snoozeMenuOpen, onSnoozeToggle }: {
  item: BriefingItem
  onDone: (id: string) => void
  onSnooze: (id: string, date: string) => void
  onChat: (id: string, title: string) => void
  snoozeMenuOpen: boolean
  onSnoozeToggle: () => void
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
            <div className="relative">
              <button
                onClick={onSnoozeToggle}
                className="text-xs text-on-surface-variant hover:text-on-surface"
              >
                Snooze
              </button>
              {snoozeMenuOpen && (
                <SnoozeMenu
                  onSelect={(date) => onSnooze(item.thing.id, date)}
                  onClose={onSnoozeToggle}
                />
              )}
            </div>
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

export function FindingCard({ finding, isFirst, onDismiss, onSnooze, onAct, snoozeMenuOpen, onSnoozeToggle }: {
  finding: SweepFinding
  isFirst: boolean
  onDismiss: (id: string) => void
  onSnooze: (id: string, date: string) => void
  onAct: (finding: SweepFinding) => void
  snoozeMenuOpen: boolean
  onSnoozeToggle: () => void
}) {
  const typeConfig = FINDING_TYPE_CONFIG[finding.finding_type]
  const icon = typeConfig?.icon ?? '\u{1F4CB}'
  const borderColor = typeConfig?.borderClass ?? 'border-primary'
  return (
    <div className={`group bg-surface-container-high rounded-2xl border-l-4 ${borderColor} transition-colors ${isFirst ? 'col-span-2' : ''}`}>
      <div className={`flex items-start gap-3 ${isFirst ? 'p-6' : 'p-4'}`}>
        <span className={`${isFirst ? 'text-base' : 'text-sm'} mt-0.5 shrink-0`}>{icon}</span>
        <div className="flex-1 min-w-0">
          <p className={`text-on-surface ${isFirst ? 'text-sm font-medium' : 'text-xs font-medium leading-snug'}`}>{finding.message}</p>
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
            <div className="relative">
              <button
                onClick={onSnoozeToggle}
                className="text-xs text-on-surface-variant hover:text-on-surface"
              >
                Snooze
              </button>
              {snoozeMenuOpen && (
                <SnoozeMenu
                  onSelect={(date) => onSnooze(finding.id, date)}
                  onClose={onSnoozeToggle}
                />
              )}
            </div>
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

  const handleFeedback = (accurate: boolean) => {
    if (feedbackSent !== null) return
    setFeedbackSent(accurate)
    onFeedback(pref.id, accurate)
  }

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
    morningBriefing, calendarEvents, error, currentUser,
    setRightView, dismissFinding, snoozeFinding, actOnFinding,
    submitPreferenceFeedback, updateThing, snoozeThing, openChatWithContext,
    continueInChat,
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
      currentUser: s.currentUser,
      setRightView: s.setRightView,
      dismissFinding: s.dismissFinding,
      snoozeFinding: s.snoozeFinding,
      actOnFinding: s.actOnFinding,
      submitPreferenceFeedback: s.submitPreferenceFeedback,
      updateThing: s.updateThing,
      snoozeThing: s.snoozeThing,
      openChatWithContext: s.openChatWithContext,
      continueInChat: s.continueInChat,
    }))
  )

  const [snoozeMenuId, setSnoozeMenuId] = useState<string | null>(null)
  const firstName = currentUser?.name?.split(' ')[0] ?? null

  const handleDoneThing = (id: string) => updateThing(id, { active: false })

  const handleContinueInChat = () => {
    if (!morningBriefing) return
    const today = new Date().toLocaleDateString('en-CA')
    continueInChat(
      serialiseMorningBriefing(morningBriefing),
      `Morning briefing — ${today}`,
      'morning_briefing',
      "Here's what's on your plate today. What would you like to focus on?",
    )
  }

  const todayISO = new Date().toLocaleDateString('en-CA')  // YYYY-MM-DD in local TZ
  const todayEvents = calendarEvents.filter(e => e.start.slice(0, 10) === todayISO)

  const hasContent = theOneThing != null || secondaryItems.length > 0 || findings.length > 0 || learnedPreferences.length > 0 || todayEvents.length > 0

  return (
    <div className="flex-1 flex flex-col bg-canvas min-w-0 min-h-0">
      {/* Header bar — hidden on mobile (bottom tab bar handles navigation) */}
      <div className="hidden md:flex px-5 py-3 bg-surface-container-low shrink-0 items-center justify-between">
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
          <h1 className="text-display text-on-surface font-bold">
            {getGreeting()}{firstName ? `, ${firstName}` : ''}
          </h1>
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
            <button
              onClick={handleContinueInChat}
              className="mt-3 flex items-center gap-1.5 text-xs font-medium text-primary hover:text-primary/80 transition-colors"
            >
              <svg xmlns="http://www.w3.org/2000/svg" className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M8.625 12a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0H8.25m4.125 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0H12m4.125 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0h-.375M21 12c0 4.556-4.03 8.25-9 8.25a9.764 9.764 0 0 1-2.555-.337A5.972 5.972 0 0 1 5.41 20.97a5.969 5.969 0 0 1-.474-.065 4.48 4.48 0 0 0 .978-2.025c.09-.457-.133-.901-.467-1.226C3.93 16.178 3 14.189 3 12c0-4.556 4.03-8.25 9-8.25s9 3.694 9 8.25Z" />
              </svg>
              Continue in chat
            </button>
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

        {/* The One Thing — hero card */}
        {theOneThing && (
          <section className="px-6 pb-4">
            <div className="relative group">
              <div className="absolute inset-0 bg-gradient-to-br from-primary to-primary/20 blur-xl opacity-20 group-hover:opacity-30 transition-opacity rounded-[2rem]" />
              <div className="relative bg-surface-container-high p-8 rounded-[2rem] border-l-4 border-primary overflow-hidden">
                <div className="flex flex-col gap-3">
                  <div className="flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full bg-ideas animate-pulse shrink-0" />
                    <span className="text-[10px] uppercase tracking-[0.2em] font-bold text-on-surface-variant">Most Important</span>
                  </div>
                  <h3 className="text-3xl font-black tracking-tighter text-on-surface leading-tight">
                    {theOneThing.thing.title}
                  </h3>
                  {theOneThing.thing.checkin_date && (
                    <p className="text-sm font-medium text-primary">
                      Due {new Date(theOneThing.thing.checkin_date).toLocaleDateString(undefined, { weekday: 'long' })}
                    </p>
                  )}
                  <div className="flex items-center gap-2 mt-1 opacity-0 group-hover:opacity-100 transition-opacity">
                    <button
                      onClick={() => handleDoneThing(theOneThing.thing.id)}
                      className="text-xs text-primary hover:text-primary/80 font-medium"
                    >
                      Done
                    </button>
                    <button
                      onClick={() => openChatWithContext(theOneThing.thing.id, theOneThing.thing.title)}
                      className="text-xs text-on-surface-variant hover:text-on-surface"
                    >
                      Chat
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </section>
        )}

        {/* Due Today */}
        {secondaryItems.length > 0 && (
          <SectionCard title="Due Today" accent="text-indigo-400">
            {secondaryItems.map(item => (
              <DueTodayRow
                key={item.thing.id}
                item={item}
                onDone={handleDoneThing}
                onSnooze={snoozeThing}
                onChat={openChatWithContext}
                snoozeMenuOpen={snoozeMenuId === item.thing.id}
                onSnoozeToggle={() => setSnoozeMenuId(snoozeMenuId === item.thing.id ? null : item.thing.id)}
              />
            ))}
          </SectionCard>
        )}

        {/* Needs Attention */}
        {findings.length > 0 && (
          <SectionCard title="Needs Attention" accent="text-amber-500" childrenClassName="grid grid-cols-2 gap-4">
            {findings.slice(0, 6).map((f, index) => (
              <FindingCard
                key={f.id}
                finding={f}
                isFirst={index === 0}
                onDismiss={dismissFinding}
                onSnooze={snoozeFinding}
                onAct={actOnFinding}
                snoozeMenuOpen={snoozeMenuId === f.id}
                onSnoozeToggle={() => setSnoozeMenuId(snoozeMenuId === f.id ? null : f.id)}
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
            {/* Mobile stats — 3-col grid, gradient text */}
            <div className="md:hidden grid grid-cols-3 gap-4 py-8">
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
