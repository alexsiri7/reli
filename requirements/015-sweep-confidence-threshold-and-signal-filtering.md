---
created: '2026-06-03'
github_issue: null
id: '015'
status: draft
title: Sweep confidence threshold and signal filtering
updated: '2026-06-03'
---

## Why

The sweep generates ~60 findings per run, the majority being lifestyle tips or location-based suggestions built on stale context. The low-value findings dilute the handful of genuinely actionable ones, making the briefing harder to parse and act on. Quantity without quality is worse than fewer findings.

## What

The sweep applies a minimum confidence threshold before surfacing a finding. Low-value finding categories — unsolicited lifestyle advice, location-based suggestions, tips derived from unverified context — are suppressed or omitted entirely. Each surfaced finding includes the confidence level and the context it was based on. The daily briefing is materially shorter and more actionable.

## Issues

_None yet._