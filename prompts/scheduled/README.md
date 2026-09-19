# Scheduled passes

The proactive half of the PA (#1413). Nothing here runs inside Reli: each file is the instructions
for one claude.ai scheduled task with Reli's MCP connector attached — the same `/mcp` an
interactive session uses, through the same Google sign-in. The task itself holds none of this
text. Its prompt is one line asking Reli for it, and the `get_scheduled_instructions` tool serves
the file as the repository holds it (#1506), so editing a file here changes what the next run does
and there is no pasted copy to drift.

## Setting up the tasks

Each claude.ai scheduled task's prompt is the one line below, verbatim:

- Resolution pass:

  > Call get_scheduled_instructions with pass_name "resolution" and follow the result exactly. If the call fails or Reli cannot be reached, stop: do nothing else this run.

- Learning pass:

  > Call get_scheduled_instructions with pass_name "learning" and follow the result exactly. If the call fails or Reli cannot be reached, stop: do nothing else this run.

- Morning conversation:

  > Call get_scheduled_instructions with pass_name "morning" and follow the result exactly. If the call fails or Reli cannot be reached, say plainly that you could not reach Reli this morning, and nothing else.

The line carries the failure behaviour because it is the only thing that survives the failure: a
pass that could not fetch its instructions has nothing to improvise from, and an empty or cheerful
morning message when the service is down is the worst available outcome. Asking for a pass that
does not exist returns the three valid names rather than an error.

**Connectors.** The Reli connector is required on all three tasks. The resolution pass also needs
the user's **Calendar and Gmail connectors attached alongside Reli's** (#1487): a check-in on a
booked flight is settled by the session reading the confirmation itself, not by Reli. That
attachment is a human setup step, and a resolution pass that finds the connectors missing records
that in the briefing rather than resolving nothing. The morning conversation carries the same two:
it reads today's calendar through the Calendar connector before presenting the briefing. The
learning pass reads only the journal and the graph, so it needs neither.

## The three passes

In this order, each depending on what the one before it wrote:

1. `resolution-pass.md` — overnight. Walks `due_for_checkin`, settles what it can from the
   session's own Calendar and Gmail and from the graph, and writes the day's `#Briefing` Thing
   holding only what it could not settle. Every write is `claude_scheduled`.
2. `learning-pass.md` — overnight, at least half an hour later. Reads the journal since its last
   run with `journal_since`, filtered to `user` and `claude_interactive` so Claude's own unattended
   edits never count as user behaviour, and records what it finds as evidence-linked preferences.
   Appends `learned` and `conflicts` to the briefing. Every write is `claude_scheduled`.
3. `morning-conversation.md` — waking hours. Reads the briefing, presents it shaped by the
   `scheduling` and `voice` preferences, archives it, asks a short question or two about a few of
   the `#New` captures nobody has talked through yet (#1518), and writes every reply back as it
   goes. Its own bookkeeping is `claude_scheduled`; every write that encodes something the user
   said is `claude_interactive`.

## What they leave in the graph

- One active Thing per task tagged `#ScheduledTask`, titled `Resolution pass`, `Learning pass` and
  `Morning conversation`. Each run ends by setting its `checkin_date` to tomorrow and `last_run`
  in its notes (the learning pass also keeps `journal_watermark`, the newest journal id it has
  processed). A run that did not complete leaves the Thing due, so a missed run shows up to every
  pass that reads `find_things(tags=["#ScheduledTask"])` and in the web view's tree. It never
  appears in `due_for_checkin`, which leaves Reli's own records out (#1516). Never archive one — an
  archived Thing leaves both, so archiving a heartbeat hides a missed run instead of reporting it.
- One `#Briefing` Thing per morning, titled `Briefing for YYYY-MM-DD` with that date as its
  `checkin_date`, with `unresolved`, `decisions`, `learned` and `conflicts` in its notes and a
  `References` edge to every Thing it mentions. The morning conversation archives it once it has
  been presented.
- `#Observation` Things standing for the journal entries a preference cites, and the `#Preference`
  Things themselves, exactly as an interactive session records them.
- On the captures the morning conversation filled in: a description, notes, a check-in date the
  user gave in place of the default, a `ChildOf` edge from the project they named, and no `#New`
  tag. A capture the user skipped keeps its `#New` and comes back another morning.

How the tasks are scheduled, how a missed run is noticed and what to do when one is: see the
"Scheduled passes" section of the repository's `CLAUDE.md`.
