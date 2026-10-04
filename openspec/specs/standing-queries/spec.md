# Standing Queries

## Purpose

Proactivity in Reli is a query, not an inference. The questions a PA needs answered — what is due, what has gone quiet, what is stuck, what only the owner can settle — are deterministic, indexed reads over the graph, and the judgement about what the answers mean happens in Claude.

## Requirements

### Requirement: What is due for check-in

The system SHALL list active Things whose check-in date is on or before a given date (today by default), most important first. Reli's own records — the "#User" anchor, preferences, observations, scheduled-task heartbeats and briefings — SHALL never appear in this list, dated or not.

#### Scenario: Due today
- GIVEN an active Thing dated yesterday and one dated next week
- WHEN what is due today is asked for
- THEN only the Thing dated yesterday is listed

#### Scenario: Bookkeeping stays out
- GIVEN a "#Briefing" Thing dated today
- WHEN what is due today is asked for
- THEN the briefing is not listed

### Requirement: What has gone stale

The system SHALL list active Things not updated for at least a given number of days (30 by default), longest untouched first.

#### Scenario: Untouched for two months
- GIVEN an active Thing last updated 60 days ago
- WHEN stale Things are asked for with the default threshold
- THEN it is listed

### Requirement: What is blocked

The system SHALL list Things that are the source of a Blocks edge whose blocker is still active, most important first. When the blocker is archived the Thing SHALL drop out of the list.

#### Scenario: Blocker finished
- GIVEN "Book flights" blocked by "Renew passport"
- WHEN "Renew passport" is archived
- THEN "Book flights" is no longer listed as blocked

### Requirement: What needs the owner's input

The system SHALL list active Things tagged "#NeedsInput", most important first, bounded by a caller-given limit, with the total that matched and whether any were left out.

#### Scenario: More decisions than the limit
- GIVEN 150 active Things tagged "#NeedsInput"
- WHEN they are asked for with a limit of 100
- THEN 100 are returned, the total is 150 and the answer is marked truncated

### Requirement: Filtering, not searching

The system SHALL list Things matching every filter given — tags (any or all), active state (live, archived or both), a check-in date range and a priority range — highest priority first, bounded by a limit of at most 1000. Omitting the tag filter SHALL mean no tag filter. There SHALL be no free-text or semantic search.

#### Scenario: Today's briefing
- GIVEN briefings dated yesterday and today
- WHEN Things tagged "#Briefing" with check-in from today to today are asked for
- THEN only today's briefing is returned

### Requirement: Neighbourhood and children

The system SHALL return the Things reachable from a Thing within a given number of hops (at most five), following edges in both directions, nearest first, each with its hop count and the edge type that reached it, optionally restricted to relationship types. Cycles SHALL terminate and the origin SHALL never be returned. The system SHALL also return a Thing's direct ChildOf children, most important first. An unknown id SHALL return an empty list rather than an error.

#### Scenario: Two hops out
- GIVEN project P with child T, and T related to note N
- WHEN the neighbourhood of P is asked for at depth 2
- THEN T is returned at depth 1 and N at depth 2
