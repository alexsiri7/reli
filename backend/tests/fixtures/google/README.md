# Google API fixtures

These are **hand-authored**, not captured from a live account. No one on this repo holds a Google
credential that an agent may use, and the issue's acceptance criteria require the tests to run with
no live API calls, so the files were written against Google's published response shapes rather than
recorded from real traffic. The addresses, ids and calendar contents are invented.

Field names and nesting follow the API reference exactly, because that is the only thing these
prove:

| File | Shape of |
|---|---|
| `messages_list.json` | `users.messages.list` — id/`threadId` stubs only, which is why the reader is an N+1 |
| `messages_metadata.json` | one `users.messages.get?format=metadata` response per id, as an array the tests index by `id`. `format=metadata` returns `payload.headers`, `snippet`, `labelIds` and `internalDate` — and no body |
| `events_list.json` | `events.list` — one timed event carrying every optional field the reader reads (`attendees[].self`, `location`, a >500-character `description`, `htmlLink`) |
| `events_boundary.json` | `events.list` — an event the day before the window, an all-day event on the `until` boundary, and one the day after |

Because they are authored rather than captured, they cannot catch Google changing a field name.
The readers are written to survive that: every optional field is read with `.get`, so a missing
`location` or `attendees` yields `None`/`0` rather than a `KeyError`. Anything that turns out to be
wrong here is fixed by comparing against the API reference, not by loosening the reader.
