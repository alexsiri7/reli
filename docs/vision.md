# Reli — Vision

**Version 4.0 · September 2026 · Supersedes v3.0 (April 2025) and the current `docs/vision.md`**

---

## 1. What Reli is

Reli is the memory and the obligations layer that lets Claude act as a complete personal assistant.

It is a service, not a product. It does no reasoning of its own, holds no conversation, and has one user. Its job is to hold everything worth remembering about that user's life, track what needs checking and when, and learn how the user actually operates — so that any Claude session, interactive or scheduled, starts already knowing. It has a web view for reading and navigating what it holds, and nothing else.

The completeness test is:

> **MCP + claude.ai + crons = a complete PA.**

If those three together don't cover it, it's a gap in Reli. If Reli is doing something those three could do better, Reli shouldn't be doing it.

## 2. What went wrong last time

This section exists so the next rebuild doesn't repeat the last one. It is not history for its own sake — each failure maps to a rule below.

**Reli grew its own brain.** A three-stage agent pipeline (Context → Reasoning → Response) was built inside the service, so every interaction paid for a second, weaker model to reason about data that a stronger model was already holding in context. The chat UI that pipeline served went essentially unused; the real interface turned out to be Claude via MCP.

**Proactivity became inference instead of data.** The original spec made `checkin_date` the mechanism for proactive attention — a date, a query, a result. The implementation replaced it with an LLM sweep that read everything and emitted "findings." Findings floated free of the facts that produced them, so nothing could tell a live finding from a dead one. The only three requirements that ever drove work in this repo were the cleanup: finding lifecycle and expiry, a sweep cleanup mandate, and confidence thresholds. All three were fixing a problem created by the shape of the data.

**Confidence was a number instead of evidence.** A preference carrying `confidence: 0.7` and no link to what caused it cannot be audited, corrected, or falsified. It can only be decayed by an algorithm guessing on the user's behalf.

**The vision doc was a manifesto.** Nine thousand words describing Concerns, multi-channel delivery, personality adaptation, memory layers and a learning flywheel — none of it small enough to build to, so the build went its own way. This document is deliberately shorter and deliberately says no more often than yes.

## 3. Principles

1. **No model inside Reli.** Reli is deterministic: storage, queries, and a journal. Every judgement call happens in Claude — interactively via MCP, or in a scheduled headless session. Reli can be fully tested without recording a single LLM interaction.
2. **Proactivity is a query, not an inference.** What needs attention is answerable from `checkin_date`, staleness and tags. Reasoning is applied to the result, never used to produce it.
3. **Every claim links to its evidence.** A preference, an inference, a derived state — each carries relationships to the Things and journal entries that support it. Nothing free-floating.
4. **The journal is the training data.** Every mutation is recorded, attributed and kept. It is not only an audit trail; it is the only source of implicit learning.
5. **Reli holds obligations, Claude discharges them.** A check-in is Reli's record that something needs verifying. Verifying it is Claude's job, and mostly happens without the user.
6. **Silence is the goal.** A loop Claude closed without telling the user is the best outcome. The briefing is what's left over, not a report of activity.
7. **One user, one instance, no accounts.** Multi-user, sharing and public release are out of scope until the single-user case is genuinely complete.

## 4. The layers

### 4.1 Reli — the data service

Python/FastAPI over Postgres. No LLM dependency. Four things live here:

**Things.** The universal entity, carried forward from v3.0 substantially unchanged: `title`, `description`, `notes` (a slug → markdown dictionary), `tags`, `urls`, `checkin_date`, `priority`, `active`, timestamps. Meaning emerges from tags and relationships rather than a type column. JSONB gives the schemaless flexibility the original spec wanted from MongoDB, without a second database technology.

**Relationships.** Typed, directional links between Things: `ChildOf`, `Blocks`, `RelatedTo`, `EvidenceFor`, `References`. Hierarchy is a `ChildOf` relationship and nothing else — `parent_id` does not exist. Two competing hierarchies is what made the last schema unsound.

**Queries.** Not just CRUD. The service answers the questions proactivity actually needs: what is due for check-in, what has gone stale, what is tagged `#NeedsInput`, what is blocked, what relates to this. These are indexed queries, not searches.

**The mutations journal.** Append-only. Every create, update, relate and delete, with actor (user, interactive Claude, cron), timestamp, and before/after state. Present from the first migration — retrofitting it means permanently losing the history that makes learning possible.

