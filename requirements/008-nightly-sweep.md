---
id: "008"
title: "Nightly sweep"
status: "done"
github_issue: "955"
updated: 2026-05-12
---

## Why
Proactive assistance requires a background analysis pass — not just responding to messages, but identifying gaps and patterns the user hasn't asked about.

## What
A nightly sweep job (`/api/sweep`) that performs gap detection, pattern aggregation, and generates a briefing. Runs on a schedule.
