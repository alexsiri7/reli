# Comparisons

How Reli relates to other projects in the personal AI space.

## OB1 (Open Brain)

[OB1](https://github.com/NateBJones-Projects/OB1) is a shared memory layer for AI tools — Postgres + pgvector, accessible via MCP. Its tagline: "One database, one AI gateway, one chat channel."

**Overlap:** Both want to be the persistent memory that follows you across AI clients, both use MCP as the integration protocol, both are self-hosted.

**Where Reli goes further:**

| | OB1 | Reli |
|---|---|---|
| Storage | Flat "thoughts" + vector search | Typed Things with relationships (graph) |
| Reasoning | None — the calling agent figures it out | Reasoning pipeline + PA prompts via MCP |
| Learning | None — it's a database | Preference extraction, confidence tracking, pattern detection |
| Proactive | None | Sweep, briefings, gap detection |
| Domain intelligence | None | Concerns (health, finance, travel...) |
| Ingestion | Slack messages | Conversation + calendar + email |

**The key difference:** OB1 solves "my AI tools don't share memory." Reli solves "I want an AI that knows me and acts on my behalf." OB1 is what you'd build if you only wanted the storage layer.

**Could Reli use OB1 as storage?** In theory, but you'd lose the graph structure that makes Reli's intelligence work — typed relationships, preference schemas with confidence tracking, Thing-level metadata for concerns, and the sweep's ability to query over structure ("find all appointments not updated in 6 months"). The graph earns its keep.

## OpenClaw

[OpenClaw](https://github.com/openclaw/openclaw) is a self-hosted AI assistant framework focused on multi-channel delivery — 23+ messaging platforms (WhatsApp, Telegram, Slack, Discord, Signal, iMessage, Teams, etc.) with device pairing, voice integration, and a skills platform.

**Overlap:** Both want to be a personal AI assistant. Both are self-hosted.

**Complementary strengths:**

| | OpenClaw | Reli |
|---|---|---|
| Focus | Delivery and routing | Intelligence and knowledge |
| Channels | 23+ messaging platforms | Web UI (expanding) |
| Memory | Conversation history with pruning/compaction | Structured knowledge graph |
| User model | None | Preferences, patterns, concerns |
| Proactive | None | Sweep, briefings, gap detection |
| Device integration | macOS/iOS/Android nodes | None |

**OpenClaw is a routing and delivery layer.** It's excellent at getting messages to/from you across platforms and executing tools. But it doesn't have a structured model of *you* — no knowledge graph, no preference learning, no proactive intelligence.

**Reli is the opposite** — strong on user modeling, weak on delivery. Reli has the knowledge graph, the preference system, the learning flywheel, and the sweep... but currently only delivers through a web chat UI.

**Potential integration:** Reli's MCP server could be consumed by OpenClaw as a skill/tool, giving Reli's intelligence access to 23+ delivery channels without building each integration from scratch. The security model would need careful evaluation — OpenClaw's broad agent capabilities and multi-channel surface area create a larger attack surface for context poisoning and unintended actions. But architecturally, it's a natural fit: Reli provides the thinking, OpenClaw provides the delivery.