### 4.2 MCP — the only way in

Every action goes through MCP. Nothing writes to Reli except an MCP client, and there is no public API.

**Tools** cover the Things, relationships and queries above.

**Prompts** carry the PA behaviour — what to capture, when to set a check-in, how to name things, when to record a preference. This is what makes Claude behave as a PA without Reli owning a model. The operational "hats" from the original spec become prompts rather than backend modes: daily planning, project planning, review.

**Resources** expose the current user model, scoped, so a session loads the preferences relevant to what it's doing.

### 4.3 Scheduled Claude — the proactive half

Nothing runs on a schedule inside Reli. Proactivity is a set of Claude scheduled tasks with Reli's MCP attached, each a saved prompt on a cadence. The reasoning is done by a good model, and its output is ordinary Things that can be read, corrected and deleted.

Three tasks, in order, each depending on what the one before it wrote.

**1. Resolution pass** (overnight). Walk everything due for check-in and try to settle each one without the user. A check-in on "book flights for holiday X" is discharged by finding the confirmation in Gmail and marking it done — the user never hears about it. What can't be resolved, or needs a decision, is written up as a briefing Thing for the day.

**2. Learning pass** (overnight). Read the journal since the last run and look for behavioural patterns: check-in dates repeatedly pushed from Mondays, Claude-generated titles the user consistently rewrites, whole tag families never touched. Write what it finds as preference Things, evidence-linked.

**3. Morning conversation** (waking hours). Claude opens a chat and tells the user about their day. It does not redo the resolution pass — it reads the briefing Thing that already exists and presents it, shaped by scheduling and communication preferences from the user model.

The third task is different in kind from the first two, and that difference matters. The overnight passes are silent and their output is data. The morning task produces a **conversation the user can answer**, and that makes it the densest source of explicit signal in the whole system: Claude is asking about precisely the residue that needed a human, and the replies are decisions. "Push that to next week." "Drop it, that's dead." "Why do you keep asking me about this?"

So the morning conversation is bidirectional and must write back as it goes — check-in dates moved, Things closed, preferences recorded mid-conversation per section 5. A morning chat that only reports is a notification with extra steps.

It also carries two jobs from the user model: disclosing notable preferences the learning pass derived overnight, and putting conflicting preferences to the user for a ruling. Both are one line each, in a conversation already happening, and both are why the system needs no review queue anywhere.

It also becomes the primary delivery channel for the briefing, which demotes ntfy to what it's actually good at: time-sensitive things that can't wait for tomorrow morning.

The scheduling mechanism is claude.ai itself — a scheduled task is an ordinary Claude session on the same MCP connection, with the same access as an interactive one. There is no service account, no second set of credentials, and no separate write limits. The only thing distinguishing a scheduled session from an interactive one is the actor recorded in the journal, which is what lets the learning pass tell "the user did this" from "Claude did this."

That leaves reliability as the one thing to verify before building on it: whether claude.ai scheduled tasks genuinely run unattended, or whether a headless Claude Code routine is needed instead, following the pattern already working for overnight development work. A PA that silently stops running is worse than no PA, so whichever it is needs to fail loudly.

### 4.4 The read view

A web frontend for looking at the graph and moving around it. React/TypeScript, served by the same container.

It reads and does not write. No chat panel, no create or edit affordances, no action buttons. Everything that changes state goes through Claude via MCP, which keeps a single write path and means the journal has one story to tell about who did what.

What it is for is the original spec's section 2.5 — visual verification for trust. Chat can tell you what Claude did; it cannot show you the shape of what you have. Three views cover that:

- **Tree.** Hierarchy via `ChildOf`, expandable, showing title and key tags.
- **Thing detail.** Everything on one Thing — notes, tags, urls, check-in date, and its relationships as navigable links. Where "how did this get here" gets answered, so this view also surfaces the Thing's journal history.
- **The user model.** Every preference, its scope, and the evidence behind it. This is the view that makes preferences correctable rather than mysterious — you can follow a preference back to the four moments that produced it.

Rejecting a preference is the one exception to read-only, and it should be the only button in the app.

The frontend consumes a small set of read-only HTTP endpoints, not MCP. Mirroring the query layer is enough; it does not need its own API surface.

## 5. The user model

