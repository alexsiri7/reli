---
id: "001"
title: "Multi-stage agent pipeline"
status: "done"
github_issue: "955"
updated: 2026-05-12
---

## Why
A single-shot LLM call lacks the context-awareness and reasoning depth needed for a personal assistant. A pipeline where each stage has a focused role produces better results.

## What
A three-stage pipeline: Context Agent (retrieves relevant Things from the knowledge graph), Reasoning Agent (decides what to create/update/link and extracts preferences), and Response Agent (generates a natural reply shaped by learned preferences).
