# Scheduled passes

The proactive half of the PA (#1413). Nothing here runs inside Reli: each file is the text of a
saved prompt for a Claude scheduled task with Reli's MCP connector attached — the same `/mcp` and
the same bearer token an interactive session uses. The files are plain prose with no placeholders,
so each is pasted into its task as-is.

Three tasks, in this order, each depending on what the one before it wrote:

1. `resolution-pass.md` — overnight. Walks `due_for_checkin`, settles what it can from Calendar,
   Gmail and the graph, and writes the day's `#Briefing` Thing holding only what it could not
   settle. Every write is `claude_scheduled`.
2. `learning-pass.md` — overnight, at least half an hour later. Reads the journal since its last
   run with `journal_since`, filtered to `user` and `claude_interactive` so Claude's own unattended
   edits never count as user behaviour, and records what it finds as evidence-linked preferences.
   Appends `learned` and `conflicts` to the briefing. Every write is `claude_scheduled`.
3. `morning-conversation.md` — waking hours. Reads the briefing, presents it shaped by the
   `scheduling` preferences, archives it, and writes every reply back as it goes. Its own
   bookkeeping is `claude_scheduled`; every write that encodes something the user said is
   `claude_interactive`.

## What they leave in the graph

- One active Thing per task tagged `#ScheduledTask`, titled `Resolution pass`, `Learning pass` and
  `Morning conversation`. Each run ends by setting its `checkin_date` to tomorrow and `last_run`
  in its notes (the learning pass also keeps `journal_watermark`, the newest journal id it has
  processed). A run that did not complete leaves the Thing due, so a missed run shows up in
  `due_for_checkin` for every session and in the web view's tree. Never archive one and never make
  it a child of anything — the watchdog reads the tree's top level.
- One `#Briefing` Thing per morning, titled `Briefing for YYYY-MM-DD` with that date as its
  `checkin_date`, with `unresolved`, `decisions`, `learned` and `conflicts` in its notes and a
  `References` edge to every Thing it mentions. The morning conversation archives it once it has
  been presented.
- `#Observation` Things standing for the journal entries a preference cites, and the `#Preference`
  Things themselves, exactly as an interactive session records them.

How the tasks are scheduled, how a missed run is noticed and what to do when one is: see the
"Scheduled passes" section of the repository's `CLAUDE.md`.
