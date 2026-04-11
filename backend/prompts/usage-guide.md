# Reli Usage Guide

Reli is a personal knowledge graph — a second brain that stores Things (tasks, notes,
projects, people, ideas, goals) and the typed relationships between them. Use this guide
to understand the correct workflow when working with Reli via MCP.

---

## Golden Rule: Search Before You Act

**Always call `fetch_context` before creating or updating anything.**

Searching first prevents duplicates and gives you the full picture of what the user has
already stored. Never assume a Thing doesn't exist — search first, then decide whether
to create or update.

```
User: "Add a task to call Alice about the Q2 budget"

✅ CORRECT:
1. fetch_context(search_queries=["Alice", "Q2 budget", "call Alice"])
2. → Finds existing "Alice Chen" person and "Q2 budget review" project
3. create_thing(title="Call Alice about Q2 budget", type_hint="task", ...)
4. create_relationship(from=new_task, to=alice_person, type="involves")
5. create_relationship(from=new_task, to=budget_project, type="child-of")

❌ WRONG:
1. create_thing(title="Call Alice about Q2 budget", ...)
   → Creates duplicate if "Call Alice" already exists; misses context
```

---

## Core Workflow

### 1. Search for Context

Use `fetch_context` to find relevant Things before any operation:

```
fetch_context(
    search_queries=["vacation", "travel plans"],  # 1-3 relevant terms
    active_only=True,                              # filter archived items
    type_hint="project",                           # optional type filter
)
```

Use `get_thing(thing_id)` when you have a specific ID from conversation history.

### 2. Create Things

After confirming no duplicate exists, create the Thing:

```
create_thing(
    title="Vacation to Japan",
    type_hint="project",
    importance=2,                     # 0=critical, 4=backlog
    checkin_date="2026-06-01",        # when to surface in briefing
    data={"destination": "Tokyo, Kyoto", "duration": "2 weeks"},
    open_questions=["What is the budget?", "Who else is coming?"],
)
```

**importance scale:** 0 = critical (must do), 1 = high, 2 = medium (default), 3 = low, 4 = backlog

### 3. Update Things

Only update fields that need to change — all fields are optional:

```
update_thing(
    thing_id="<uuid>",
    checkin_date="2026-05-15",       # moved up
    data={"budget": "$3000"},         # shallow-merged into existing data
)
```

When a task is completed, set `active=False` to archive it (data is preserved).

### 4. Link Things with Relationships

Connect Things with typed relationships to build the knowledge graph:

```
create_relationship(
    from_thing_id="task-uuid",
    to_thing_id="project-uuid",
    relationship_type="child-of",    # task belongs to project
)
create_relationship(
    from_thing_id="task-uuid",
    to_thing_id="person-uuid",
    relationship_type="involves",    # person is involved
)
```

**Common relationship types:**
- Structural: `parent-of` / `child-of`, `depends-on` / `blocks`, `part-of` / `contains`
- Associative: `related-to`, `involves`, `tagged-with`
- Temporal: `followed-by` / `preceded-by`, `spawned-from`
- Personal: use the role directly (`manager`, `colleague`, `client`)

---

## The Knowledge Graph: Things and Types

Everything stored in Reli is a **Thing**. Things have a `type_hint` that describes
what they are:

| type_hint   | When to use                                              | Visible in views? |
|-------------|----------------------------------------------------------|-------------------|
| `task`      | Actionable work item with a clear outcome                | Yes               |
| `note`      | Freeform information or observation                      | Yes               |
| `idea`      | Something to explore or brainstorm                       | Yes               |
| `project`   | Container for related tasks and notes                    | Yes               |
| `goal`      | High-level objective (parent of tasks)                   | Yes               |
| `journal`   | Reflective or diary-style entry                          | Yes               |
| `person`    | Someone the user interacts with                          | No (graph only)   |
| `event`     | A specific meeting or occurrence                         | No (graph only)   |
| `place`     | A physical or virtual location                           | No (graph only)   |
| `concept`   | An abstract idea or recurring theme                      | No (graph only)   |
| `reference` | External resource (URL, book, document)                  | No (graph only)   |
| `preference`| Learned user behavior pattern (managed automatically)    | No (graph only)   |

Entity types (person, event, place, etc.) are graph nodes — they should be created
with `surface=False` so they don't clutter default views but remain searchable.

---

## When to Use `reli_think`

`reli_think` is reasoning-as-a-service: send a natural language description and get
back structured instructions for what to create, update, or link. Use it when:

- The user's request is complex (multiple entities and relationships in one message)
- You're unsure how to map natural language to specific CRUD operations
- The request involves interpretation ("organize my week", "what should I focus on?")

```
reli_think(
    message="I finished the project proposal and sent it to Sarah. Now I need to
             schedule a follow-up call with her for next week.",
    context="Recent: 'Website Redesign Proposal' project, 'Sarah (Manager)' person",
)
→ Returns: instructions to mark proposal done, create follow-up task, link to Sarah
```

For simple, unambiguous requests ("add a task called X"), skip `reli_think` and use
the CRUD tools directly — it's faster.

---

## Staying Informed: Briefing and Conflicts

### Daily Briefing

```
get_briefing()  # What needs attention today
```

Returns approaching checkin dates and sweep findings (stale items, overdue check-ins,
neglected high-importance Things). Surface this proactively at the start of a session.

### Open Questions

```
get_open_questions()  # Things with unresolved knowledge gaps
```

Use this to proactively ask the user about gaps you recorded when creating Things.
Ask one question at a time — don't barrage the user.

### Conflicts

```
get_conflicts(window=14)  # Blockers, deadline conflicts, schedule overlaps
```

Surface blocking chains and deadline conflicts so the user can act before it's too late.

---

## Merging Duplicates

When you discover two Things representing the same real-world entity:

1. `fetch_context` to compare both
2. `merge_things(keep_id="primary-uuid", remove_id="duplicate-uuid")`

The merge preserves all data and transfers all relationships to the kept Thing.
The duplicate is permanently removed. Always keep the more complete record.

---

## What Reli Does NOT Do

- **No hard deletes via MCP**: `delete_thing` soft-deletes (sets `active=False`).
  Data is preserved — it can be undeleted by setting `active=True`.
- **No external data**: Reli stores what you tell it. Use `chat_history` to recall
  past conversations, not to retrieve external information.
- **No auto-sync**: Reli does not watch your calendar, email, or files. You describe
  what happens; Reli records it.
