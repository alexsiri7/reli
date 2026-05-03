import type { MorningBriefing, WeeklyBriefing } from '../generated/api-types'

/** Render a morning briefing as plain text suitable for seeding an LLM `system` message.
 *  Drops empty sections; uses only the first entry of `reasons[]` to keep the seed compact. */
export function serialiseMorningBriefing(b: MorningBriefing): string {
  const c = b.content
  const lines: string[] = [`Daily briefing — ${b.briefing_date}`]
  if (c.summary) lines.push(`\nSummary: ${c.summary}`)
  if (c.priorities.length) {
    lines.push('\nPriorities:')
    c.priorities.forEach(i => lines.push(`  • ${i.title}${i.reasons.length ? ` — ${i.reasons[0]}` : ''}`))
  }
  if (c.overdue.length) {
    lines.push('\nOverdue:')
    c.overdue.forEach(i => lines.push(`  • ${i.title}${i.days_overdue != null ? ` — ${i.days_overdue}d overdue` : ''}`))
  }
  if (c.blockers.length) {
    lines.push('\nBlockers:')
    c.blockers.forEach(i => lines.push(`  • ${i.title}`))
  }
  if (c.findings.length) {
    lines.push('\nNeeds attention:')
    c.findings.forEach(f => lines.push(`  • ${f.message}`))
  }
  return lines.join('\n')
}

/** Render a weekly briefing as plain text suitable for seeding an LLM `system` message.
 *  Drops empty sections. Mirrors the field set rendered in the WeeklyBriefingSection UI. */
export function serialiseWeeklyBriefing(b: WeeklyBriefing): string {
  const c = b.content
  const lines: string[] = [`Weekly review — week of ${b.week_start}`]
  if (c.summary) lines.push(`\nSummary: ${c.summary}`)
  if (c.completed.length) {
    lines.push('\nCompleted this week:')
    c.completed.forEach(i => lines.push(`  • ${i.title}`))
  }
  if (c.upcoming.length) {
    lines.push('\nUpcoming:')
    c.upcoming.forEach(i => lines.push(`  • ${i.title}${i.detail ? ` — ${i.detail}` : ''}`))
  }
  if (c.new_connections.length) {
    lines.push('\nNew connections this week:')
    c.new_connections.forEach(conn => lines.push(`  • ${conn.from_title} → ${conn.to_title}${conn.relationship_type ? ` (${conn.relationship_type})` : ''}`))
  }
  if (c.preferences_learned.length) {
    lines.push('\nPreferences learned:')
    c.preferences_learned.forEach(p => lines.push(`  • ${p}`))
  }
  if (c.open_questions.length) {
    lines.push('\nOpen questions:')
    c.open_questions.forEach(i => lines.push(`  • ${i.title}`))
  }
  return lines.join('\n')
}
