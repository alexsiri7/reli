---
name: Web Research — Issue #854 (RAILWAY_TOKEN expiration, 39th occurrence, 2nd pickup)
description: Web research informing the recurring RAILWAY_TOKEN failure; this run confirms the Project-token validation query and the absence of any official "No expiration" UI option, building on prior workflow 8a2386c3
---

# Web Research: fix #854

**Researched**: 2026-05-02T02:35:00Z
**Workflow ID**: `0aa164affe30087c42fdb1f17b4c013d`
**Issue**: [#854 — Main CI red: Deploy to staging](https://github.com/alexsiri7/reli/issues/854) (39th occurrence of `RAILWAY_TOKEN is invalid or expired: Not Authorized` in `staging-pipeline.yml` step `Validate Railway secrets`).

**Prior art**: Workflow `8a2386c3ae1983d14df8161ca0d0849e` (~2h earlier today) produced a comprehensive `web-research.md` for the same issue. This document does **not** restate that work verbatim — it confirms the open questions from that artifact against authoritative Railway docs and adds two new findings.

Path of prior artifact: `/home/asiri/.archon/workspaces/alexsiri7/reli/artifacts/runs/8a2386c3ae1983d14df8161ca0d0849e/web-research.md`

---

## Summary

Two questions were left open by prior research and are now answered:

1. **The official Railway API docs do NOT document any "No expiration" option** for any token type (account, workspace, or project). The internal runbook `docs/RAILWAY_TOKEN_ROTATION_742.md` instructs the rotator to "select No expiration", but no public Railway documentation corroborates such a UI affordance exists. This makes the runbook's central premise unverified — a likely reason the issue has now recurred 39 times.
2. **The Project-token validation query is now confirmed** as `query { projectToken { projectId environmentId } }` (verbatim from Railway's Public API docs). This was marked "confirm against the GraphQL schema before implementing" in prior research — it is now a known-good probe, removing the technical blocker for migrating `staging-pipeline.yml` to a Project token.

The 2025/2026 Railway changelog contains **no** token-related entries, so the community claim ("Railway changed token requirements") is not officially substantiated; the recurrence pattern is the only evidence that something has shifted.

Action posture is unchanged: agent cannot rotate the token; human action against railway.com + GitHub Actions secrets is the only fix. See investigation.md for the human checklist.

---

## Findings

### 1. Confirmed: Railway docs document NO expiration UI for any static token

**Source**: [Public API | Railway Docs](https://docs.railway.com/integrations/api) (fetched 2026-05-02)
**Authority**: Official Railway documentation
**Relevant to**: The runbook's "select No expiration" instruction.

**Key Information** (verbatim from the fetched page summary):

| Token type | Auth header | Docs example validation query | TTL/expiration mentioned? |
|------------|-------------|-------------------------------|---------------------------|
| Account    | `Authorization: Bearer <API_TOKEN>` | `query { me { name email } }` | **No** |
| Workspace  | `Authorization: Bearer <WORKSPACE_TOKEN>` | `query { workspace(workspaceId: "<WORKSPACE_ID>") { name id } }` | **No** |
| Project    | `Project-Access-Token: <PROJECT_TOKEN>` | `query { projectToken { projectId environmentId } }` | **No** |

The docs do not describe the token-creation UI's expiration controls at all. The OAuth flow (a separate concept, not what CI uses) is documented as 1-hour access tokens / 1-year refresh tokens — no relation to the static `RAILWAY_TOKEN` secret.

**Why this matters**: The runbook (`docs/RAILWAY_TOKEN_ROTATION_742.md` line 22) tells the human "**Expiration: No expiration** (critical — do not accept default TTL)". If this UI option does not exist, the runbook is impossible to follow correctly, and every "rotation" produces a token with whatever the default TTL is. After 39 occurrences this is the most plausible failure mode — the runbook itself is the bug.

**What to do next**: When the human next rotates, screenshot the Railway token-creation UI. Either (a) confirm "No expiration" exists and was missed previously, or (b) confirm it doesn't exist and update the runbook to reflect the actual default TTL.

---

### 2. Confirmed: Project-token validation query

**Source**: [Public API | Railway Docs](https://docs.railway.com/integrations/api)
**Authority**: Official Railway documentation
**Relevant to**: The Project-token migration path proposed in prior research §3 / Recommendation 3.

**Key Information**: The exact query the validator step would use after migration is:

```bash
curl -sf -X POST "https://backboard.railway.app/graphql/v2" \
  -H "Project-Access-Token: $RAILWAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query":"{ projectToken { projectId environmentId } }"}'
```

A non-error response with both fields populated means the token is valid for the bound environment.

Prior research left this query as an unverified hypothesis. With the official docs example in hand, the migration is now technically a one-PR change:

1. Generate a Project token under the project's Settings → Tokens (not Account → Tokens).
2. Update the `RAILWAY_TOKEN` GitHub Actions secret with the new token.
3. Edit `.github/workflows/staging-pipeline.yml`:
   - Change `Authorization: Bearer ***` → `Project-Access-Token: ***`.
   - Change `'{"query":"{me{id}}"}'` → `'{"query":"{ projectToken { projectId environmentId } }"}'`.
   - Update the success check from `.data.me.id` → `.data.projectToken.projectId`.
4. Confirm the deploy job (which presumably uses the Railway CLI's `railway up` or similar) still works — the CLI accepts `RAILWAY_TOKEN` in either form, but verify against the deploy step.

**This is still out of scope for issue #854.** The change is clearly defined now, but #854 is a "rotate the secret" ticket, not a "refactor the auth model" ticket. Send to mayor as a follow-up, per polecat scope discipline.

---

### 3. Confirmed: No 2025–2026 changelog entries on token behavior

**Source**: [Changelog | Railway](https://railway.com/changelog)
**Authority**: Official Railway product changelog
**Relevant to**: The community claim ([Help Station thread](https://station.railway.com/questions/railway-token-invalid-or-expired-59011e20)) that "Railway changed its token requirements".

**Key Information**: A scan of 2025/2026 changelog entries returned **no** mentions of API tokens, account tokens, project tokens, expiration, rotation, or session/token revocation. Entries in the period cover features like Undoable Volume Deletes, Railway Agent, IPv6, CDN integration, and AI features — nothing in the auth/token space.

**Implication**: The "Railway changed token requirements" claim from the community thread is **unsupported by official sources**. It remains a hypothesis. The 39-occurrence pattern could equally be explained by (a) the runbook's "No expiration" step being wrong (Finding 1), or (b) Railway silently expiring tokens on a TTL the docs don't disclose, or (c) some account-level event (password reset, plan downgrade) that is not documented as a token-revoking event.

---

### 4. Strengthened: Community thread says project tokens are now mandatory

**Source**: [RAILWAY_TOKEN invalid or expired — Railway Help Station](https://station.railway.com/questions/railway-token-invalid-or-expired-59011e20) (re-fetched 2026-05-02)
**Authority**: Community user (`bytekeim`); no Railway staff confirmation
**Relevant to**: Whether the repo's account-token approach is structurally obsolete.

**Key information** (paraphrased from the fetched thread):

- The OP reported the same `RAILWAY_TOKEN invalid or expired` message and that recreating the token "does nothing".
- `bytekeim` claimed "RAILWAY_TOKEN now only accepts project token" — that account tokens no longer work for the `RAILWAY_TOKEN` slot. Recommended fix: generate the token under project settings, not account settings; remove any `RAILWAY_API_TOKEN` variable.
- **Railway staff did not respond directly** to the token-type claim — only automated suggestions linking to other issues. So this is community lore, not vendor-confirmed.

**Implication**: This thread, taken with Finding 1 (no documented "No expiration" option for account tokens) and Finding 2 (Project-token migration is technically straightforward), strengthens the case for migrating off account tokens — even though prior research correctly classified it as out of scope for #854.

---

## Code Examples

Current validator (account token, account-token query — what's failing):

```bash
# .github/workflows/staging-pipeline.yml — current
RESP=$(curl -sf -X POST "https://backboard.railway.app/graphql/v2" \
  -H "Authorization: Bearer ${{ secrets.RAILWAY_TOKEN }}" \
  -H "Content-Type: application/json" \
  -d '{"query":"{me{id}}"}')
echo "$RESP" | jq -e '.data.me.id' > /dev/null \
  || { echo "::error::RAILWAY_TOKEN is invalid or expired: $(echo "$RESP" | jq -r '.errors[0].message')"; exit 1; }
```

Migration target (Project token, Project-token query — confirmed against [official docs](https://docs.railway.com/integrations/api)):

```bash
# .github/workflows/staging-pipeline.yml — proposed (FOLLOW-UP, NOT FOR #854)
RESP=$(curl -sf -X POST "https://backboard.railway.app/graphql/v2" \
  -H "Project-Access-Token: ${{ secrets.RAILWAY_TOKEN }}" \
  -H "Content-Type: application/json" \
  -d '{"query":"{ projectToken { projectId environmentId } }"}')
echo "$RESP" | jq -e '.data.projectToken.projectId' > /dev/null \
  || { echo "::error::RAILWAY_TOKEN (project token) rejected: $(echo "$RESP" | jq -r '.errors[0].message')"; exit 1; }
```

---

## Gaps and Conflicts

- **The "No expiration" UI claim is now actively contradicted** by the absence of any such option in the Railway docs (Finding 1). It's still possible the option exists in the live UI and is undocumented — only a screenshot from the next human rotation will resolve this.
- **Railway staff have not publicly confirmed or denied the "account tokens no longer work" hypothesis** (Finding 4). Worth posting on the Help Station as a follow-up to get an authoritative answer, but that's beyond what an automated agent can do.
- **No upstream changelog signal** for any of this. If Railway tightened token policy, they didn't announce it (Finding 3).
- **CLI behavior** with project vs account tokens for the actual `railway up` deploy step is still unverified. The validator change is well-defined; the deploy-step compatibility needs to be tested in a follow-up branch before any migration ships.

---

## Recommendations

Carrying forward the prior research's recommendations, with two updates from this run:

1. **Do NOT rotate the token from this agent.** Unchanged — Category 1 trap per `CLAUDE.md`.

2. **When the human next rotates, capture ground truth on the "No expiration" option.** Now upgraded to **HIGH PRIORITY**: the docs explicitly do not describe such an option, so the runbook is suspect until proven correct. Screenshot the UI either way.

3. **Migrate the deploy job to a Project token (follow-up issue).** Now technically de-risked — the validator query is `query { projectToken { projectId environmentId } }` per official docs, and the diff to `staging-pipeline.yml` is mechanically small. Still out of scope for #854; send to mayor.

4. **Long-term: investigate OAuth refresh-token flow.** Unchanged — eliminates static-token recurrence entirely but is significant net-new work.

5. **Do not modify the validation step in this PR.** Unchanged — the validator is correctly catching the bug, not causing it.

---

## Sources

| # | Source | URL | Relevance |
|---|--------|-----|-----------|
| 1 | Railway Docs — Public API (re-fetched 2026-05-02) | https://docs.railway.com/integrations/api | Confirmed: validation queries per token type; no expiration UI documented |
| 2 | Railway Docs — Login & Tokens | https://docs.railway.com/integrations/oauth/login-and-tokens | OAuth/refresh — separate from static API tokens; no static-token TTL |
| 3 | Railway — Changelog (scanned 2025–2026) | https://railway.com/changelog | Confirmed: no token-related entries in the relevant period |
| 4 | Railway Help Station — RAILWAY_TOKEN invalid or expired (re-fetched 2026-05-02) | https://station.railway.com/questions/railway-token-invalid-or-expired-59011e20 | Community claim: account tokens no longer accepted; no Railway staff confirmation |
| 5 | Railway Help Station — GraphQL "Not Authorized" for PAT | https://station.railway.com/questions/graph-ql-requests-returning-not-authoriz-56dacb52 | Community note: `me` query requires personal/account token |
| 6 | Railway Blog — Using GitHub Actions with Railway | https://blog.railway.com/p/github-actions | Official recommendation to use Project tokens for CI |
| 7 | Prior research artifact (workflow `8a2386c3…`) | `artifacts/runs/8a2386c3ae1983d14df8161ca0d0849e/web-research.md` | Comprehensive baseline this artifact builds on, not duplicates |
