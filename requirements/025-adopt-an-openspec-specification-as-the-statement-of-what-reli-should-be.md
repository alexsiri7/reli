---
created: '2026-09-28'
github_issue: 1632
id: '025'
status: idea
title: Adopt an OpenSpec specification as the statement of what Reli should be
updated: '2026-09-28'
---

## Why

Requirement files record changes, not what Reli should be. Auditing Reli against them means replaying a change log: 001–017 describe a system the v4 rebuild deleted, and 018–024 each amend what came before. Their hand-kept status drifts too, and many are recorded wrongly here: 018 and 019 are recorded as "idea" and 021 as "draft", yet all three are built, while most of 001–017 are recorded "done" but are obsolete. A spec per capability, changed only through spec-change pull requests, gives one document to audit the code against and lets Lachesis derive status from the work itself. This is the same move Lachesis made in its own requirement 030.

## What

The repository holds Reli's specification in OpenSpec format under `openspec/specs/`, one file per capability:
- access-control
- assistant-behaviour
- mutation-journal
- scheduled-passes
- service-boundaries
- standing-queries
- things-graph
- user-model
- web-view

CI validates the specification on every pull request and every push to the default branch. From then on, work on Reli starts as a spec change, and the existing requirement files are superseded by the spec.

## Issues

- #1632 — Add Reli's OpenSpec specification and validate it in CI