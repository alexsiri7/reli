import { useState, useCallback } from 'react'
import { useShallow } from 'zustand/react/shallow'
import { useStore } from '../store'
import type { SweepFinding, BriefingItem, LearnedPreference } from '../store'

const FINDING_TYPE_ICONS: Record<string, string> = {
  approaching_date: '\u23F0',
  stale: '\u{1F4A4}',
  neglected: '\u{1F6A8}',
  overdue_checkin: '\u{1F4C5}',
  orphan: '\u{1F50D}',
  inconsistency: '\u26A0\uFE0F',
  open_question: '\u2753',
  connection: '\u{1F517}',
}

const FINDING_TYPE_COLORS: Record<string, string> = {
  approaching_date: 'bg-events',
  stale: 'bg-on-surface-variant',
  neglected: 'bg-ideas',
  overdue_checkin: 'bg-ideas',
  orphan: 'bg-primary',
  inconsistency: 'bg-events',
  open_question: 'bg-people',
  connection: 'bg-projects',
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

function urgencyLabel(urgency: number): { text: string; className: string } {
  if (urgency >= 0.8) return { text: 'Urgent', className: 'text-ideas' }
  if (urgency >= 0.5) return { text: 'Soon', className: 'text-events' }
  return { text: 'Upcoming', className: 'text-on-surface-variant' }
}

function OneThingCard({ item, onClick }: { item: BriefingItem; onClick: () => void }) {
  const urg = urgencyLabel(item.urgency)
  return (
    <button
      onClick={onClick}
      className="w-full text-left glass rounded-2xl p-6 hover:bg-surface-container-high/80 transition-colors cursor-pointer"
    >
      <p className="text-label text-on-surface-variant mb-2">The One Thing</p>
      <h3 className="text-headline text-on-surface font-semibold mb-3 leading-tight">
        {item.thing.title}
      </h3>
      {item.reasons.length > 0 && (
        <p className="text-body text-on-surface-variant mb-3">
          {item.reasons[0]}
        </p>
      )}
      <div className="flex items-center gap-3">
        <span className={`text-label font-medium ${urg.className}`}>{urg.text}</span>
        <span className="text-label text-on-surface-variant">
          Score {item.score.toFixed(1)}
        </span>
      </div>
    </button>
  )
}

function PriorityFocusCard({ item, onClick }: { item: BriefingItem; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="w-full text-left rounded-xl p-4 bg-surface-container-low hover:bg-surface-container-high transition-colors cursor-pointer flex items-center gap-4"
    >
      <div className="flex-1 min-w-0">
        <p className="text-sm text-on-surface font-medium truncate">{item.thing.title}</p>
        {item.reasons.length > 0 && (
          <p className="text-xs text-on-surface-variant mt-0.5 truncate">{item.reasons[0]}</p>
        )}
      </div>
      <span className="gradient-cta text-xs font-medium px-3 py-1.5 rounded-lg shrink-0">
        Focus
      </span>
    </button>
  )
}

function FindingCard({ finding, onDismiss, onSnooze, onAct }: {
  finding: SweepFinding
  onDismiss: (id: string) => void
  onSnooze: (id: string) => void
  onAct: (finding: SweepFinding) => void
}) {
  const icon = FINDING_TYPE_ICONS[finding.finding_type] ?? '\u{1F4CB}'
  const dotColor = FINDING_TYPE_COLORS[finding.finding_type] ?? 'bg-primary'
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

function LearnedPreferenceCard({
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
        <div className="flex items-center gap-2 mt-0.5 shrink-0">
          <span className="text-sm">{'\u{1F9E0}'}</span>
        </div>
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
    theOneThing, secondaryItems, briefingStats, findings, learnedPreferences,
    setRightView, openThingDetail, dismissFinding, snoozeFinding, actOnFinding, submitPreferenceFeedback,
  } = useStore(
    useShallow(s => ({
      theOneThing: s.theOneThing,
      secondaryItems: s.secondaryItems,
      briefingStats: s.briefingStats,
      findings: s.findings,
      learnedPreferences: s.learnedPreferences,
      setRightView: s.setRightView,
      openThingDetail: s.openThingDetail,
      dismissFinding: s.dismissFinding,
      snoozeFinding: s.snoozeFinding,
      actOnFinding: s.actOnFinding,
      submitPreferenceFeedback: s.submitPreferenceFeedback,
    }))
  )

  const handleSnooze = (id: string) => {
    const tomorrow = new Date()
    tomorrow.setDate(tomorrow.getDate() + 1)
    snoozeFinding(id, tomorrow.toISOString().slice(0, 10))
  }

  const hasContent = theOneThing || secondaryItems.length > 0 || findings.length > 0 || learnedPreferences.length > 0

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
        {/* Greeting */}
        <section className="px-6 pt-8 pb-4">
          <h1 className="text-display text-on-surface font-bold">{getGreeting()}</h1>
          <p className="text-body text-on-surface-variant mt-1">{formatGreetingDate()}</p>
        </section>

        {/* The One Thing hero card */}
        {theOneThing && (
          <section className="px-6 pb-6">
            <OneThingCard
              item={theOneThing}
              onClick={() => openThingDetail(theOneThing.thing.id)}
            />
          </section>
        )}

        {/* Priority Focus — first secondary item */}
        {secondaryItems.length > 0 && (
          <section className="px-6 pb-6">
            <p className="text-label text-on-surface-variant mb-2">Priority Focus</p>
            <div className="space-y-2">
              {secondaryItems.slice(0, 3).map(item => (
                <PriorityFocusCard
                  key={item.thing.id}
                  item={item}
                  onClick={() => openThingDetail(item.thing.id)}
                />
              ))}
            </div>
          </section>
        )}

        {/* I Noticed — learned preferences */}
        {learnedPreferences.length > 0 && (
          <section className="px-6 pb-6">
            <div className="flex items-center gap-2 mb-3">
              <p className="text-label text-on-surface-variant">I Noticed</p>
              <span className="text-[10px] text-on-surface-variant bg-surface-container-high px-1.5 py-0.5 rounded-full">
                AI-Learned
              </span>
            </div>
            <div className="space-y-2">
              {learnedPreferences.map(pref => (
                <LearnedPreferenceCard
                  key={pref.id}
                  pref={pref}
                  onFeedback={submitPreferenceFeedback}
                />
              ))}
            </div>
          </section>
        )}

        {/* Findings from Sweep */}
        {findings.length > 0 && (
          <section className="px-6 pb-6">
            <div className="flex items-center gap-2 mb-3">
              <p className="text-label text-on-surface-variant">Findings from Sweep</p>
              <span className="text-[10px] text-on-surface-variant bg-surface-container-high px-1.5 py-0.5 rounded-full">
                AI-Generated Insights
              </span>
            </div>
            <div className="space-y-2">
              {findings.slice(0, 6).map(f => (
                <FindingCard
                  key={f.id}
                  finding={f}
                  onDismiss={dismissFinding}
                  onSnooze={handleSnooze}
                  onAct={actOnFinding}
                />
              ))}
            </div>
          </section>
        )}

        {/* Stats footer */}
        {briefingStats && (
          <section className="px-6 pb-20 md:pb-8">
            <div className="flex gap-3">
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
            <p className="text-sm font-medium text-on-surface">No briefing yet</p>
            <p className="text-xs text-on-surface-variant mt-1">
              Add some Things with check-in dates and your briefing will appear here.
            </p>
          </div>
        )}
      </div>
    </div>
  )
}
