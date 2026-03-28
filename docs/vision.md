# Vision

Reli is an attempt to push the concept of a personal AI assistant to its limits. Not a chatbot with memory bolted on, but a system that genuinely models you and gets better over time.

## A system that models you

The core insight is that a PA's value comes from understanding the person it serves. Reli builds this understanding through three mechanisms:

**The knowledge graph.** Everything Reli knows is stored as typed Things with relationships. People, events, tasks, preferences, patterns — all linked. This structure is what allows Reli to reason across domains: "your dentist is near the restaurant you're going to Thursday."

**Preference learning.** Every interaction is a data point. Explicit corrections ("I hate morning meetings") create immediate preferences. Implicit patterns (you keep rescheduling mornings) are detected over time. Preferences are first-class Things with confidence levels:

- **Emerging** — first observation, a hypothesis
- **Moderate** — 2-3 observations, gaining confidence
- **Strong** — 4+ observations, reliable pattern

Preferences can conflict ("prefers working alone" but "always invites Tom to brainstorms"). Context determines which applies — that's fine. They evolve, and the user can see and edit them.

**Personality adaptation.** Reli's communication style itself is learnable. How verbose to be, whether to use bullet points or prose, how often to ask clarifying questions, how proactive to be with suggestions. New users get a sensible default. Long-term users get a PA that communicates the way they prefer.

### Signals that drive learning

| Signal type | Example | Effect |
|------------|---------|--------|
| Positive | User follows a suggestion, says "thanks" | Strengthen the approach used |
| Negative | User says "too much detail", ignores suggestion | Weaken that approach |
| Explicit correction | "Don't use emoji" / "Be more concise" | Immediate strong preference |
| Implicit correction | User consistently edits Thing titles after creation | Naming patterns don't match expectations |
| Behavioral | User reads briefings but ignores staleness alerts | Briefings valued, staleness alerts aren't |

## Concerns

Reli's domain intelligence is modular. A **concern** is an area of life that Reli monitors on your behalf:

- **Health** — knows "dentist every 6 months" is worth tracking, searches your calendar/email to find when you last went, asks you about it when appropriate
- **Finance** — watches for contract expiry dates, suggests renegotiation at the right time
- **Travel** — checks visa requirements when you book a flight to a new country

Each concern has a lifecycle:

1. **Initialize** — scan email, calendar, and existing Things to build an understanding of where you stand in this domain. Surface open questions ("when did you last go to the dentist?")
2. **Watch** — react to new inputs that match this domain (a billing email, a calendar appointment, a conversation mention) rather than polling everything. Update Things and questions as new information arrives.

The user doesn't teach Reli everything from scratch — the concern provides the domain framework (what matters, what cadences to track, what questions to ask), and Reli fills it in with *your* specifics.

Concerns also connect to the preference system. A health concern might start by asking lots of questions, but over time it learns what you care about (dental, exercise) and what you ignore (sleep tracking suggestions), and adjusts.

## The nightly sweep

The sweep is Reli's planning session. It's not a cleanup job — it's when Reli *thinks* about your life.

**What the sweep does:**

- **Coordinates concerns** — checks if any watched conditions have triggered across all active concerns
- **Calendar lookahead** — what's coming this week that needs preparation or attention?
- **Gap detection** — "you mentioned a conference but never said which days"
- **Pattern aggregation** — "you've rescheduled 3 morning meetings this month" → strengthen "avoids mornings" preference
- **Briefing assembly** — prioritized by urgency and your patterns, not just chronological

**What the sweep doesn't do:**

- Run every concern fully every night. Once a concern is initialized and stable, it waits for relevant updates before resurfacing.
- Replace real-time learning. The reasoning agent catches obvious signals during conversation. The sweep catches subtler patterns across many interactions.

The sweep output is a briefing — delivered through whatever channel makes sense (web UI, Telegram, email). Not just "here's your calendar" but "here's what needs your attention, across all the domains you care about."

