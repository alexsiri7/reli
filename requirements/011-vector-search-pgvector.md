---
id: "011"
title: "Vector search (pgvector)"
status: "done"
github_issue: "955"
updated: 2026-05-12
---

## Why
Semantic retrieval of Things requires embedding-based search, not just SQL keyword matching.

## What
pgvector integration storing `text-embedding-3-small` embeddings for all Things in a `thing_embeddings` Postgres table. The Context Agent uses cosine distance search to find relevant Things for each message.
