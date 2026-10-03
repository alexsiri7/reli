---
created: '2026-10-03'
github_issue: 1640
id: '026'
status: idea
title: Morning conversation asks follow-up questions one at a time
updated: '2026-10-03'
---

## Why

The morning conversation lists open items and the questions each one needs, but it never actually asks anything. The user gets a status dump and the conversation doesn't move. Alex, 2026-10-03: "you're mentioning things, but you're not actually asking anything. The idea is that you should ask me follow-up questions (one at a time)." The morning push is the only part of the run he sees, and a list of seven open items with questions buried inside them gets no replies. That's four mornings running with no answers on the #New captures.

## What

- The morning push gives a short one-to-two-line context (calendar shape, overnight status) and then ends with exactly one direct question. That question is the most important open item: decisions first, then unresolved items, then #New captures (always including the oldest).
- The run keeps an ordered queue of the remaining questions, from the briefing's decisions/unresolved and the selected #New captures, in the Morning conversation Thing's notes. The briefing is still archived on delivery.
- When Alex replies in the session, his answer is written back to the relevant Thing as now, and the reply carries the next question from the queue. One question per turn, never a list.
- If he skips or deflects, that Thing keeps its state and the next question follows. The queue doesn't restart from the top.
- The queue ends when it's empty or when he signals he's done. Then one closing line, no recap.
- Unanswered questions carry into the next morning's ordering without being re-listed.

## Issues

- #1640 — Morning prompt: end the push with one question, then ask the rest one per turn