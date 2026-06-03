---
created: '2026-06-03'
github_issue: null
id: '015'
status: draft
title: Sweep agent mode (cleanup mandate)
updated: '2026-06-03'
---

## Why

The sweep correctly identifies actionable problems but stops at observation. Every finding requires human follow-through even for cases where the right action is unambiguous. This creates a growing queue of low-effort tasks that clog the briefing and limit the system's real leverage.

## What

High-confidence sweep findings — duplicate Things, obviously-done sub-tasks, self-invalidated findings — are executed autonomously rather than just reported. The sweep merges duplicates, closes stale items, and dismisses its own expired findings. The daily briefing surfaces a summary of actions taken alongside any remaining observations requiring human judgment.

## Issues

_None yet._