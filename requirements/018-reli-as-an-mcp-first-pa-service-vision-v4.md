---
created: '2026-09-10'
github_issue: null
id: 018
status: draft
title: Reli as an MCP-first PA service (vision v4)
updated: '2026-09-10'
---

## Why

Reli was built as an application with its own three-stage agent pipeline and chat UI, and the real interface turned out to be Claude over MCP. That mismatch is the root of everything since: a second, weaker model reasoning about data a stronger model already held; proactivity implemented as LLM inference rather than as a query over check-in dates; and derived "findings" that floated free of the facts that produced them, which is why the only three requirements that ever drove work here (015-017) were all cleanup for sweep output quality.

The current code and data are being discarded and rebuilt in this repo, reusing the existing deployment. The full reasoning is in docs/vision.md v4.

## What

Reli becomes a service that lets Claude act as a complete personal assistant, measured against a single test: MCP + claude.ai + scheduled tasks together cover the whole job.

Desired behaviour:

- Everything worth remembering is a Thing — typed by tags and relationships rather than a type column — with notes, urls, priority, and a check-in date.
- A check-in date is Claude's obligation to verify state by that date, not a to-do date for the user. Most check-ins are discharged without the user ever hearing about them, by looking at Calendar, Gmail, or another Thing's state.
- Every change to the graph is recorded in an append-only journal attributed to who made it, so behaviour can be observed over time.
- Reli holds a model of its user: preferences as first-class Things anchored to a #User Thing, each linked to the specific evidence that produced it. Strength is a readable count of evidence, not a confidence float.
- Preferences are learned two ways — written mid-conversation when Claude notices one, and derived from the journal by a scheduled pass. Derived preferences go live immediately with no approval queue; the user is told about notable ones and can reject any of them.
- Conflicting preferences are both kept and put to the user in the daily conversation rather than resolved by a rule.
- Each morning Claude opens a conversation telling the user about their day, presenting only what could not be resolved overnight, and writing back decisions as they are made.
- A read-only web view shows the Thing tree, individual Things with their journal history, and the full user model with the evidence behind each preference.

Explicitly not in scope: any LLM call originating inside the Reli service, a chat interface, any write path through the frontend, vector search, multi-user support, and derived-state stores that do not link to their evidence.

## Issues

_None yet._