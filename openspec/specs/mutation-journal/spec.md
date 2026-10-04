# Mutation Journal

## Purpose

The journal is the record of every change to the graph and who made it. It answers "where did this come from?" for any Thing, and it is the only source of implicit learning about the owner, so a gap in it can never be recovered.

## Requirements

### Requirement: Every mutation is journalled

Every create, update, relate and unrelate SHALL write exactly one journal entry in the same transaction as the change. Each entry SHALL record when it happened, the actor, the operation, the entity type and id, and the state before and after. No path SHALL change a Thing or an edge without a journal entry.

#### Scenario: Updating a Thing
- GIVEN a Thing with check-in date Monday
- WHEN it is updated to Wednesday
- THEN one journal entry records the update with both dates in its before and after state

### Requirement: The journal is append-only

Journal entries SHALL NOT be updated or deleted by any path, including by the database itself rejecting such a change.

#### Scenario: Attempted rewrite
- GIVEN an existing journal entry
- WHEN anything attempts to update or delete it
- THEN the attempt fails and the entry is unchanged

### Requirement: Every write names an honest actor

Every write SHALL name one of three actors: "user" for the owner acting directly in the web view, "claude_interactive" for a session with a person in it, and "claude_scheduled" for an unattended scheduled session. A write over MCP SHALL require the actor with no default, and SHALL NOT be able to claim "user".

#### Scenario: Missing actor
- GIVEN an MCP session
- WHEN it calls a writing tool without an actor
- THEN the call fails validation and nothing is written

#### Scenario: MCP cannot impersonate the owner
- GIVEN an MCP session relaying the owner's rejection of a preference
- WHEN it performs the rejection
- THEN the journal attributes it to the Claude session, not to "user"

### Requirement: A Thing's history is readable

The system SHALL return a Thing's journal entries, oldest first within a window cut from the newest end, with the total number of entries and whether older ones were left out.

#### Scenario: Long history
- GIVEN a Thing with 300 journal entries
- WHEN its history is read with a limit of 200
- THEN the newest 200 are returned oldest first
- AND the total is 300 and the answer is marked truncated

### Requirement: The journal is readable across the graph by actor

The system SHALL return journal entries after a given id across every entity, oldest first, optionally restricted to a set of actors, with a total and a truncated flag so a caller can page forward by the last id it saw.

#### Scenario: Learning from the owner only
- GIVEN journal entries by all three actors since id 500
- WHEN the journal is read after 500 for "user" and "claude_interactive"
- THEN no "claude_scheduled" entry is returned
