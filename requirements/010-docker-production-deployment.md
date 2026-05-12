---
id: "010"
title: "Docker production deployment"
status: "done"
github_issue: "955"
updated: 2026-05-12
---

## Why
Reproducible, isolated deployment to Railway (staging + prod) with persistent data volumes.

## What
Multi-stage Dockerfile (Node build + Python runtime), Docker Compose for local prod simulation, Cloudflare Tunnel for public access. Data persists in `./data/` volume. CI via GitHub Actions.
