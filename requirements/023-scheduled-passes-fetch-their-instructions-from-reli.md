---
created: '2026-09-14'
github_issue: 1506
id: '023'
status: draft
title: Scheduled passes fetch their instructions from Reli
updated: '2026-09-14'
---

## Why

The three scheduled passes are set up by pasting the contents of `prompts/scheduled/*.md` into claude.ai task settings. That copy then drifts: the repository is the source of truth, but what actually runs is whatever text was pasted, and nothing reconciles them.

This is about to bite. The prompts are being rewritten to use the session's own Calendar and Gmail rather than Reli's, and every already-configured task will keep running the old text — silently, since a pass that resolves nothing looks the same as a pass with nothing to resolve.

## What

A scheduled task holds a one-line prompt naming which pass it is. Everything else it needs, it asks Reli for.

Desired behaviour:

- A tool returns the full instructions for a named pass — resolution, learning, or morning conversation — including the shared conventions and the assistant's voice, ready to follow with no further setup.
- Changing a pass's instructions in the repository changes what the scheduled tasks do, with no human re-pasting anything into a settings field.
- The instructions name the connectors the pass expects the session to have attached, so a task set up without them says so plainly rather than resolving nothing and reporting success.
- Asking for a pass that does not exist returns the list of valid names rather than an opaque error, because the caller is an unattended session with no one to ask.
- If the instructions cannot be fetched, the pass does not improvise. It stops, and — for the morning conversation, which has a human waiting — says why.

This is the same principle already settled for interactive sessions: behaviour lives in the repository, versioned with the code that implements it, and sessions obtain it rather than carrying their own copy.

## Issues

- #1506 — Add get_scheduled_instructions so scheduled passes fetch their own prompts
