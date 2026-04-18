# UX Strategy

How users should experience Reli — from first login to daily habit.

This document complements [vision.md](vision.md) (what Reli is) and [next-steps.md](next-steps.md) (engineering priorities) by focusing on how the product should *feel* and what design decisions get us there.

## The core UX tension

Reli's value compounds over time — a month of use produces a deeply personalized PA that a fresh install can't match. But users decide whether to stay in the first five minutes. Every UX decision must serve both ends: **demonstrate value immediately** while **rewarding long-term investment**.

## Design principles

1. **Show value before asking for input.** Every screen should demonstrate what the system can do, not wait for the user to figure it out.
2. **Earn trust incrementally.** Show what was understood, what was inferred, and let users correct. Trust compounds.
3. **Chat for conversation, direct manipulation for data.** Don't make users type "mark task X as done" when a checkbox would do.
4. **The briefing is the product.** If we nail the daily briefing, everything else follows. People add more Things because the briefing gets better with more data.
5. **Invisible when working, visible when learning.** Don't show pipeline stages. Do show when a new preference was learned or a new connection discovered.

---

## Phase 1: Onboarding and empty states

**Problem:** A new user logs in, sees an empty chat and an empty sidebar. They have no mental model of what a Thing is, what the system can do, or why they should trust it with their life context.

### Guided first conversation

Instead of a blank chat, Reli opens with a structured onboarding flow:

> "Let's get to know each other. What are you working on this week?"

The assistant asks 3-4 natural questions, creating Things from the answers in real time. The user watches the sidebar populate as they talk. This teaches the mental model by demonstration, not explanation.

**Key behaviors:**
- Create 3-5 Things from the initial conversation (mix of tasks, projects, people)
- Show each Thing appearing in the sidebar as it's created — the "aha" moment
- End the onboarding with a mini-briefing: "Here's what I know so far. Tomorrow morning I'll check in on these."

### Seed from existing data

During onboarding, offer a one-click "Import from Google Calendar + Gmail" option. Pre-populate Things from upcoming events, contacts, and recent threads. The user sees a populated sidebar in under a minute.

This is especially powerful because it feeds the context agent immediately — the very next conversation already has rich context to draw from.

### Empty state design

Every empty panel should show *what will appear there* and *what triggers it*:

| Panel | Current empty state | Target empty state |
|-------|--------------------|--------------------|
| Sidebar | "No Things" | "Things you mention in chat appear here — try telling me about a project." |
| Briefing | "No items" | "Your morning briefing shows up here once you have Things with check-in dates. Tell me about something you need to follow up on." |
| Detail panel | Blank | "Click any Thing in the sidebar to see its details, relationships, and history." |
| Preferences | Empty list | "As we talk, I'll learn how you like to work. You can always edit what I've picked up." |

### Success metric

A new user should have 5+ Things and understand the briefing concept within their first session, without reading any documentation.

---

## Phase 2: The briefing as daily driver

**Problem:** The briefing is Reli's killer feature — the thing that makes it feel like a real PA. But if it reads like a database query result, users won't come back for it.

### Make the briefing the landing page

When users open Reli in the morning, don't show yesterday's chat. Show a designed, scannable briefing view:

```
Good morning. Here's what needs your attention today.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📅 TODAY
  Dentist at 2pm — Dr. Garcia, 123 Main St
  Proposal draft due — you started this last Tuesday

⚡ NEEDS ATTENTION
  Energy contract expires in 12 days
  You mentioned booking flights for June — haven't yet

🔍 I NOTICED
  You've rescheduled 3 morning meetings this month
  → Learned: you prefer afternoons (moderate confidence)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

One screen. Zero scrolling. The user's entire day at a glance.

### Briefing should have a personality

The briefing should read like a note from a thoughtful assistant, not a status report:

- **Not:** "3 tasks due. 1 sweep finding."
- **Instead:** "Busy day — you've got that dentist at 2pm and the proposal draft is due. Your energy contract expires in 12 days, want me to look into alternatives?"

The personality adapts via the existing preference learning system — some users want terse bullet points, others want conversational summaries.

### Inline actions on briefing items

Each briefing item should have quick actions directly in the briefing view:

- **Snooze** — push the check-in date forward (tomorrow, next week, pick a date)
- **Done** — mark complete / archive
- **Open in chat** — start a conversation about this Thing
- **Dismiss** — for sweep findings the user doesn't care about (feeds back into preference learning)

The user should be able to process their entire briefing without navigating away from it.

### Success metric

Users who engage with the briefing on day 2 should be 3x more likely to be active on day 7. Track briefing open rate, items acted on, and time-to-process.

---

## Phase 3: Type-first sidebar and direct manipulation

**Problem:** "Thing" is maximally abstract. The sidebar currently presents a flat list. Users don't naturally think in universal entity types — they think in tasks, people, projects.

### Lead with types, not Things

Reorganize the sidebar into typed sections:

```
📋 TASKS (12)
  ▸ Active (8)
  ▸ Upcoming (4)

