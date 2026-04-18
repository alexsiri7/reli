# Reli: Second Brain + Personal Assistant

## Vision

Reli is a **Personal Assistant (PA)**, not a database. The difference:
- A database stores what you tell it and retrieves what you ask for.
- A PA *knows more than you do* about your own life, anticipates what's
  relevant, and brings the right thing to mind at the right time.

This frees the user from "Level 1 thinking" (remembering, tracking, reminding)
so they can focus on **Level 2 thinking** (deciding, creating, strategizing).

A good PA:
- Remembers everything — people, projects, ideas, offhand comments
- Connects the dots — "Tom mentioned he knows someone at that company
  you're trying to partner with"
- Anticipates needs — "Your meeting with Sarah is tomorrow and you never
  followed up on the proposal she asked about"
- Asks the right questions — "You said Q2 budget is due soon but haven't
  set a deadline — when is it actually due?"

## Core Concept

Everything is a **Thing**. A Thing can be a project, a task, a person, an event,
a place, an idea, a note — anything worth remembering. Things exist in a graph,
connected to one another through relationships.

The brain is messy by nature. Users don't think in hierarchies — they think in
associations. "I'm going with Tom to the conference" creates three Things
(me, Tom, the conference) and two relationships (going-with, attending).

## Interaction Model

Reli is a **single ongoing conversation**, not a session-based chatbot. The user
doesn't "start new conversations" — they continue talking to their PA. Multiple
conversations is a crutch; we're exploring what the right way to interact with
a smart agent is.

This means:
- One conversation per user, running indefinitely
- The PA maintains continuity across days, weeks, months
- The user can pick up where they left off without re-explaining context
- "New session" is a UI/technical concern, not a user-facing concept

## Memory Architecture

Reli's memory operates in three layers, each with a different scope and lifetime:

| Layer | Storage | Purpose | Lifetime |
|-------|---------|---------|----------|
| **Long-term memory** | Things DB (knowledge graph) | People, projects, ideas, relationships — everything worth remembering | Permanent |
| **Short-term memory** | Rolling conversation summary + last N messages | Conversation flow, recent decisions, user intent | Rolling window |
| **Task context** | Context agent retrieval (vector search + SQL) | Only what's needed for the current request | Per-request |

### Long-term memory: Things DB

The knowledge graph IS the long-term memory. When the user says "Tom works at
Acme" — that's a Thing and a relationship, stored permanently. The PA doesn't
need to "remember" this in conversation history; it lives in the graph and gets
retrieved when relevant.

### Short-term memory: Rolling summary + recent messages

Conversations can't grow forever — context windows have limits, and old
back-and-forth becomes noise. Instead of sending full history to the agents:

1. Every N messages, a **summarization agent** compresses `previous_summary +
   messages_since_last_summary` into a new summary
2. The summary captures: ongoing topics, recent decisions, user preferences,
   unresolved threads
3. Agents receive: `[summary] + [last N raw messages]` — not the full history
4. Old messages are preserved in `chat_history` for UI scrollback, but agents
   only see the compressed form

The summary doesn't duplicate what's in Things. If the user created a project
last week, that's in the graph — the summary only tracks "we were discussing
next steps for the project."

### Task context: Context agent retrieval

Per-request, the context agent decides what's relevant: it generates search
queries, retrieves Things from the graph via vector search + SQL, and passes
only the needed context to the reasoning agent. This keeps each request focused
— the agent doesn't wade through the entire graph, just the neighborhood that
matters.

### How the layers interact

```
User: "What's the status on Tom's project?"
                    │
    ┌───────────────┼───────────────┐
    ▼               ▼               ▼
 Summary         Recent msgs     Context agent
 "We discussed   [last N turns    searches Things DB
  Tom's project   of raw chat]    → finds Tom, project,
  timeline                          tasks, relationships
  last week"
    │               │               │
    └───────────────┼───────────────┘
                    ▼
            Reasoning agent has full picture:
            conversation continuity + current state
```

## Learning the User: Preference Things

Reli doesn't just store information — it **models the user**. Every interaction
is a data point about who they are and how they operate. This is a core
differentiator: a database stores what you tell it; a PA learns *you*.

### How it works

The reasoning agent has two jobs on every interaction:
1. "What Things should I create/update based on what the user said?"
2. "What did I just learn about this user?"

Both explicit statements and inferred patterns become **preference Things**:

