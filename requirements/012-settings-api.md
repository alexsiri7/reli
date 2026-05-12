---
id: "012"
title: "Settings API"
status: "done"
github_issue: 955
updated: 2026-05-12
---

## Why
User-configurable settings (model preferences, feature flags) need a persistent store accessible to both frontend and backend.

## What
`/api/settings` endpoint for reading and writing user settings stored in SQLite.