This is the part that makes Reli more than a queryable notebook. A Things database with no model of its owner is a markdown vault with a nicer API.

**Structure.** A single `#User` Thing acts as an anchor. Each preference is its own Thing related to it — not a field inside it. A preference needs its own evidence links, its own tags and its own history, and one blob would make them unqueryable and force a full rewrite on every update.

**Evidence over confidence.** A preference carries `EvidenceFor` relationships to the specific Things and journal entries that produced it. Strength is a count you can read, not a float you maintain. "Prefers deep work 9–11am" shows its four occasions; if three are from March and the job changed in June, that is visible on inspection rather than something a decay function has to guess at.

**Scope.** Preferences declare what they apply to — which hat, which tags, which domain. Six months in there will be many, and loading all of them into every session is both expensive and useless. Daily planning should pull scheduling preferences and not naming conventions.

**Two sources.**

- *Explicit*, mid-conversation. Claude writes a preference the moment it notices one, not in an end-of-session summary — a closed tab is a lost signal. The convention is encoded in the MCP prompts.
- *Implicit*, from the journal. The learning pass. This is the "without being told" requirement, and it cannot come from conversation at all, because a scheduled job cannot read claude.ai sessions. It can only come from observed behaviour.

**No approval queue.** A preference the learning pass derives goes live immediately. It is not held provisional, and the user is not asked to confirm it. This is the behaviour of a PA who notices you never take meetings before ten and simply stops booking them — the noticing is the job, and routing every observation back for sign-off would turn "self-learning" into a chore and defeat the point. Correctness is handled after the fact, by correction, not before it, by permission.

The morning conversation mentions notable new preferences as it goes, one line, in a conversation already happening. That is disclosure, not approval.

**Conflicts go to the morning conversation.** Two preferences that genuinely contradict — "prefers working alone" against "always invites Tom to brainstorms" — are not resolved by the system picking a winner or by a merge rule. Both are held, and the conflict is raised with the user in the daily chat, which is exactly the kind of residue that conversation exists to clear. The answer is usually context rather than a contradiction, and that context becomes the scope on one or both.

**Correctability.** The user can see any preference and the evidence behind it, and can reject it. Rejection is itself journalled, and a rejected preference is not re-derived.

## 6. Check-ins

`checkin_date` is Claude's obligation, not the user's to-do date.

It means: *by this date, establish whether this is still true.* Whether that requires the user depends entirely on what Claude finds. Most check-ins should die quietly — resolved against Calendar, Gmail, or another Thing's state.

Consequently, Calendar and Gmail are not enrichment features to be added once the core works. They are the substrate that lets check-ins resolve without the user, which is the entire difference between a PA and a task list. They arrive early.

Deadlines, where they matter, live in `notes` as context. The check-in date is about attention, not obligation to the outside world.

## 7. Non-goals

Explicitly not being built, and not to be added without revisiting this document:

- A chat panel, or any write path through the frontend. claude.ai is where things happen; the web view is for looking.
- Any LLM call originating inside the Reli service.
- Multi-user, authentication beyond single-user access control, sharing, or public availability.
- A findings table, confidence decay algorithms, or any derived-state store that doesn't link to its evidence.
- Vector search. For one user's Things, `checkin_date`, tags and Postgres full-text are sufficient, and dropping ChromaDB removes a stateful component from the deployment.
- Concerns as modular domain monitors. The idea is sound and may return, but it is a layer on top of a working core, not part of it.
- Delivery channels beyond the morning conversation and ntfy. Telegram, email digests and voice are all deferred.
- Personality adaptation — Reli learning how to talk. Claude's own tone handling covers this.

## 8. Deployment

Unchanged, and reused wholesale: Docker, Railway (staging and production), Cloudflare Tunnel, GitHub Actions CI, `scripts/gates.sh` for test, lint and typecheck gates. The database becomes Postgres. The frontend is rebuilt as a read-only view against the new schema — the existing React app assumed a chat-first application and a data model that no longer exists.

## 9. What done looks like

Not feature completion — behaviour:

- A week passes in which Claude closes several loops the user never hears about.
- The morning briefing is short, and everything on it genuinely needs a person.
- A new claude.ai session already knows how the user works, without being told.
- The user reads a preference they never stated, and it's right.
- Nothing in the graph can be pointed at and asked "where did this come from?" without an answer.
