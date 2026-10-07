# Scheduled Passes

## Purpose

The proactive half of the PA is three claude.ai scheduled sessions with Reli attached, not anything running inside Reli. Overnight they settle what they can without the owner and learn from the journal; in the morning a conversation presents only the residue that needs a person and writes the owner's answers straight back. Silence is the goal: a loop closed without telling the owner is the best outcome.

## Requirements

### Requirement: Passes fetch their instructions from Reli

A tool SHALL return the full instructions for a named pass — "resolution", "learning" or "morning" — as the repository holds them, including the default voice and the shared conventions, ready to follow with no further setup. Any other name SHALL return a sentence naming the three valid passes. A scheduled task SHALL hold only a one-line prompt asking for its pass, so a change to a pass in the repository changes the next run with no one re-pasting anything. The one-line prompt SHALL tell the pass to stop if the instructions cannot be fetched, and the morning conversation SHALL instead say plainly that it could not reach Reli.

#### Scenario: Unknown pass name
- GIVEN an unattended session
- WHEN it asks for the instructions of pass "nightly"
- THEN it receives the names "resolution", "learning" and "morning"

#### Scenario: Reli unreachable in the morning
- GIVEN the morning task cannot reach Reli
- WHEN it runs
- THEN it tells the owner it could not reach Reli this morning and does nothing else

### Requirement: Outside data comes from the session's own connectors

The resolution pass and the morning conversation SHALL read Calendar and Gmail through the connectors attached to the Claude session running them, read-only, never sending mail or changing an event. The instructions SHALL name the connectors each pass expects. A resolution pass that finds them missing SHALL record that first in the briefing's decisions rather than write a briefing as though there were nothing to settle.

#### Scenario: Connectors not attached
- GIVEN the resolution task was set up without the Gmail connector
- WHEN it runs
- THEN the briefing's first decision says the connectors are missing

### Requirement: The resolution pass settles check-ins silently

Overnight, the resolution pass SHALL walk what is due for check-in and, for each, look narrowly at the session's Calendar and Gmail and at related Things, then either archive it, re-date it with the reason in its notes, tag it "#NeedsInput" and list it as unresolved without moving its date, or list it as a decision. A settled check-in SHALL NOT appear in the briefing. An unpresented briefing from the previous day SHALL be archived and its unresolved items carried forward.

#### Scenario: Flights confirmed
- GIVEN a check-in "Book flights for Lisbon" is due
- WHEN the pass finds the booking confirmation in Gmail
- THEN the Thing is archived with the reasoning journalled
- AND the owner never hears about it

### Requirement: Captures are enriched, not resolved, overnight

For a due Thing tagged "#New", the resolution pass SHALL write nothing to the Thing. It SHALL briefly look for related Calendar or Gmail items and, when something turns up, add a bullet to the briefing's unresolved list saying what was found and what was not, so the morning question can build on it.

#### Scenario: A bare title with a matching order
- GIVEN a "#New" Thing titled "Fridge"
- WHEN the pass finds an order confirmation dated the 12th
- THEN the briefing mentions the order against "Fridge"
- AND the Thing keeps its "#New" tag, date and notes unchanged

### Requirement: The resolution pass captures new obligations from the inbox

Once a night, after walking the due list, the resolution pass SHALL look through the session's Gmail for mail received since its previous run, using its heartbeat's last run time as the window and the last day when there is none. For each message that implies something the owner must do, decide, attend or reply to, and that no active Thing already covers, it SHALL create one Thing as "claude_scheduled", tagged "#New" and "#FromInbox", with the default check-in date. The Thing SHALL be about the topic, not the message: a title naming the obligation in the owner's terms, and at most a one-line description of what is needed, who it involves and any outside deadline. Message bodies, quoted text, addresses and attachments SHALL NOT be copied into the graph. Newsletters, promotions, automated notifications, receipts with nothing left to do, and mail the owner has already answered SHALL be skipped. A message that bears on an existing active Thing SHALL NOT create a new one; if that Thing is due, the message is evidence for its check-in as usual. Several messages about one topic SHALL become one Thing. When nothing qualifies, nothing SHALL be created and nothing SHALL be said. An obligation that cannot wait for the morning SHALL also go first under the briefing's decisions, saying why.

