# User Model

## Purpose

Reli holds a model of its one user so that any session starts already knowing how they work. Every preference is traceable to the moments that produced it: strength is evidence you can count and inspect, never a confidence number, and correction happens after the fact by rejection rather than before it by approval.

## Requirements

### Requirement: Preferences are evidence-linked Things

The model SHALL be anchored on a single Thing tagged "#User". Each preference SHALL be its own Thing tagged "#Preference", linked from the anchor, carrying a scope and supported by at least one EvidenceFor edge from another Thing. Recording a preference without evidence or without a scope SHALL be refused, and a Thing shaped like a preference but lacking either SHALL NOT be returned as part of the model.

#### Scenario: Recording with evidence
- GIVEN three Things where the owner rewrote a generated title shorter
- WHEN a preference "Prefers short titles" is recorded under scope "capture" citing all three
- THEN the preference is stored with three pieces of evidence

#### Scenario: No evidence
- GIVEN any session
- WHEN a preference is recorded with no evidence
- THEN the request is refused

### Requirement: Strength is a count, not a score

A preference's strength SHALL be the number of distinct Things supporting it. No confidence value, decay or score SHALL exist anywhere in the model. Adding the same evidence twice SHALL change nothing.

#### Scenario: Reinforcing twice with the same moment
- GIVEN a preference with two pieces of evidence
- WHEN one new evidence Thing is added to it twice
- THEN its strength is three

### Requirement: Journal entries become evidence through observations

A journal entry SHALL be citable as evidence only through a Thing tagged "#Observation" holding that entry's id in its notes, because an edge can only point at a Thing.

#### Scenario: Citing a pushed check-in
- GIVEN journal entry 812 where the owner moved a check-in from Monday to Tuesday
- WHEN it is to support a preference
- THEN an "#Observation" Thing holding journal_entry_id "812" is created and cited

### Requirement: Preferences are scoped

Every preference SHALL declare a scope, and the model SHALL be readable for one scope at a time, matched exactly apart from case. The scope vocabulary SHALL be "capture", "scheduling", "planning", "review" and "voice". The model SHALL also be available as a loadable resource, whole or per scope, without a tool call.

#### Scenario: Daily planning loads only what it needs
- GIVEN preferences under "scheduling" and "capture"
- WHEN the model is read for scope "scheduling"
- THEN only the scheduling preferences are returned, each with its evidence and count

### Requirement: Voice is a scope like any other

How the assistant sounds SHALL be recorded as preferences under the "voice" scope, with evidence, and SHALL be loaded beside the scope of whatever mode a session is in. A voice preference SHALL override the default voice. Voice preferences SHALL be learned only from what the owner says in conversation, never derived from the journal.

#### Scenario: Owner asks for less cheer about money
- GIVEN the owner says "stop being so chirpy about my tax return"
- WHEN the session records it
- THEN a "voice" preference exists citing that conversation's Thing
- AND later sessions load it and sound accordingly

### Requirement: Preferences go live and are correctable

A recorded preference SHALL take effect immediately with no approval step. The owner SHALL be able to reject any preference; a rejection SHALL tag it "#Rejected", be journalled, leave it and its evidence readable, and change nothing when repeated. Rejected preferences SHALL be left out of the model by default, SHALL be readable on request, and SHALL NOT be derived again.

#### Scenario: Rejected preference is not re-derived
- GIVEN the owner rejected "Avoids meetings on Fridays"
- WHEN a later pass finds the same pattern
- THEN it does not record the preference again

### Requirement: Conflicts are kept, not resolved

Two live preferences that cannot both be followed SHALL both be kept, and the conflict SHALL be put to the owner in the morning conversation for a ruling rather than settled by any rule.

#### Scenario: Contradicting preferences
- GIVEN "Prefers working alone" and "Always invites Tom to brainstorms"
- WHEN the learning pass notices they conflict
- THEN both stay live and the pair is listed under the briefing's conflicts
