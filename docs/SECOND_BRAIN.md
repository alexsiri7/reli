# Reli: Second Brain Architecture

## Core Concept

Everything is a **Thing**. A Thing can be a project, a task, a person, an event,
a place, an idea, a note — anything worth remembering. Things exist in a graph,
connected to one another through relationships.

The brain is messy by nature. Users don't think in hierarchies — they think in
associations. "I'm going with Tom to the conference" creates three Things
(me, Tom, the conference) and two relationships (going-with, attending).

## Thing Surface Levels

Not all Things are equal in visibility. The UI needs to distinguish:

### Tracked Things (surface in sidebar)
Things the user actively cares about. They show up in the sidebar, have
check-in dates, can be snoozed. Examples:
- **Projects**: "Launch new website", "Q2 budget planning"
- **Goals**: "Run a marathon", "Learn Spanish"
- **Active tasks**: "Review PR #42", "Call the dentist"

### Entity Things (exist in the graph, don't surface by default)
Things that are real and referenced, but don't need active tracking. They
surface when relevant — when mentioned in conversation, when connected to
a tracked Thing. Examples:
- **People**: "Tom", "Sarah from marketing"
- **Places**: "The office in Austin", "Blue Bottle Coffee on 5th"
- **Events**: "React Conf 2026", "Mom's birthday dinner"
- **Concepts**: "The auth refactor approach", "That idea about caching"

The distinction isn't type-based — a person CAN be tracked ("Check in with
Tom weekly") and a project CAN be an entity (a past project referenced for
context). **The user decides what surfaces, not the system.**

## Relationships

Things connect to other Things. Relationships are typed and directional:

### Structural relationships
- **parent-of / child-of**: Project → Task, Goal → Milestone
- **depends-on / blocks**: Task A must finish before Task B
- **part-of**: "Chapter 3" is part of "The Book"

### Associative relationships
- **related-to**: Generic connection ("this reminds me of that")
- **involves**: "Conference trip" involves "Tom", "Hotel booking", "Talk prep"
- **tagged-with**: Lightweight grouping without hierarchy

### Temporal relationships
- **followed-by / preceded-by**: Sequential events
- **spawned-from**: "This task came from that meeting"

## How the AI Uses This

### Context Agent (Stage 1)
When searching for relevant Things, follow the graph:
- User mentions "Tom" → find Tom → find everything connected to Tom
- User asks about "the website project" → find project → find all children,
  dependencies, involved people, related notes

### Reasoning Agent (Stage 2)
When deciding what to create/update:
- "I'm going with Tom to React Conf" →
  - Find or create Tom (entity, type: person)
  - Find or create React Conf (entity, type: event)
  - Create relationship: user → attending → React Conf
  - Create relationship: Tom → attending → React Conf
  - Create relationship: user → going-with → Tom (for this event)
  - DON'T surface Tom or React Conf in sidebar unless user asks
- "Start a project to redesign the homepage" →
  - Create "Redesign homepage" (tracked, type: project)
  - Surface in sidebar
  - If user describes subtasks, create them as children

### Response Agent (Stage 4)
When responding, show awareness of the graph:
- "Got it, I've added the React Conf trip. Tom's coming too — want me to
  track any prep tasks for it?"
- "That's the third task under the website redesign — you're 2/5 done!"

## UI Implications

### Sidebar
- Show **tracked Things** grouped by type (Projects, Tasks, Goals)
- Projects show child count and completion progress
- Things with approaching check-in dates surface prominently
- Entity Things don't appear here unless explicitly tracked

### Thing Detail View
- Expand a Thing to see all its connections
- Show related entities, child tasks, dependencies
- Show a mini-graph of connections (nice-to-have)

### Chat Context
- When discussing a Thing, the AI has access to its full graph neighborhood
- "What's the status of the website project?" pulls the project + all
  children + their statuses + involved people

## Data Model Changes Needed

### Current: things table
```
id, title, type_hint, parent_id, checkin_date, priority, active, data
```

### Proposed additions:

**thing_relationships table:**
```
id, from_thing_id, to_thing_id, relationship_type, metadata, created_at
```
This replaces the flat parent_id with a proper graph. parent_id can stay
as a shortcut for the common parent-child case.

**New type_hints:**
- Current: task, note, idea, project, goal, journal
- Add: person, place, event, concept, reference

**New Thing fields:**
- `surface`: boolean — whether this Thing appears in the sidebar
- `last_referenced`: timestamp — when this was last mentioned in conversation
  (for relevance ranking of entity Things)

## Migration Path

1. Add `thing_relationships` table (non-breaking)
2. Add `surface` column with default=true for existing Things (non-breaking)
3. Update reasoning agent prompts to create relationships
4. Update context agent to traverse relationships when searching
5. Update sidebar to group by type and show project progress
6. Update ThingCard to show relationship context
</content>
</invoke>