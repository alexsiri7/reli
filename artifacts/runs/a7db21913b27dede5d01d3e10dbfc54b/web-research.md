# Web Research: fix #836

**Researched**: 2026-05-01T07:45:00Z
**Workflow ID**: a7db21913b27dede5d01d3e10dbfc54b
**Issue**: Main CI red — `Deploy to staging` failing at "Validate Railway secrets" with `RAILWAY_TOKEN is invalid or expired: Not Authorized` (33rd identical-shape recurrence; prior workflow `c2f4f36352b6bae6a5b97a5ca7802f0e`)

---

## Summary

This run is the second pickup of issue #836 (the prior workflow produced PR #837, a docs-only investigation receipt; the actual rotation requires a human and remains pending). Fresh 2026-05-01 searches confirm and reinforce the prior research:

- Railway publishes **four token types** (Account, Workspace, Project, OAuth) with **different headers and different scopes** — `Authorization: Bearer` + the `{me{id}}` GraphQL probe used by `staging-pipeline.yml:49-58` only succeeds with a personal **Account token created with "No workspace" selected**.
- **No 2026 Railway changelog entry** mentions API-token policy, rotation, or expiration changes; the January 28-29, 2026 Railway incident was a GitHub OAuth rate-limit issue, **not** PAT revocation. The recurrence is therefore operator-side (token-creation procedure / wrong scope), not Railway-side TTL enforcement.
- Railway docs now explicitly recommend **Workspace tokens** as "the right choice for team CI/CD" (clarified in current `docs.railway.com/integrations/api`), which is a slightly stronger steer than what was reflected in the prior research's recommendations.

The actionable fix (rotate the secret) is unchanged and remains a **human-only task** per `CLAUDE.md > Railway Token Rotation`.

---

## Findings

### 1. Token type matrix — confirmed unchanged

