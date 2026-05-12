---
id: "009"
title: "Multi-model configuration"
status: "done"
github_issue: "955"
updated: 2026-05-12
---

## Why
Different pipeline stages have different latency/cost tradeoffs. Allowing per-stage model selection keeps costs low while preserving quality where it matters.

## What
`config.yaml` specifying independent models for context, reasoning, and response stages. All routed through Requesty (OpenAI-compatible gateway). Overridable via environment variables.
