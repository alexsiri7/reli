---
created: '2026-09-19'
github_issue: 1516
id: '024'
status: idea
title: Capture fast, fill in during the morning conversation
updated: '2026-09-22'
---

## Why

The owner captures Things on the go, as bare titles with no description and no check-in date. A Thing with no check-in date never surfaces again, so those captures sit unread and the graph fills with titles nobody can act on.

The morning conversation is already a daily conversation the owner is having, which makes it the natural place to deepen a capture at almost no cost. Two preferences recorded in the user model say exactly this: that every new Thing should get a check-in date rather than being left empty, and that the morning conversation should go deeper on bare captures with a few simple questions.

## What

A Thing captured on the go as a bare title comes back the next morning to be filled in.

Desired behaviour:

- A Thing created without a check-in date gets one, defaulting to tomorrow in Europe/London. A date passed explicitly is kept. Nothing the owner captures can silently disappear by having no date.
- Reli's own records — preferences, observations, the user anchor, scheduled-task heartbeats and briefings — never get a default date and never appear among the things due for check-in. The morning is about the owner's life, not the system's bookkeeping.
- A newly captured Thing is marked as not yet discussed, distinct from a Thing whose state needs verifying. The morning conversation clears that mark once it has been talked through.
- The morning conversation asks about a handful of undiscussed Things, newest first, one or two questions each, answerable in a word: by when, what does done look like, who is involved, part of which project. Answers are written back immediately — description, notes, a real check-in date, and a relationship to its project where there is one. The rest wait for another morning and are not mentioned.
- The overnight resolution pass gathers context for undiscussed Things from Calendar and Gmail and puts what it finds in the briefing, so the morning question can build on it. It does not try to resolve them.
- After a one-off backfill, no active Thing of the owner's is left without a check-in date.

The purpose is to build up knowledge of the owner's tasks and projects over time through short, folded-in questions — not to interrogate them.

## Issues

- #1516 — Default check-in date and #New mark on capture, excluding Reli's own records
- #1517 — Backfill: give existing dateless Things a check-in date and #New
- #1518 — Morning conversation: fill in #New Things with short questions
- #1519 — Resolution pass: gather context for #New Things without resolving them
- #1568 — Capture prompt contradicts itself on dating the user's to-dos