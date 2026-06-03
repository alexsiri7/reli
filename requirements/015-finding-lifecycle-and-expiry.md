---
created: '2026-06-03'
github_issue: null
id: '015'
status: draft
title: Finding lifecycle and expiry
updated: '2026-06-03'
---

## Why

Findings accumulate nightly with no mechanism to expire or self-invalidate. Findings based on stale context (wrong location, outdated project state) continue to surface indefinitely, progressively degrading the signal-to-noise ratio and eroding trust in the briefing.

## What

Each finding carries a context snapshot or TTL at creation time. On subsequent sweeps, findings are re-validated before surfacing — findings whose underlying context has materially changed are auto-dismissed. The finding backlog never grows unboundedly; stale findings disappear without manual intervention.

## Issues

_None yet._