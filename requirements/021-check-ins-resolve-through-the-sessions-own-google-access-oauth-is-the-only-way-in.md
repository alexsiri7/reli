---
created: '2026-09-12'
github_issue: null
id: '021'
status: draft
title: Check-ins resolve through the session's own Google access; OAuth is the only
  way in
updated: '2026-09-12'
---

## Why

Reli built its own Google Calendar and Gmail readers so the resolution pass could settle check-ins. But a scheduled pass is a Claude session, and a Claude session already has Calendar and Gmail connectors. Reli maintaining a second, parallel Google integration duplicates the surface, adds a credential the owner must mint by hand, and fails the vision doc's own test: if MCP plus claude.ai plus scheduled tasks can do something better, Reli should not be doing it.

It is also the current blocker. Reli's Google tools error with "Google is not configured", so the resolution pass can resolve nothing and every check-in lands on the owner — which is the difference between a PA and a task list.

Separately, the HTTP Basic password introduced during the v4 rebuild was never wanted. Its last consumer, the GitHub Actions watchdog, is being removed.

## What

Reli holds no Google integration of its own, and Google sign-in is the only way into Reli.

Desired behaviour:

- The scheduled passes resolve check-ins using the Calendar and Gmail connectors attached to the Claude session running them, not through Reli. A check-in on a booked flight is settled by the session reading the confirmation itself.
- Reli exposes no Calendar or Gmail tools and holds no Google API credential. `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` and `GOOGLE_REFRESH_TOKEN` for data access are gone, along with the human step of minting a refresh token.
- The judgement that made those tools worth having is preserved in the prompts that now do the work: lookups return evidence rather than a verdict, an empty result may mean a thing did not happen or that it left no trace, and telling those apart is the caller's job.
- Google sign-in is unaffected. It remains the single way a human reaches the web view and the single way an MCP client authorises.
- There is no password anywhere. `WEB_UI_PASSWORD` does not exist, in the deploy, in CI, or in the code.

Explicitly unchanged: the `#ScheduledTask` heartbeat convention, and a missed run surfacing in `due_for_checkin` for every session.

## Issues

_None yet._