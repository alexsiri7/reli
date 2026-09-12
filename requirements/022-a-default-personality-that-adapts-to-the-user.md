---
created: '2026-09-12'
github_issue: 1492
id: '022'
status: idea
title: A default personality that adapts to the user
updated: '2026-09-12'
---

## Why

The assistant reads as a competent tool rather than as someone's PA. The behaviour rules say what to capture and how to title it, but nothing says how to talk, so every session sounds like a default assistant.

A fixed personality alone would be the wrong fix: a voice the user cannot move is one they will end up working around. Tone is a preference like any other, and the user model already exists to hold preferences with their evidence and apply them by scope.

Note that `docs/vision.md` currently lists personality adaptation as a non-goal, on the reasoning that Claude's own tone handling covers it. That has been overtaken: the user has asked for a default personality that adapts, and the non-goal is withdrawn rather than worked around.

## What

Reli's assistant has a voice, and that voice moves toward what the user actually wants.

Desired behaviour:

- Out of the box the assistant is warm, upbeat and direct. It says what it did rather than asking whether it may, it leads with the answer, and it does not pad or flatter.
- The voice is a starting point, not a fixture. Tone preferences are recorded like any other preference, under a `voice` scope, with evidence, and they shape every subsequent session. "Less chirpy about money things" or "stop opening with a summary" changes how the assistant talks from then on.
- The voice applies everywhere a session behaves as the assistant: interactive conversations and the morning conversation alike. It is one definition, not a copy per surface.
- Confidence of manner never becomes confidence of fact. The assistant sounds certain about what it has done and unhesitant about raising what the user is avoiding, while remaining plain about what it does not know or has not checked. It never states something it has not verified in a tone that implies it has.
- Voice preferences are correctable and rejectable in the web view like every other preference, and visible with the evidence behind them.

## Issues

- #1492 — A default voice, defined once and carried everywhere
- #1493 — Voice preferences: a `voice` scope the user can move
- #1494 — Vision doc: withdraw the personality non-goal