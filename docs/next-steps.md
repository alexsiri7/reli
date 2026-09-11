# Next Steps

A snapshot of where the v4 rebuild stands. The live source is the
[GitHub issues list](https://github.com/alexsiri7/reli/issues); this file is not a roadmap.

## Shipped

The rebuild chain that replaced the previous system, in order:

- **Data layer** (#1408) — `things`, `relationships`, `journal` on Postgres; hierarchy as
  `ChildOf`; an append-only journal from the first migration.
- **MCP tools** (#1409) — the writes, the reads and the standing questions at `/mcp`, every write
  with a required actor and no hard delete.
- **User model** (#1410) — the `#User` anchor and evidence-linked preference Things; strength is
  a count, there is no confidence value.
- **Prompts** (#1411) — `capture`, `daily-planning`, `project-planning`, `review`, each carrying
  the preference-capture convention and naming the scope it loads.
- **Google readers** (#1412) — read-only Gmail and Calendar lookups that return evidence for
  settling a check-in.
- **Read-only web view** (#1414) — tree, Thing detail with history, and the user model, with
  rejecting a preference as the only button.
- **The scheduled passes** (#1413) — the resolution pass, the learning pass and the morning
  conversation as prompt files under `prompts/scheduled/`, with `journal_since` as their one new
  tool, a `#ScheduledTask` heartbeat per task and a daily watchdog that files an issue when a run
  is missed.

The result is described in [ARCHITECTURE.md](ARCHITECTURE.md).

## Open

- **`#NeedsInput` as a first-class query** (#1442) — vision §4.1 lists it among the questions the
  service answers; today it is reachable only through `find_things` by tag.

What is deliberately not next is in [vision.md §7](vision.md#7-non-goals).