## Memory layers

Reli maintains three layers of memory:

| Layer | Storage | Purpose |
|-------|---------|---------|
| **Long-term** | Things DB (knowledge graph) | Persistent structured knowledge — people, events, preferences, relationships |
| **Short-term** | Rolling conversation summary | Compressed conversation context for continuity across sessions |
| **Task context** | Context agent retrieval | Only what's needed for the current request |

The knowledge graph is long-term memory. The rolling conversation summary captures flow, intent, and recent decisions without duplicating what's already stored as Things. The context agent retrieves only what's relevant per request.

This means conversations can go indefinitely without context window issues, while maintaining continuity ("last time you mentioned wanting to move the trip...").

## MCP: intelligence as a service

Reli's value isn't tied to its chat UI. Through MCP (Model Context Protocol), any agent can tap into Reli's intelligence:

- **Prompts** that encode PA behavior — how to create Things, track preferences, handle relationships
- **Schema** contracts — what a Thing looks like, how confidence tracking works, what relationship types exist
- **Retrieval** — search the knowledge graph for relevant Things given any context
- **The accumulated user model** — preferences, patterns, and relationships that make any calling agent smarter about *you*

The key architectural decision: the calling agent (Claude Code, a Telegram bot, a voice assistant) does its own reasoning using Reli's prompts and data. Reli provides the intelligence substrate — the structured knowledge, the learned preferences, the domain framework from concerns — but doesn't force an extra LLM call. The client's model follows Reli's prompts to act as a PA.

This means your PA knowledge follows you across every tool you use. Claude Code knows your scheduling preferences. A Telegram bot knows your health concerns. A voice assistant knows your travel patterns. All from the same knowledge graph.

### Data integrity

When multiple clients write to the same knowledge graph, there's a risk of corruption — a lesser model might misinterpret the schema and make destructive updates. The current approach is to keep a mutations journal (append-only log of all changes) so the sweep can audit and roll back bad changes. A validation layer (where changes are proposed and reviewed before committing) is a future consideration for multi-user scenarios.

## Multi-channel delivery

The web UI is one interface. Reli's proactive intelligence should reach you where you are:

- **Telegram bot** — morning briefings, quick questions, proactive nudges ("bring a change of clothes today")
- **Claude Code** via MCP — development context ("what did I decide about the auth rewrite?")
- **Email** — weekly summaries or time-sensitive alerts

The intelligence is decoupled from delivery. Adding a new channel means connecting to Reli's API/MCP, not rebuilding the PA logic.

Integration with projects like [OpenClaw](https://github.com/openclaw/openclaw) (a multi-channel AI assistant framework supporting 23+ messaging platforms) could provide broad delivery coverage without building each channel integration from scratch. The security model would need evaluation, but architecturally Reli's MCP server would be a natural fit as an OpenClaw skill/tool.

## External source ingestion

Conversation is one input channel. Reli also learns from:

- **Google Calendar** — schedule, recurring patterns, time preferences
- **Gmail** — confirmations, receipts, appointments, contracts
- **Documents** — anything you feed it

These sources feed the knowledge graph. Concerns know what to look for in each source: a health concern scans for appointment confirmations, a finance concern watches for billing emails and contract renewals.

## The learning flywheel

Everything connects into a reinforcing loop:

```
Real-time (every interaction):
  Reasoning agent -> extracts preferences + generates questions
                                    |
Background (nightly sweep):
  Sweep -> coordinates concerns, detects gaps, aggregates patterns
  Sweep -> generates briefing with questions + insights
                                    |
Next interaction:
  Context agent -> retrieves Things + preferences + open questions
  Reasoning agent -> acts with full knowledge of who you are
```

Interactions produce preferences. Preferences improve context. Better context produces better interactions. The system compounds — a month of use produces a deeply personalized PA that a fresh install can't match.
