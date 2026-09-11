---
created: '2026-09-11'
github_issue: 1466
id: '020'
status: idea
title: Ambient PA behaviour via get_initial_instructions
updated: '2026-09-11'
---

## Why

The v4 rebuild put the PA behaviour into MCP prompts, on the assumption that the `capture` prompt would apply by default. It does not: MCP prompts in claude.ai apply only when the user explicitly selects one, so an ordinary conversation gets Reli's tools with none of its behaviour. The `capture` prompt opens by declaring itself the default for any conversation with Reli attached, and nothing makes that true.

The available workaround is to paste a condensed copy of the rules into the Claude Project instructions, which puts a second copy of the behaviour outside the repository where it will drift from `backend/prompts.py` with nothing to catch it.

## What

Any Claude session with Reli attached can obtain Reli's default operating behaviour without the user having loaded a prompt.

Desired behaviour:

- A tool, `get_initial_instructions`, returns Reli's working guidelines as text — the same behaviour the `capture` prompt describes: what is worth a Thing, how to title, tags, relate-before-create, when to set a check-in date and what one means, how and when to record preferences, and which actor to write as.
- It also orients the caller in what it does not carry: that `daily-planning`, `project-planning` and `review` are prompts to load when the conversation moves into those modes.
- It takes no arguments and reads nothing from the graph, so it is cheap to call at the start of any session.
- The guidelines it returns and the `capture` prompt cannot drift apart. One is derived from the other, and a test fails if they diverge.
- The repository documents that a Claude Project or system prompt should call this tool rather than restating Reli's rules in its own words, so the behaviour is versioned with the code that implements it.

This matches the pattern already established by Annie and Lachesis, both of which expose `get_initial_instructions` for the same purpose.

## Issues

- #1466 — Add get_initial_instructions so PA behaviour reaches every session
- #1467 — Vision doc: correct how ambient behaviour reaches a session