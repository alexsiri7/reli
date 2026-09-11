---
created: '2026-09-11'
github_issue: 1448
id: 019
status: idea
title: Restore Google OAuth for the web view and MCP
updated: '2026-09-11'
---

## Why

The v4 rebuild (requirement 018) replaced Google OAuth on the web view with an HTTP Basic password and the MCP's auth with a shared bearer token. That was never asked for and was never a decision — it fell out of the vision doc's "no accounts, single-user access control" non-goal being read as a licence to discard working authentication. The owner lost access to both the web view and the MCP connector as a result.

The separate data-in-a-public-repo rule is here because requirement 018's issues instructed agents to commit a production graph export and Gmail-derived test fixtures to this repository. The export was never committed, but the instruction was given, and nothing in CLAUDE.md currently prevents it happening again.

## What

Google OAuth is the way in to Reli, as it was before the v4 rebuild.

Desired behaviour:

- Opening the web view presents Google sign-in. The owner's Google account is the only account allowed in; any other account is refused with a clear message rather than a blank failure.
- The MCP endpoint authenticates the way it did before the rebuild, so a claude.ai connector authorises against Google rather than carrying a shared bearer token.
- No HTTP Basic password anywhere. `WEB_UI_PASSWORD` is gone once Google sign-in is verified working, and not before.
- A revoked or expired grant produces a message naming what a human needs to re-run, not a silent 401.

This is a recovery, not a new design. Working implementations of both exist in this repository's git history, immediately before the v4 rebuild deleted them. They are to be read and restored, porting them onto the new backend and the read-only frontend, rather than reimplemented from the specification.

Separately, and independently of the auth work: this repository is public. No real user data may be committed to it — not graph exports, not tag statistics, not recorded Gmail or Calendar fixtures. Test fixtures are synthetic.

## Issues

- #1448 — Recover the pre-v4 Google OAuth implementation from git history
- #1449 — Restore Google OAuth on the web view
- #1450 — Restore the MCP endpoint's original authentication
- #1451 — CLAUDE.md: this is a public repo, no real user data in it