📁 PROJECTS (3)
  ▸ Website redesign
  ▸ Q2 planning
  ▸ Move to new apartment

👤 PEOPLE (7)
  ▸ Recent mentions

📝 NOTES & IDEAS (15)
  ▸ Recent
```

Each section is collapsible. Counts give a quick sense of scope. The "Thing" abstraction still powers everything underneath — this is purely a presentation change.

### Direct manipulation

The sidebar and detail panel should support direct interaction, not just viewing:

- **Click a task checkbox** to toggle done
- **Drag Things** to reorder by priority
- **Inline edit titles** — click to edit, Enter to save
- **Right-click context menu** — snooze, archive, move to project, delete
- **Bulk select** — check multiple Things, then batch archive/snooze/delete

The chat is for conversation. Structured data deserves structured interaction.

### Quick-add shortcuts

A "+" button in the sidebar (or a floating action button) with type-specific quick-add:

- "Add a task" — pre-fills type_hint, focuses on title input
- "Note an idea" — opens a minimal note capture
- "Remember a person" — prompts for name and context

These bypass the chat for simple data entry. The reasoning agent still processes them (for linking, preference detection), but the user doesn't need to have a conversation just to jot something down.

### Success metric

Measure the ratio of chat-created vs. direct-created Things. A healthy ratio is roughly 60/40 — chat for complex/contextual creation, direct for quick capture.

---

## Phase 4: Command palette and power user features

**Problem:** Once users have 50+ Things and use Reli daily, they need fast navigation. Clicking through the sidebar doesn't scale.

### Command palette (Cmd+K / Ctrl+K)

A spotlight-style command palette for fast access:

- **Search Things** — type any query to search by title and type
- **Quick actions** — built-in shortcuts for common actions
- **Navigation** — "Go to Projects", "Open settings"

The command palette should be the fastest way to do anything in Reli. It uses title-based search (SQL LIKE) for Thing results; semantic search may be added in a future iteration.

#### Query prefix syntax

| Prefix | Behavior | Example |
|--------|----------|---------|
| (none) | Search Things + show Quick Actions | `proposal draft` |
| `>` | Show only Quick Actions (hide Things) | `> add task` |
| `#type` | Filter Things by type, then search | `#task proposal` |

Supported type values match Thing `type_hint` values: `task`, `project`, `note`, `person`, `idea`, `goal`, `preference`.

### Keyboard shortcuts

| Shortcut | Action |
|----------|--------|
| `Cmd+K` | Command palette |
| `Cmd+N` | Quick-add Thing |
| `Cmd+B` | Toggle sidebar |
| `Cmd+Enter` | Send chat message |
| `Cmd+.` | Toggle briefing |
| `/` | Focus chat input |
| `Esc` | Close panels / back to chat |

### Structured views beyond chat

For users with enough data, offer additional views:

- **Calendar view** — Things with dates plotted on a week/month grid
- **Priority board** — Kanban-style columns (P1 through P5) for tasks
- **People view** — Contact cards with recent mentions and relationships
- **Graph view** — Visual knowledge graph showing Thing relationships (power user feature, not default)

These views are read-heavy and action-light — they help users *understand* their data. Chat remains the primary way to *change* it.

### Success metric

Power users (30+ days, 100+ Things) should spend <2 seconds navigating to any Thing or action. Track command palette usage and time-to-action.

---

## Phase 5: Proactive intelligence

**Problem:** Reli's biggest value proposition is proactive assistance — "bring a change of clothes, you have that event tonight." The infrastructure exists (sweep, concerns, proactive API) but the delivery is passive.

### Push notifications