**Source**: [Public API | Railway Docs](https://docs.railway.com/integrations/api)
**Authority**: Official Railway documentation
**Relevant to**: Why `RAILWAY_TOKEN` keeps "expiring"; how to construct a token that actually validates

**Key Information** (re-verified 2026-05-01):

- Four token types: **Account, Workspace, Project, OAuth**.
- Account & Workspace tokens authenticate with `Authorization: Bearer <TOKEN>`.
- **Project tokens require `Project-Access-Token: <TOKEN>`** — using `Authorization: Bearer` with a project token returns `Not Authorized`.
- Canonical endpoint: `https://backboard.railway.com/graphql/v2` (the `.app` host still resolves; `.com` is current).
- **`{ me { id } }` is personal-account scoped** and "cannot be used with a workspace or project token because the data returned is scoped to your personal account." Workspace and project tokens have no associated user record and will return `Not Authorized` against this query — indistinguishable from genuine expiration.

---

### 2. Railway explicitly recommends Workspace tokens for team CI/CD (new emphasis)

**Source**: [Public API | Railway Docs](https://docs.railway.com/integrations/api) (re-checked 2026-05-01)
**Authority**: Official Railway documentation
**Relevant to**: Long-term structural fix — out-of-scope for #836 but informs the future bead

**Key Information**:

- Account tokens (created with "No workspace") have "the broadest scope, and can perform any API action you're authorized to do across all your resources and workspaces."
- Workspace tokens "are scoped to a single workspace, **which is the right choice for team CI/CD**."
- Project tokens "are scoped to a specific environment within a project and can only be used to authenticate requests to that environment."

This is a more emphatic recommendation than the prior research surfaced. For `staging-pipeline.yml` the implication is:

- Today's validator (`{me{id}}`) **only accepts Account tokens** — a human rotating a Workspace token will fail validation forever.
- A future structural bead should either (a) keep using an Account token and document this hard requirement in the runbook, or (b) migrate to a Workspace token and change the validation query (e.g. `{ projects { edges { node { id } } } }`).

---

### 3. `Not Authorized` ≠ "expired" — token-creation procedure is the dominant failure mode

**Source**: [API Token "Not Authorized" Error for Public API and MCP — Railway Help Station](https://station.railway.com/questions/api-token-not-authorized-error-for-pub-82b4ccf1)
**Authority**: Railway support thread, resolved by a Railway employee
**Relevant to**: Root cause of recurring "Not Authorized" failures

**Key Information** (re-verified):

- "Not Authorized" can stem from token *creation procedure*, not actual expiration.
- Resolution from Railway staff: tokens for the public API must be created at `railway.com/account/tokens` with **"No workspace" selected**.
- A token assigned to a specific workspace at creation time cannot answer `{ me { id } }` and will fail authorization checks that rely on it — even though the token is otherwise "valid" for some operations.

**Implication for #836**: If the human operator has been rotating tokens from inside a workspace context (or with a workspace pre-selected in the UI), every rotation will fail validation. The runbook (`docs/RAILWAY_TOKEN_ROTATION_742.md`) does say "No expiration" but does NOT explicitly call out "No workspace" — this is the most likely cause of the 33-cycle recurrence and the runbook should be updated (out of scope here; flag for follow-up bead).

---

### 4. Account-scoped token is correct for GitHub Actions

**Source**: [Token for GitHub Action — Railway Help Station](https://station.railway.com/questions/token-for-git-hub-action-53342720)
**Authority**: Railway employee answer
**Relevant to**: Choosing the right secret for `staging-pipeline.yml`

**Key Information** (re-verified):

- Railway employee: "use a Railway API token scoped to the user account, not a project token" for GitHub Actions.
- Suggested env var: `RAILWAY_API_TOKEN` (but `RAILWAY_TOKEN` is still accepted and takes precedence if both are set — older CLI bug fixed in railwayapp/cli PR #668).
- For projects in a workspace: "ensure that the token specified is scoped to your account, not just the workspace."

This means the current variable name (`RAILWAY_TOKEN`) is *not* itself the problem; the validator and token-class are.

---

### 5. OAuth tokens — separate family, 1h access / 1y refresh, rotation revokes

**Source**: [Login & Tokens | Railway Docs](https://docs.railway.com/integrations/oauth/login-and-tokens)
**Authority**: Official Railway documentation
**Relevant to**: Ruling out OAuth as the recurrence driver

**Key Information** (re-verified):

- OAuth **access tokens expire after 1 hour**.
- OAuth **refresh tokens have a 1-year lifetime**, refreshed on use.
- Using an already-rotated refresh token "immediately revokes the entire authorization."
- This family is **not** the same as Account/Workspace/Project API tokens used in CI; OAuth is for third-party apps.

**Implication**: The 1-hour TTL only applies to OAuth access tokens. There is no documented TTL for the API tokens used in `RAILWAY_TOKEN`.

---

### 6. No 2026 Railway changelog entry explains the recurrence

**Source**: [Changelog | Railway](https://railway.com/changelog) (fetched 2026-05-01)
**Authority**: Official Railway changelog
**Relevant to**: Whether Railway changed token policy recently

**Key Information**:

- Direct fetch of the changelog shows **no 2026 entries mentioning API tokens, personal access tokens, RAILWAY_TOKEN, token rotation, token expiration, or workspace/account/project tokens**.
- If Railway had silently introduced a TTL on Account tokens, it would be documented here (and would be widely reported in the help station — it is not).
- Conclusion: the recurring expiration is not driven by a Railway-side policy change in 2026. It is operator-side.

---

### 7. January 2026 Railway incident — unrelated to PAT revocation

**Source**: [Incident Report: January 28-29, 2026](https://blog.railway.com/p/incident-report-january-26-2026)
**Authority**: Official Railway incident report
**Relevant to**: Ruling out a recent Railway incident as a token-revocation cascade

**Key Information** (fetched 2026-05-01):

- The Jan 28-29 incident was a GitHub OAuth rate-limit issue: "the `installationTokenById` dataloader was creating new tokens on every request batch without caching across requests."
- Affected GitHub installation tokens used for Railway → GitHub API calls, not user-side personal access tokens.
- **No PAT revocation, no GitHub Actions impact**.

This rules out an "incident triggered cascade revocation" theory for #836's recurrence cluster.

---

### 8. Personal/Workspace/Project token lifetime — still undocumented

**Source**: [Public API | Railway Docs](https://docs.railway.com/integrations/api), [Railway changelog](https://railway.com/changelog), [Token for GitHub Action thread](https://station.railway.com/questions/token-for-git-hub-action-53342720)
**Authority**: Official docs + employee answers (cross-referenced 2026-05-01)
**Relevant to**: Whether the recurrence is a "scheduled expiration"

**Key Information**:

- **None of the official sources document an expiration TTL** for Account, Workspace, or Project tokens. They are presented as long-lived bearer credentials.
- Documented lifetimes apply only to OAuth (1 h access / 1 yr refresh).
- Conclusion (re-confirmed): if a non-OAuth token is repeatedly rejected, the most likely root causes — in descending order of probability — are:
  1. **Token type / creation-procedure mismatch** — the validator's `{me}` + `Authorization: Bearer` shape only matches an Account token created with "No workspace".
  2. Manual revocation (someone rotating in another tab, or a related session being logged out via password change / 2FA reset).
  3. Refresh-token rotation collateral damage on linked OAuth grants.
  4. Transient Railway-side `Not Authorized` (occasional reports on the help station).

---

### 9. Health-check shape that actually validates the token type in use

**Source**: [GraphQL requests returning "Not Authorized" for PAT — please inspect traceIds](https://station.railway.com/questions/graph-ql-requests-returning-not-authoriz-56dacb52), [Public API | Railway Docs](https://docs.railway.com/integrations/api)
**Authority**: Railway support + official docs
**Relevant to**: Reducing false-positive "expired" alerts (structural fix; out-of-scope for #836)

**Key Information**:

- For a workspace token, validate with a workspace-scoped query (e.g. `{ projects { edges { node { id } } } }`) — not `{ me }`.
- For a project token, the header must be `Project-Access-Token` and the query must be project-scoped (e.g. `{ projectToken { projectId environmentId } }` or `{ project { id name } }`).
- Mismatched header/query shape returns `Not Authorized` even when the underlying token is valid. The current workflow's error string ("invalid or expired") conflates these — every operator since #742 has been told the token "expired" when many of those cycles were probably wrong-shape.
- Surfacing the raw `errors[0].message` plus Railway's `traceId` on validation failure would let humans (and Railway support, if pinged) tell expiration apart from misconfiguration.

---

## Code Examples

Health-check shapes by token type, suitable for a CI validation step:

```bash
# Account token (current pattern — works only with No-workspace personal tokens)
# Host matches `.github/workflows/staging-pipeline.yml:49` for byte-identical CI reproduction
# (the `.app` host still resolves; `.com` is the current docs name — see "Host" note below)
curl -sf -X POST "https://backboard.railway.app/graphql/v2" \
  -H "Authorization: Bearer $RAILWAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query":"{ me { id } }"}'

# Workspace / Team token — does NOT have `me`, so check workspace metadata instead
curl -sf -X POST "https://backboard.railway.app/graphql/v2" \
  -H "Authorization: Bearer $RAILWAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query":"{ projects { edges { node { id } } } }"}'

# Project token — different header AND no `me`
curl -sf -X POST "https://backboard.railway.app/graphql/v2" \
  -H "Project-Access-Token: $RAILWAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query":"{ projectToken { projectId environmentId } }"}'
```

A diagnostic variant that surfaces Railway's traceId when validation fails (out-of-scope to ship for #836; recorded for the future structural bead):

```bash
# Print errors[0].message + traceId so humans can distinguish "expired"
# from "wrong token type" without guessing.
resp=$(curl -sS -X POST "https://backboard.railway.com/graphql/v2" \
  -H "Authorization: Bearer $RAILWAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query":"{ me { id } }"}')
echo "$resp" | jq -e '.data.me.id' >/dev/null || {
  echo "Validation failed:"
  echo "$resp" | jq '{message: .errors[0].message, traceId: .errors[0].extensions.traceId}'
  exit 1
}
```

---

## Gaps and Conflicts

- **Gap**: Still no official documented TTL for Account / Workspace / Project tokens. Railway docs remain silent on whether they expire on a schedule (re-checked 2026-05-01).
- **Gap**: No public Railway changelog entry in 2026 explains the cluster of expirations beginning around #824–#836 — i.e., the recurrence is **not** correlated with a known Railway-side change.
- **Conflict (resolved)**: Help-station threads describing account tokens as "long-lived and stable" vs this repo's experience of repeated invalidation. The most parsimonious explanation, given evidence, is operator-side procedure (workspace not set to "No workspace" at creation time, or wrong-class token being rotated each cycle), not a Railway TTL.
- **Gap**: It's still unclear from public sources whether changing the Railway account password, rotating any other personal token, or any 2FA event triggers a cascade revocation. Worth confirming with Railway support if the human operator is doing any of those activities between rotations.

---

## Recommendations

For the immediate #836 rotation (within scope):

1. **Tell the human operator explicitly: "No workspace" must be selected.** The current runbook (`docs/RAILWAY_TOKEN_ROTATION_742.md`) mentions "No expiration" but is silent on workspace selection. The latter is the more likely cause of the 33-cycle pattern. Per `CLAUDE.md > Railway Token Rotation` the agent cannot rotate, but the investigation/PR comment should call this out so the human gets it right this cycle.
2. **Per `CLAUDE.md`, do NOT create a `.github/RAILWAY_TOKEN_ROTATION_836.md` claiming rotation is done.** This research is informational; actual rotation requires a human with Railway dashboard access. Direct the operator to `docs/RAILWAY_TOKEN_ROTATION_742.md`.

For the structural fix (out-of-scope for #836; flag for a future bead):

3. **Differentiate "expired" from "wrong shape" in the validator.** Update `staging-pipeline.yml:49-58` to surface raw `errors[0].message` + Railway `traceId`. Distinguishing HTTP 401/Not-Authorized-with-`me` from HTTP-200-with-empty-`data.me` would stop conflating "expired" with "workspace-scoped token".
4. **Consider migrating to a Workspace token.** Railway's docs now explicitly recommend Workspace tokens as "the right choice for team CI/CD". They survive a single user's account changes. Trade-off: the validation query must change (no `me`); see the workspace shape in the Code Examples section.
5. **Update the rotation runbook to require both "No expiration" AND "No workspace".** The current runbook only mentions the former. This is the cheapest single change that could break the recurrence cycle.
6. **Do NOT** assume the recurrence is an unavoidable Railway-side TTL — the 2026 changelog has no entries that would explain it, and a daily auto-expiration would be widely reported in support channels (it is not).

---

## What changed since the prior workflow's research (`c2f4f36352b6bae6a5b97a5ca7802f0e`)

Honest delta — the prior research is largely correct and complete. This refresh adds:

- **Confirmed via direct changelog fetch**: no 2026 Railway changelog entries on token policy. This was inferred in the prior run; now verified.
- **Confirmed via direct incident-report fetch**: the Jan 28-29, 2026 Railway incident is unrelated to PAT revocation. New context the prior research did not have.
- **Stronger steer on Workspace tokens for CI/CD**: current Railway docs phrasing is now "the right choice for team CI/CD" (more emphatic than the prior research reflected).
- **Sharpened Recommendation #1**: the runbook should explicitly require "No workspace" at creation time. The prior research listed this as a finding; this refresh elevates it to the top-line operator action because the 33-cycle pattern strongly implies the human is currently missing this checkbox each cycle.

No prior finding has been invalidated.

---

## Sources

| # | Source | URL | Relevance |
|---|--------|-----|-----------|
| 1 | Public API — Railway Docs | https://docs.railway.com/integrations/api | Token types, headers, endpoint, "right choice for team CI/CD" phrasing |
| 2 | API Token "Not Authorized" — Help Station | https://station.railway.com/questions/api-token-not-authorized-error-for-pub-82b4ccf1 | "No workspace" requirement for `{me}` |
| 3 | Token for GitHub Action — Help Station | https://station.railway.com/questions/token-for-git-hub-action-53342720 | Account-scoped token recommended for GHA |
| 4 | Login & Tokens — Railway Docs | https://docs.railway.com/integrations/oauth/login-and-tokens | OAuth TTLs (1 h access / 1 yr refresh) — separate family from PATs |
| 5 | Railway Changelog | https://railway.com/changelog | No 2026 token-policy entries (verified by direct fetch) |
| 6 | Incident Report Jan 28-29, 2026 | https://blog.railway.com/p/incident-report-january-26-2026 | Unrelated to PAT revocation (verified by direct fetch) |
| 7 | Using GitHub Actions with Railway — Railway blog | https://blog.railway.com/p/github-actions | Project-token GHA setup pattern |
| 8 | GraphQL "Not Authorized" for PAT — Help Station | https://station.railway.com/questions/graph-ql-requests-returning-not-authoriz-56dacb52 | Trace-ID debugging pattern |
| 9 | Railway tokens dashboard | https://railway.com/account/tokens | Where to create the right kind of token |
| 10 | Using the CLI — Railway Docs | https://docs.railway.com/cli | `RAILWAY_TOKEN` vs `RAILWAY_API_TOKEN` precedence |
| 11 | Introduction to GraphQL — Railway Docs | https://docs.railway.com/integrations/api/graphql-overview | GraphQL endpoint and schema introspection |
| 12 | Prior workflow web-research | `artifacts/runs/c2f4f36352b6bae6a5b97a5ca7802f0e/web-research.md` | Baseline this refresh extends |
