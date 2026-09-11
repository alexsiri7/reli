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

The result is described in [ARCHITECTURE.md](ARCHITECTURE.md).

## Open

- **The scheduled passes** (#1413) — the resolution pass, the learning pass and the morning
  conversation as Claude scheduled tasks on the same MCP connection, per
  [vision.md §4.3](vision.md#43-scheduled-claude--the-proactive-half). That section also names
  the question to settle first: whether claude.ai scheduled tasks genuinely run unattended, or a
  headless routine is needed — and either way, that a stopped PA must fail loudly.
- **`#NeedsInput` as a first-class query** (#1442) — vision §4.1 lists it among the questions the
  service answers; today it is reachable only through `find_things` by tag.

What is deliberately not next is in [vision.md §7](vision.md#7-non-goals).
