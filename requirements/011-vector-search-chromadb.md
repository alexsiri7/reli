---
id: "011"
title: "Vector search (ChromaDB)"
status: "done"
github_issue: 955
updated: 2026-05-12
---

## Why
Semantic retrieval of Things requires embedding-based search, not just SQL keyword matching.

## What
ChromaDB integration storing `text-embedding-3-small` embeddings for all Things. The Context Agent uses cosine similarity search to find relevant Things for each message.
