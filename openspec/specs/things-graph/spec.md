# Things Graph

## Purpose

Everything worth remembering about the owner's life is a Thing, and the meaning of a Thing lives in its tags and its typed relationships rather than in a type column. The graph is the memory a Claude session starts from, so it must be shaped for querying and must never lose anything.

## Requirements

### Requirement: A Thing is the universal entity

A Thing SHALL carry a title, an optional description, notes as a mapping of slug to markdown, tags, urls as a mapping of name to URL, an optional check-in date, a priority, an active flag and creation and update times. There SHALL be no type column and no user identifier; what a Thing is SHALL be expressed only through its tags and relationships.

#### Scenario: Capturing a person
- GIVEN a session that wants to remember a contact
- WHEN it creates a Thing titled "Tom" tagged "#Person"
- THEN the Thing is stored with that title and tag
- AND no type field is required or accepted

### Requirement: Relationships are typed and directed

Two Things SHALL be linked only by one of five relationship types: ChildOf, Blocks, RelatedTo, EvidenceFor and References. Each edge SHALL carry an optional sentence of context. Direction SHALL be read per type: for ChildOf the source is the parent and the target the child; for Blocks the source is the blocked Thing and the target its blocker; for EvidenceFor the source is the evidence and the target what it supports. A second EvidenceFor edge between the same pair SHALL be refused, naming the edge that already exists.

#### Scenario: Recording a blocker
- GIVEN Things "Book flights" and "Renew passport"
- WHEN a Blocks edge is created from "Book flights" to "Renew passport"
- THEN "Book flights" is the blocked Thing

#### Scenario: Duplicate evidence refused
- GIVEN an EvidenceFor edge from an observation to a preference
- WHEN the same edge is created again
- THEN the request is refused and names the existing edge

### Requirement: Hierarchy is a ChildOf relationship and nothing else

The graph SHALL express hierarchy only through ChildOf edges. There SHALL be no parent field on a Thing.

#### Scenario: Placing a task in a project
- GIVEN a project Thing and a task Thing
- WHEN a ChildOf edge is created from the project to the task
- THEN the task appears among the project's children

### Requirement: Nothing is hard-deleted

A Thing SHALL be retired by archiving, which sets it inactive and leaves it and its edges readable. There SHALL be no hard delete of a Thing reachable from outside the service. An edge MAY be removed; both Things it joined SHALL remain.

#### Scenario: Archiving a finished task
- GIVEN an active Thing with two edges
- WHEN it is archived
- THEN it drops out of every standing question and the default listing
- AND reading it by id still returns it with both edges

### Requirement: Updates replace, never merge

Updating a Thing SHALL replace each field given with the value given and leave every field not given untouched. Tags, notes and urls given SHALL replace the whole stored value.

#### Scenario: Adding a tag requires the union
- GIVEN a Thing tagged "#Travel" and "#New"
- WHEN it is updated with tags ["#NeedsInput"]
- THEN its tags are exactly ["#NeedsInput"]

### Requirement: A capture is dated and marked for discussion

A Thing created without a check-in date SHALL be given tomorrow's date in Europe/London; a date passed explicitly SHALL be kept. A newly created Thing SHALL be tagged "#New", meaning not yet talked through with the owner. Reli's own records — the "#User" anchor, preferences, observations, scheduled-task heartbeats and briefings — SHALL receive neither the default date nor the "#New" mark. After the one-off backfill, no active Thing of the owner's SHALL be without a check-in date.

#### Scenario: Bare capture on the go
- GIVEN it is Monday in Europe/London
- WHEN a Thing titled "Fridge" is created with no check-in date
- THEN its check-in date is Tuesday
- AND it is tagged "#New"

#### Scenario: Reli's own record
- GIVEN a session recording a preference
- WHEN the preference Thing is created
- THEN it has no default check-in date and no "#New" tag
