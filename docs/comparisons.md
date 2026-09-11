# Comparisons

How Reli relates to other projects in the personal AI space.

## OB1 (Open Brain)

[OB1](https://github.com/NateBJones-Projects/OB1) is a shared memory layer for AI tools — Postgres + pgvector, accessible via MCP. Its tagline: "One database, one AI gateway, one chat channel."

**Overlap:** Both want to be the persistent memory that follows you across AI clients, both use MCP as the integration protocol, both are self-hosted, both put no model inside the service.

**Where they differ:**

| | OB1 | Reli |
|---|---|---|
| Storage | Flat "thoughts" + vector search | Typed Things with five relationship types; hierarchy is a `ChildOf` edge |
| Reasoning | None — the calling agent figures it out | None in Reli either — Claude reasons over MCP. The difference is the PA prompts Reli serves: capture, daily planning, project planning, review |
| Learning | None — it's a database | Preferences as evidence-linked Things, explicit from conversation and implicit from the journal; strength is a count of evidence, there is no confidence score |
| Proactive | None | `checkin_date` as Claude's obligation to verify, answered by indexed queries (`due_for_checkin`, `stale`, `blocked`) and discharged by scheduled Claude sessions (not yet shipped) |
| Domain intelligence | None | None — Concerns are a stated non-goal |
| Ingestion | Slack messages | MCP, plus read-only Gmail and Calendar lookups that return evidence for settling a check-in |

**The key difference:** OB1 solves "my AI tools don't share memory." Reli solves "any Claude session starts already knowing how I operate and what needs checking." OB1 is what you'd build if you only wanted the storage layer.

**Could Reli use OB1 as storage?** In theory, but you'd lose what makes Reli more than a notebook: typed relationships to query over structure (`children`, `blocked`, `get_related`), `checkin_date` as an indexed obligation rather than a note, evidence edges that let a preference be audited and rejected, and an append-only journal that attributes every change to the user, an interactive Claude session or a scheduled one. The graph earns its keep.

## OpenClaw

[OpenClaw](https://github.com/openclaw/openclaw) is a self-hosted AI assistant framework focused on multi-channel delivery — 23+ messaging platforms (WhatsApp, Telegram, Slack, Discord, Signal, iMessage, Teams, etc.) with device pairing, voice integration, and a skills platform.

**Overlap:** Both want to be a personal AI assistant. Both are self-hosted.

**Complementary strengths:**

| | OpenClaw | Reli |
|---|---|---|
| Focus | Delivery and routing | Memory and obligations |
| Channels | 23+ messaging platforms | claude.ai (interactive and scheduled), ntfy for what cannot wait; a read-only web view |
| Memory | Conversation history with pruning/compaction | Structured knowledge graph with a journal of every mutation |
| User model | None | Preferences with the evidence behind each, correctable by rejection |
| Proactive | None | Check-ins as indexed queries, discharged by scheduled Claude sessions (not yet shipped) |
| Device integration | macOS/iOS/Android nodes | None |

**OpenClaw is a routing and delivery layer.** It's excellent at getting messages to/from you across platforms and executing tools. But it doesn't have a structured model of *you* — no knowledge graph, no evidence-linked preferences, no record of what needs verifying and when.

**Reli is the opposite** — strong on the model of the user, and delivery channels beyond the morning conversation and ntfy are a deliberate non-goal.

**Potential integration:** Reli's MCP server could be consumed by OpenClaw as a skill/tool, giving Reli's graph access to 23+ delivery channels without building each integration from scratch. The security model would need careful evaluation — OpenClaw's broad agent capabilities and multi-channel surface area create a larger attack surface for context poisoning and unintended actions, and every OpenClaw write would arrive in Reli's journal under one of the two Claude actors. But architecturally, it's a natural fit: Reli provides the memory, OpenClaw provides the delivery.