Browser notifications (with explicit permission) for time-sensitive insights:

- "Your meeting with Sarah is in 30 minutes — here's context from your last conversation"
- "The proposal draft is due tomorrow and you haven't started the financial section"
- "Price drop: flights to Barcelona in June are 20% cheaper than last week"

Notifications should be rare and high-value. The preference system should learn which notification types the user engages with and suppress the rest. A notification the user always dismisses is a bug, not a feature.

### Interstitial nudges

When the user opens Reli (not from a notification), surface one proactive insight at the top of the view before they type anything:

```
💡 Quick note: you mentioned wanting to book flights for June —
   prices for your usual route dropped 20% this week.
   [Look into it] [Dismiss] [Stop these]
```

The "[Stop these]" option is critical — it feeds directly into preference learning. Users who feel they can control the system's proactivity will trust it more.

### Weekly digest

A weekly summary delivered through the user's preferred channel (in-app, email, Telegram):

- Things completed this week
- New connections discovered
- Preferences learned or strengthened
- Upcoming deadlines and check-ins
- Open questions the system still has

This serves two purposes: it drives re-engagement for lapsed users, and it makes the learning flywheel *visible* — users can see that Reli is getting smarter over time.

### Success metric

Proactive nudges that lead to user action within 24 hours. Target: 40%+ action rate on delivered nudges (if lower, the system is being too noisy).

---

## Cross-cutting concerns

### Progressive disclosure

Don't show everything at once. Features should unlock naturally as the user's data grows:

| Things count | Unlocked feature |
|-------------|-----------------|
| 0 | Guided onboarding conversation |
| 5+ | Briefing becomes meaningful |
| 10+ | "I noticed some connections" — relationship discovery |
| 20+ | Priority board view becomes useful |
| 50+ | Command palette becomes essential |
| 100+ | Graph view, weekly digest, advanced search |

The UI should adapt to the user's maturity level, not present every feature on day one.

### Transparency and trust

The "Context & Changes" panel in chat is valuable for trust-building, but needs refinement:

- **Default to subtle** — Show a small pill ("3 things updated") that expands on click
- **Highlight surprises, not expectations** — If the user said "remind me to call Mom" and a task was created, that's expected. If the system *inferred* a connection to travel plans, highlight that.
- **Show preference learning** — When the system acts on a learned preference, surface it: "Based on your usual preference for afternoon meetings..."
- **Confidence indicators** — Let users see and edit the system's confidence in its preferences about them

### Mobile considerations

Reli's primary interface is desktop web, but mobile access matters for quick capture and briefing consumption:

- The briefing view should be fully responsive and optimized for mobile
- Quick-add should work with minimal taps
- Chat should support voice input (already partially implemented)
- The full sidebar and detail panel can be simplified on mobile — the chat and briefing are what matter

### Personality as UX

Reli's personality (defined in [PERSONALITY_REFERENCE.md](PERSONALITY_REFERENCE.md)) is a UX surface. The same information delivered in the right tone feels helpful; in the wrong tone, it feels robotic or intrusive.

Key personality UX principles:
- **Brevity by default, detail on request.** "You have 3 things today" not a paragraph.
- **Confidence-appropriate hedging.** "I think you prefer mornings" (emerging) vs. "You always prefer mornings" (strong).
- **Never patronize.** Don't explain what a Thing is after the first session. Don't celebrate trivial completions.
- **Personality adapts.** The preference system should learn communication style preferences just like it learns scheduling preferences.

---

## Implementation notes

This strategy is designed to be implemented incrementally alongside the engineering roadmap in [next-steps.md](next-steps.md). Some mappings:

| UX Phase | Depends on |
|----------|-----------|
| Phase 1 (Onboarding) | Core pipeline stability, Google OAuth (both exist) |
| Phase 2 (Briefing) | Sweep (#192), briefing API (exists) |
| Phase 3 (Type-first sidebar) | Frontend only — no backend changes |
| Phase 4 (Command palette) | Vector search (exists), frontend work |
| Phase 5 (Proactive) | Concerns (new), push notification infrastructure, preference learning (#191) |

Each phase delivers standalone value. Users benefit from Phase 1 even if Phase 5 is months away. The phases are ordered by impact-to-effort ratio — onboarding and briefing improvements are high-impact, moderate-effort changes that set the foundation for everything else.
