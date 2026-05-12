---
id: "002"
title: "Knowledge graph (Things)"
status: "done"
github_issue: 955
updated: 2026-05-12
---

## Why
User data needs structured representation beyond plain text to support semantic queries, relationship traversal, and preference tracking over time.

## What
A typed knowledge graph where all stored information (tasks, notes, people, projects, places) becomes a "Thing" with relationships to other Things. Backed by SQLite + ChromaDB vector embeddings. CRUD API at `/api/things`.
