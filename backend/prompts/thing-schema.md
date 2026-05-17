# Reli Thing Schema Reference

## Thing Fields

| Field          | Type            | Default | Description                                    |
|----------------|-----------------|---------|------------------------------------------------|
| id             | string (UUID)   | auto    | Unique identifier                              |
| title          | string          | —       | Short descriptive name (1–500 chars, required) |
| type_hint      | string or null  | null    | Category for filtering and display             |
| checkin_date   | ISO 8601 or null| null    | When to surface this Thing in the daily briefing |
| importance     | int (0–4)       | 2       | How bad if undone: 0 = critical, 4 = backlog   |
| active         | bool            | true    | false = completed/archived (never hard-delete) |
| surface        | bool            | true    | false = graph entity, hide from default views  |
| data           | object or null  | null    | Arbitrary JSON for custom fields and notes     |
| open_questions | string[] or null| null    | Unresolved knowledge gaps about this Thing     |
| created_at     | ISO 8601        | auto    | Creation timestamp                             |
| updated_at     | ISO 8601        | auto    | Last-modified timestamp                        |

## type_hint

`type_hint` is open-ended — use any lowercase singular noun that fits.

### System types (preferred when they fit)

| type_hint   | Meaning                                            | surface default |
|-------------|---------------------------------------------------|-----------------|
| task        | Actionable work item with a clear outcome          | true            |
| note        | Freeform information or observation                | true            |
| idea        | Something to explore or brainstorm                 | true            |
| project     | Container for related tasks and notes              | true            |
| goal        | High-level objective (parent of tasks)             | true            |
| journal     | Reflective or diary-style entry                    | true            |
| preference  | Learned user preference pattern                    | false           |
| person      | A person the user interacts with                   | false           |
| place       | A physical or virtual location                     | false           |
| event       | A specific occurrence or meeting                   | false           |
| concept     | An abstract idea or recurring topic                | false           |
| reference   | An external resource (URL, book, document, etc.)   | false           |

### Custom types
Use a custom type when no system type fits: "trip", "recipe", "rehearsal", "habit", "gig", etc.
Custom types default to `surface=true`.

## Relationship Types

| Category    | Types                                                         |
|-------------|---------------------------------------------------------------|
| Structural  | parent-of / child-of, depends-on / blocks, part-of / contains |
| Associative | related-to, involves, tagged-with                             |
| Temporal    | followed-by / preceded-by, spawned-from / spawned             |
| Possessive  | Use the role as type (sister, doctor, manager, colleague, etc.) |

Relationships are directed: `from_thing_id` → `to_thing_id` with a `relationship_type` label. Prefer semantic opposites (parent-of/child-of) over creating both directions.

## open_questions

`open_questions` is an array of strings representing knowledge gaps:

- Add 1–3 questions when creating a Thing if important context is missing
- Example: `["What is the deadline?", "Who else is involved?"]`
- When the user answers a question, remove it from the array and store the answer in `data`
- Do NOT re-ask questions whose answers are already in `data`

## Preference Things and Confidence Tracking

Personality preferences are stored as `type_hint: "preference"` Things. The `data` field holds a `patterns` array:

```json
{
  "title": "How the user wants Reli to communicate",
  "type_hint": "preference",
  "surface": false,
  "data": {
    "patterns": [
      {
        "pattern": "Prefers concise responses",
        "confidence": "strong",
        "observations": 12,
        "last_observed": "2025-06-01"
      }
    ]
  }
}
```

**Confidence levels** (based on observation count):
- `emerging` — 1 observation (tentative signal, may be noise)
- `moderate` — 2–3 observations (consistent pattern)
- `strong` — 4+ observations (reliable, override defaults)

**Resolution order** (highest wins):
1. Explicit user correction in current session
2. Strong confidence preferences
3. Moderate / emerging preferences
4. Default personality (warm, proactive, supportive)
5. Fixed constraints (grounding, no hallucination, one question at a time)

## Well-Formed Thing Examples

### Task
```json
{
  "title": "Draft Q1 budget spreadsheet",
  "type_hint": "task",
  "importance": 2,
  "checkin_date": "2025-03-31",
  "data": {"notes": "Due before board meeting"},
  "open_questions": ["Who needs to review it before submission?"]
}
```

### Person
```json
{
  "title": "Alice Chen",
  "type_hint": "person",
  "surface": false,
  "data": {"email": "alice@example.com", "notes": "Engineering manager, met at AWS re:Invent"},
  "open_questions": ["What team does she manage?"]
}
```

### Project
```json
{
  "title": "Website Redesign",
  "type_hint": "project",
  "importance": 1,
  "data": {"deadline": "2025-09-01", "stakeholder": "Marketing team"}
}
```

### Preference
```json
{
  "title": "How Alex wants Reli to communicate",
  "type_hint": "preference",
  "surface": false,
  "data": {
    "patterns": [
      {"pattern": "No emoji", "confidence": "strong", "observations": 5},
      {"pattern": "Bullet points over prose", "confidence": "moderate", "observations": 3}
    ]
  }
}
```

### Event
```json
{
  "title": "Q2 Planning Offsite",
  "type_hint": "event",
  "surface": false,
  "data": {"event_date": "2025-04-15", "location": "San Francisco", "attendees": "Leadership team"}
}
```

## Naming Conventions

- **Titles**: Specific and descriptive ("Draft Q1 budget" not "Work on budget")
- **Relationship types**: Lowercase hyphen-separated ("depends-on", "parent-of")
- **Data keys**: snake_case (e.g. `due_date`, `event_date`, `last_contacted`)
- **Dates in data**: ISO 8601 format (`YYYY-MM-DD`) for date-based surfacing to work
