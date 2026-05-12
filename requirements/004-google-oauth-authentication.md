---
id: "004"
title: "Google OAuth authentication"
status: "done"
github_issue: 955
updated: 2026-05-12
---

## Why
Reli stores personal data and needs to restrict access to the authenticated user.

## What
Google OAuth flow (`/api/auth`) issuing JWTs. The app is deployed behind authentication; only the signed-in user's data is accessible.