#### Scenario: An invite that needs the owner
- GIVEN mail arrived yesterday asking the owner to bring his passport to a right-to-work check on Wednesday at 11:00
- AND no active Thing covers it
- WHEN the resolution pass runs
- THEN one Thing titled along the lines of "Bring passport to the right-to-work check (Wed 11:00)" exists, tagged "#New" and "#FromInbox"
- AND none of the message's text is stored in it

#### Scenario: Only newsletters and receipts
- GIVEN the inbox since the last run holds a newsletter, a delivery notification and a paid receipt
- WHEN the resolution pass runs
- THEN no Thing is created
- AND the briefing says nothing about the inbox

#### Scenario: Mail about something already tracked
- GIVEN an active Thing "Take the cat to the vet"
- WHEN a Medivet appointment reminder arrives
- THEN no new Thing is created

### Requirement: One briefing per morning

The overnight passes SHALL leave one Thing tagged "#Briefing" per morning, titled "Briefing for YYYY-MM-DD" and dated that day, with notes "unresolved", "decisions", "learned" and "conflicts", and a References edge to every Thing it mentions. A quiet night SHALL still write a briefing with empty lists.

#### Scenario: Quiet night
- GIVEN nothing due could not be settled
- WHEN the resolution pass finishes
- THEN a briefing for the morning exists with empty unresolved and decisions

### Requirement: The learning pass learns only from the owner

The learning pass SHALL read the journal after its stored watermark, restricted to "user" and "claude_interactive" entries, and SHALL record or reinforce preferences only for patterns with at least two supporting entries, each cited through an observation. It SHALL check rejected preferences first, SHALL never write under the "voice" scope, SHALL append what it learned and any conflicts to the briefing, and SHALL advance its watermark.

#### Scenario: Monday check-ins pushed
- GIVEN three journal entries by "claude_interactive" moving check-ins from Monday to Tuesday
- WHEN the learning pass runs
- THEN a "scheduling" preference cites three observations
- AND it appears under the briefing's learned list

### Requirement: The morning conversation presents the residue and writes back

In waking hours the morning conversation SHALL load the "scheduling" and "voice" preferences, read today's calendar through its own connector, present the briefing in order — decisions, unresolved, notable learned preferences as disclosure, conflicts as questions — and archive the briefing once presented. Every reply SHALL be written back in the same turn: dates moved, Things archived, preferences recorded or rejected, conflicts ruled on by scope.

#### Scenario: "Drop it, that's dead"
- GIVEN the owner answers a briefing item with "drop it"
- WHEN the conversation continues
- THEN that Thing is archived as "claude_interactive" in the same turn

### Requirement: The morning fills in bare captures

The morning conversation SHALL ask about three to five "#New" Things, newest first and always including the oldest, one or two questions each answerable in a word — by when, what does done look like, who is involved, which project. A Thing tagged "#FromInbox" SHALL be introduced as found in the inbox, so the owner can say it is not worth tracking; that answer archives it as "claude_interactive". Answers SHALL be written back immediately as description, notes, a real check-in date and a ChildOf edge from the named project, and "#New" SHALL be removed only once the Thing has been talked through. The rest SHALL wait without being mentioned.

#### Scenario: Owner skips one
- GIVEN four "#New" Things raised this morning
- WHEN the owner answers three and deflects one
- THEN three lose "#New" and gain their answers
- AND the deflected one keeps "#New" for another morning

#### Scenario: An inbox capture not worth tracking
- GIVEN a "#New" Thing tagged "#FromInbox" raised this morning
- WHEN the owner says it does not need tracking
- THEN it is archived as "claude_interactive" in the same turn

### Requirement: A missed run is noticed in-session

Each task SHALL own one never-archived Thing tagged "#ScheduledTask" and end every run by setting its check-in date to tomorrow. A heartbeat still due SHALL mean that run did not complete: the next resolution pass SHALL note it first in the briefing's decisions and the morning conversation SHALL say so in its first line. No external watcher SHALL be used to detect it.

#### Scenario: Learning pass did not run
- GIVEN the "Learning pass" heartbeat is dated yesterday
- WHEN the morning conversation starts
- THEN its first line tells the owner the learning pass did not complete last night

### Requirement: Scheduled writes are attributed honestly

The overnight passes SHALL write as "claude_scheduled". The morning conversation SHALL write its own bookkeeping as "claude_scheduled" and every write that encodes something the owner said as "claude_interactive".

#### Scenario: Archiving the briefing
- GIVEN the morning conversation has presented the briefing
- WHEN it archives it
- THEN the journal attributes the archive to "claude_scheduled"