- **Explicit**: "I hate morning meetings" → immediate preference creation
- **Inferred**: user cancels morning meetings 3 times → preference emerges
- Even a single interaction is a signal — "Alex seems to prefer afternoons"

### Preference Things

Stored as regular Things with `type_hint: preference`. They have:

- **Confidence levels** — first observation is "emerging", repeated behavior
  becomes "strong". Tracks observation count.
- **Granularity** — starts broad ("doesn't like mornings"), refines over time
  ("doesn't like Monday mornings before 10am")
- **Negative preferences** — what the user avoids is as valuable as what
  they prefer
- **Conflict tolerance** — "prefers working alone" but "always invites Tom
  to brainstorms" can coexist. Context determines which applies.
- **Evolution** — each interaction can update existing preferences
- **Transparency** — user can see and edit them ("actually I don't mind
  Tuesday mornings")

### Examples

| User says | Preference learned |
|-----------|--------------------|
| "Move it to afternoon, I hate morning meetings" | "Avoids morning meetings" |
| "Let's invite the usual crew" | Reinforces "usual crew" = Tom, Sarah, Mike |
| "I'll handle budget later, venue first" | "Does venue-before-budget for events" |
| "Just book the cheap one" | "Optimizes for cost on travel" |

Learned preferences surface in the daily briefing under the **"I Noticed"**
section, where users can confirm or correct them. See
[Sweep output → "I Noticed"](#i-noticed--learned-preferences-in-the-briefing).

### Context integration

When the user mentions a topic, the context agent surfaces relevant preference
Things alongside factual Things. "Plan a party" retrieves both the party task
AND "Alex's approach to party planning." Preferences get a retrieval boost —
they're almost always relevant when their topic matches.

### Why this matters for the MCP vision

Preference Things are especially powerful when Reli is a shared memory service
(#190). Any agent that connects to Reli immediately knows how the user
operates. The preferences follow the user, not the client.

## The Learning Flywheel

The system is always absorbing, not just when the user explicitly tells it
something. Three mechanisms work together:

### Real-time: every interaction teaches

The reasoning agent has two outputs beyond its normal work:
1. **Preference extraction** — "what did I just learn about this user?"
2. **Priority question** — "what's the single most valuable thing to ask
   right now?" (always generated, not always asked — the response agent
   uses judgment on timing)

### Background: the sweep learns patterns

The nightly sweep doesn't just find stale Things. It also:

**Detects gaps** — Things with missing information get questions attached:
- "Conference trip" has no dates → "When is the conference?"
- Person "Sarah" has no context → "How do you know Sarah?"
- Project has tasks but no deadline → "When does this need to be done?"

**Aggregates patterns** — weak signals from individual interactions become
strong preferences:
- Rescheduled 3 morning meetings → strengthen "avoids mornings"
- Always picks cheapest travel option → "cost-conscious traveler"
- Mentions Tom in 60% of social planning → "Tom is core social group"

### The flywheel effect

```
Interactions → preferences → better context → better questions
     ↑                                              │
     └──────── richer interactions ←────────────────┘
```

Each turn makes the next turn smarter. The sweep compounds this overnight.
A PA that's been running for a month knows vastly more than one running for
a day — not just more facts, but more about *how the user thinks*.

## Thing Surface Levels

Not all Things are equal in visibility. The UI needs to distinguish:

### Tracked Things (surface in sidebar)
Things the user actively cares about. They show up in the sidebar, have
check-in dates, can be snoozed. Examples:
- **Projects**: "Launch new website", "Q2 budget planning"
- **Goals**: "Run a marathon", "Learn Spanish"
- **Active tasks**: "Review PR #42", "Call the dentist"

### Entity Things (exist in the graph, don't surface by default)
Things that are real and referenced, but don't need active tracking. They
surface when relevant — when mentioned in conversation, when connected to
a tracked Thing. Examples:
- **People**: "Tom", "Sarah from marketing"
- **Places**: "The office in Austin", "Blue Bottle Coffee on 5th"
- **Events**: "React Conf 2026", "Mom's birthday dinner"
- **Concepts**: "The auth refactor approach", "That idea about caching"

The distinction isn't type-based — a person CAN be tracked ("Check in with
Tom weekly") and a project CAN be an entity (a past project referenced for
context). **The user decides what surfaces, not the system.**

**Exception: proactive surfacing.** The system CAN promote an entity Thing to
"top of mind" temporarily when time-sensitive data makes it relevant. If Tom
has a birthday in 3 days, Tom surfaces in the sidebar even though he's not
explicitly tracked. This is the system being a good assistant — reminding you
of things you'd want to know. These proactive surfaces are temporary and
disappear after the event passes.

## The Sidebar: "Top of Mind"

The sidebar is NOT an inventory. It's **what you should be thinking about
right now.** It combines:

1. **Tracked Things** — projects, active tasks, goals you're working on
2. **Upcoming dates** — check-ins, deadlines, birthdays approaching
3. **Recently discussed** — Things from recent conversations (fades over time)
4. **Proactive surfaces** — entity Things the system thinks are relevant now
5. **Review flags** — Things the overnight sweep tagged for attention

The sidebar should have a **search bar** at the top. Search reaches into the
full graph — every Thing, every entity, every relationship — not just what's
currently surfaced. This is how you access the deep brain.

## Relationships

Things connect to other Things. Relationships are typed and directional:

### Structural relationships
- **parent-of / child-of**: Project → Task, Goal → Milestone
- **depends-on / blocks**: Task A must finish before Task B
- **part-of**: "Chapter 3" is part of "The Book"

### Associative relationships
- **related-to**: Generic connection ("this reminds me of that")
- **involves**: "Conference trip" involves "Tom", "Hotel booking", "Talk prep"
- **tagged-with**: Lightweight grouping without hierarchy

### Temporal relationships
- **followed-by / preceded-by**: Sequential events
- **spawned-from**: "This task came from that meeting"

## The Nightly Sweep (Background Process)

A scheduled background process (default: once daily at a quiet hour) where
Reli reviews its knowledge and surfaces things that need the user's attention.
This is the PA "thinking overnight" — anticipating tomorrow's needs.

### Design principle: incremental, not exhaustive

The sweep must NOT read the entire graph through the LLM every night. That's
expensive and unnecessary. A good PA doesn't re-read every file in the
cabinet — they know what's time-sensitive and check those things.

**Two-phase architecture:**

**Phase 1: SQL candidate selection (cheap, no LLM)**
Identify Things that might need attention using simple queries:
- Things with dates in the next 7 days (birthdays, deadlines, check-ins)
- Active Things not updated in 14+ days (staleness)
- Things with no relationships (orphans)
- Projects where all children are inactive but project is still active
- Unanswered questions from recent chat history (last AI question with
  no subsequent user message in that thread)

**Phase 2: LLM reflection (targeted, small context)**
Send ONLY the candidate Things (typically 5-20 items) to the LLM with
the prompt: "You are reviewing these items for the user. What should they
know tomorrow? What's urgent, what's been forgotten, what connections
should they be aware of?"

This keeps LLM costs proportional to the number of *interesting* Things,
not the total graph size. A graph with 1,000 Things but only 8 candidates
costs the same as a graph with 50 Things and 8 candidates.

### What the sweep catches

**Time-sensitive surfacing:**
- Approaching dates: birthdays, deadlines, check-in dates within N days
- Entity Things with temporal data becoming relevant (Tom's birthday)
- Promote these to "top of mind" temporarily

**Staleness detection:**
- Active Things untouched for 2+ weeks → tag for review
  ("Are you still working on the website redesign?")
- Tasks with no progress → suggest breaking down or deferring

**Orphan detection:**
- Things with no relationships → might be forgotten or need connecting
- Recently created Things that were never referenced again

**Inconsistency checks:**
- Projects with all tasks complete but project still "active"
- Dependencies where the blocker is done but the blocked task hasn't started
- Overdue check-in dates that were never snoozed or completed

**Open questions:**
- Past conversations where the AI asked a clarifying question but never
  got an answer → resurface the question

**Connection opportunities (LLM-powered):**
- "You mentioned Tom knows someone at Acme Corp — you're also tracking
  a partnership outreach to Acme. Want to ask Tom for an intro?"
- "The conference you're attending has a talk on caching — you had an
  idea about caching last week. Might be relevant."

### Sweep output

The sweep produces a **daily briefing** that appears at the top of the
sidebar. It's a short, prioritized list:

- "Tom's birthday is Thursday — want to set a reminder?"
- "Website redesign has been idle for 2 weeks. Still active?"
- "You never answered: what's the deadline for the Q2 report?"
- "3 tasks under 'Launch prep' are done — looks like the project is complete?"

The user can dismiss, snooze, or act on each item. Acting opens the relevant
Thing in the chat context.

### "I Noticed" — learned preferences in the briefing

The briefing also includes an **"I Noticed"** section showing up to 5 learned
preferences (Things with `type_hint: preference`). Each preference shows:

- Its title (e.g., "Prefers afternoon meetings")
- A confidence label: `emerging`, `moderate`, or `strong`
- Feedback buttons: **"That's right"** (reinforces) / **"Not really"** (flags)

The confidence label is derived from the preference Thing's `confidence` field:
≥0.7 → `strong`, ≥0.5 → `moderate`, else `emerging`. If the preference uses the
`patterns` list format, the first pattern's confidence is used.

Feedback routes to the existing preference feedback endpoint
(`POST /api/preferences/{id}/feedback`) without requiring a separate API call
from the user.

### Implementation notes

The sweep runs on a schedule (cron or similar). It writes findings to a
`sweep_findings` table with expiry dates. The briefing endpoint reads
from these findings. Findings expire automatically (birthday reminder
disappears after the date passes).

Cost target: the nightly sweep should cost less than a single chat
interaction. If it's costing more, the SQL candidate selection isn't
filtering aggressively enough.

## How the AI Uses This

### Context Agent (Stage 1)
When searching for relevant Things, follow the graph:
- User mentions "Tom" → find Tom → find everything connected to Tom
- User asks about "the website project" → find project → find all children,
  dependencies, involved people, related notes

### Reasoning Agent (Stage 2)
When deciding what to create/update:
- "I'm going with Tom to React Conf" →
  - Find or create Tom (entity, type: person)
  - Find or create React Conf (entity, type: event)
  - Create relationship: user → attending → React Conf
  - Create relationship: Tom → attending → React Conf
  - Create relationship: user → going-with → Tom (for this event)
  - DON'T surface Tom or React Conf in sidebar unless user asks
- "Start a project to redesign the homepage" →
  - Create "Redesign homepage" (tracked, type: project)
  - Surface in sidebar
  - If user describes subtasks, create them as children
- "Tom's birthday is March 20th" →
  - Find or create Tom (entity, type: person)
  - Store birthday in Tom's data: `{"birthday": "03-20"}`
  - The sweep will handle surfacing this when it's approaching

### Response Agent (Stage 4)
When responding, show awareness of the graph:
- "Got it, I've added the React Conf trip. Tom's coming too — want me to
  track any prep tasks for it?"
- "That's the third task under the website redesign — you're 2/5 done!"

## UI Implications

### Sidebar
- **Search bar** at top — searches full graph
- **Daily briefing** section — sweep findings, dismissable
- **Top of mind** — tracked Things + proactive surfaces, grouped by type
- Projects show child count and completion progress
- Proactive surfaces have a subtle indicator (why they're showing)

### Thing Detail View
- Expand a Thing to see all its connections
- Show related entities, child tasks, dependencies
- Show a mini-graph of connections (nice-to-have)

### Chat Context
- When discussing a Thing, the AI has access to its full graph neighborhood
- "What's the status of the website project?" pulls the project + all
  children + their statuses + involved people

## Data Model Changes Needed

### Current: things table
```
id, title, type_hint, parent_id, checkin_date, priority, active, data
```

### Proposed additions:

**thing_relationships table:**
```
id, from_thing_id, to_thing_id, relationship_type, metadata, created_at
```
This replaces the flat parent_id with a proper graph. parent_id can stay
as a shortcut for the common parent-child case.

**sweep_findings table:**
```
id, thing_id, finding_type, message, priority, dismissed, created_at, expires_at
```
Stores review sweep output. Feeds the daily briefing. Findings expire
automatically (birthday reminder disappears after the date passes).

**New type_hints:**
- Current: task, note, idea, project, goal, journal
- Add: person, place, event, concept, reference

**New Thing fields:**
- `surface`: boolean — whether this Thing appears in the sidebar (default: true
  for tasks/projects/goals, false for entity types)
- `last_referenced`: timestamp — when this was last mentioned in conversation
  (for relevance ranking and staleness detection)

## Migration Path

1. Add `thing_relationships` table (non-breaking)
2. Add `sweep_findings` table (non-breaking)
3. Add `surface`, `last_referenced` columns (non-breaking, sensible defaults)
4. Update reasoning agent prompts to create relationships and entities
5. Update context agent to traverse relationships when searching
6. Build the review sweep as a scheduled background job
7. Update sidebar: add search, briefing section, grouped display
8. Update ThingCard to show relationship context and expand into detail view
