# Next Steps

Immediate priorities and the path forward.

## Current state

The core pipeline works: context agent, reasoning agent, validator, response agent. Things are created, updated, linked. Google Calendar and Gmail integrations exist. The preference learning system is partially landed (personality schema, response agent loading, sweep aggregation are merged; reasoning agent signal detection is in progress).

The system is currently stabilizing — bugs in both Reli and the development tooling need resolution before pushing further on features.

## Immediate priorities

### 1. Stabilize the core

Before adding new capabilities, the existing system needs to be reliable:
- Fix outstanding bugs in the pipeline
- Ensure Things operations (create, update, link, delete) are consistently correct
- Verify the sweep runs reliably

### 2. Complete preference learning (#191, #193)

The foundation for everything else. Remaining work:
- Finish reasoning agent signal detection (explicit, implicit, positive, negative, behavioral signals)
- Wire signals to preference Thing creation/updates
- Validate that preferences actually improve responses over time

### 3. Rolling conversation context (#188)

One conversation per user, running indefinitely. Three-layer memory:
- Long-term: Things DB
- Short-term: rolling summary (compressed every N messages)
- Task context: per-request retrieval

### 4. Structured Thing references (#187)

Response agent outputs which Things it mentions as structured JSON, not string concatenation. Clean content, structured metadata, frontend inline linking.

### 5. Context agent as reasoning sub-agent (#165)

Move from rigid pipeline to on-demand context retrieval:
- Warm start with last 3 messages + their context
- Reasoning agent calls context search when it needs more
- ~80% of turns are follow-ups that don't need fresh retrieval

## Near-term roadmap

### Proactive learning (#192)

The reasoning agent generates a `priority_question` every turn — the single most valuable question to ask right now. The response agent decides whether to actually ask it based on conversation flow. The sweep detects gaps in Things and attaches open questions.

### Concerns (new)

Modular domain intelligence. Each concern (health, finance, travel) brings knowledge about what to care about and what questions to ask. Lifecycle: initialize (scan sources, build understanding, surface questions) → watch (react to relevant new inputs). See [vision](vision.md#concerns).

### MCP server (#190)

Expose Reli's intelligence to any MCP-compatible client:
- CRUD + search tools for Things
- PA behavior prompts (how to act on the user's behalf)
- Retrieval of preferences and the user model
- Briefing/sweep results

### Prompt evals (#160)

Golden datasets + ADK eval + Phoenix observability. Gate PRs on eval score thresholds. This is infrastructure for confident iteration on the prompts that drive Reli's intelligence.

## Future possibilities

- **Telegram bot** for proactive delivery (morning briefings, nudges, quick interactions)
- **Supabase migration** (#189) for multi-user support with RLS
- **OpenClaw integration** for broad multi-channel delivery (see [comparisons](comparisons.md#openclaw))
- **Mutations journal** for audit and rollback of knowledge graph changes
- **Additional ingestion sources** beyond calendar and email
