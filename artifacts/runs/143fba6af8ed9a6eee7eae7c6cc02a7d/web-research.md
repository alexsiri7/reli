# Web Research: fix #850

**Researched**: 2026-05-02
**Workflow ID**: 143fba6af8ed9a6eee7eae7c6cc02a7d

---

## Summary

Issue #850 is the 38th occurrence of the same `RAILWAY_TOKEN is invalid or expired: Not Authorized` failure in the staging pipeline. Web research confirms the workflow is calling Railway's GraphQL `me` query with an `Authorization: Bearer` header, which **requires an account (personal) token** — matching the prescription in `docs/RAILWAY_TOKEN_ROTATION_742.md`. Railway's public documentation does **not** describe any expiration policy or "no expiration" option for account tokens, which is the central unknown driving the recurring rotations: the runbook's "create with No expiration" instruction has no source we could find in Railway's published docs.

---

## Findings

### Railway token model: three distinct types with different semantics

**Source**: [Public API | Railway Docs](https://docs.railway.com/integrations/api)
**Authority**: Official Railway documentation
**Relevant to**: Validating that the workflow's auth pattern is using the right token type

**Key Information**:

- Three token types exist with non-interchangeable semantics:
  - **Account (personal) token** — scope: "All your resources and workspaces"; header: `Authorization: Bearer <API_TOKEN>`; **can authenticate the `me` query**.
  - **Workspace token** — scope: "Single workspace"; header: `Authorization: Bearer <WORKSPACE_TOKEN>`; explicitly **cannot** authenticate `me`: "This query cannot be used with a workspace or project token".
  - **Project token** — scope: "Single environment in a project"; header is **different**: `Project-Access-Token: <PROJECT_TOKEN>` (not `Authorization: Bearer`); also **cannot** authenticate `me`.
- The repo's `.github/workflows/staging-pipeline.yml:49-52` sends `Authorization: Bearer $RAILWAY_TOKEN` and queries `{me{id}}`. By Railway's docs, **only an account token will succeed**. This matches what `docs/RAILWAY_TOKEN_ROTATION_742.md` instructs (create at `https://railway.com/account/tokens`).
- Implication: a "Not Authorized" response on the `me` query is consistent with (a) the token having been revoked/expired, (b) the token being created as a workspace or project token instead of an account token, or (c) the token being malformed in the secret.

---

### Account token expiration / lifetime is undocumented in Railway's public docs

**Source**: [Login & Tokens | Railway Docs](https://docs.railway.com/reference/oauth/login-and-tokens), [Public API | Railway Docs](https://docs.railway.com/integrations/api), [CLI guide](https://docs.railway.com/guides/cli)
**Authority**: Official Railway documentation
**Relevant to**: Why tokens keep "expiring" — and whether the runbook's "No expiration" claim is accurate

**Key Information**:

- The OAuth/Login & Tokens page documents OAuth flows only: "Access tokens expire after one hour" and "The new refresh token has a fresh one-year lifetime from the time of issuance." These are **OAuth** access/refresh tokens, **not** the personal API tokens used by GitHub Actions.
- Across the three pages we fetched (`integrations/api`, `guides/cli`, `reference/oauth/login-and-tokens`), Railway's documentation **contains no statement** about TTL, expiration, or rotation policy for account, workspace, or project tokens.
- The runbook (`docs/RAILWAY_TOKEN_ROTATION_742.md:21`) asserts: "When creating tokens on Railway, the default TTL may be short (e.g., 1 day or 7 days). Previous rotations may have used these defaults. The new token must be created with 'No expiration'." We could not corroborate either the default-TTL claim or the "No expiration" option from official documentation. This is either UI-only behavior (changeable at any time without doc updates) or a misremembered convention.

---

### The error string "Not Authorized" can occur even with a brand-new token if token type is wrong

**Source**: [RAILWAY_TOKEN invalid or expired — Railway Help Station](https://station.railway.com/questions/railway-token-invalid-or-expired-59011e20)
**Authority**: Railway community help forum (user-reported, high signal for failure-mode taxonomy)
**Relevant to**: Distinguishing genuine expiration from token-type mismatch

**Key Information**:

- A user describes the same error string we are seeing: "RAILWAY_TOKEN now only accepts *project token*, if u put the normal account token... it literally says 'invalid or expired' even if u just made it 2 seconds ago."
- This describes the **Railway CLI** (`railway up`) behavior, not raw GraphQL. Our workflow uses raw GraphQL (`curl` to `backboard.railway.app/graphql/v2`), so the inverse holds for us: a project token would fail because `me` is an account-only query and the `Authorization: Bearer` header is wrong for project tokens.
- Takeaway: the same "invalid or expired" string is emitted both for genuine expiration **and** for token-type mismatch. The validator step cannot distinguish them. When investigating recurrences, ask the rotator to confirm token type, not just freshness.

---

### Confirmation of `me` query restriction from Railway moderator

**Source**: [GraphQL requests returning "Not Authorized" for PAT — Railway Help Station](https://station.railway.com/questions/graph-ql-requests-returning-not-authoriz-56dacb52)
**Authority**: Railway moderator response on official help forum
**Relevant to**: Reinforces that `{me{id}}` is account-token-only

**Key Information**:

- Moderator quote: "`query { me { id email } }` ... not using your personal access token here is the only reason I can see why it would be returning an authentication error."
- "There are only two scopes, personal access token and workspace access token... the personal access token is the highest level token and should work with essentially any workspace."
- This independently confirms the docs: the validator step in `staging-pipeline.yml` requires a **personal/account** token, not a workspace or project token.

---

### CLI env-var convention is the opposite of the GraphQL header convention — naming is misleading

**Source**: [Using the CLI | Railway Docs](https://docs.railway.com/guides/cli)
**Authority**: Official Railway documentation
**Relevant to**: Naming hygiene of the `RAILWAY_TOKEN` GitHub secret

**Key Information**:

- Railway CLI documents two env vars with opposite scopes from what the secret name suggests:
  - `RAILWAY_TOKEN` → "project-level actions" (i.e., expects a **project** token).
  - `RAILWAY_API_TOKEN` → "account-level actions" (i.e., expects an **account** token).
- This repo's secret is named `RAILWAY_TOKEN` but holds an **account** token (correctly, for the GraphQL `me` query). If anyone running rotation reads Railway's CLI docs without context, they could create the wrong token type for the secret name. This is a latent foot-gun in the rotation procedure, not a bug in the workflow itself (the workflow uses raw curl, not the CLI, so the env var name doesn't affect runtime behavior).

---

## Code Examples

The exact GraphQL call pattern from Railway docs that matches our validator step:

```bash
# From Railway Public API docs
# https://docs.railway.com/integrations/api
curl -X POST "https://backboard.railway.app/graphql/v2" \
  -H "Authorization: Bearer $RAILWAY_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query":"{ me { id email } }"}'
```

This is identical to `.github/workflows/staging-pipeline.yml:49-52` except Railway's docs name the variable `RAILWAY_API_TOKEN`. The HTTP semantics are the same; the variable name is a local convention.

---

## Gaps and Conflicts

- **No source corroborates "default TTL of 1 day or 7 days" for account tokens.** The claim in `docs/RAILWAY_TOKEN_ROTATION_742.md:21` could not be verified against Railway's published documentation. Either the UI exposes TTL options not described in docs, or the claim is folklore.
- **No source corroborates a "No expiration" creation option for account tokens.** Railway's public docs are silent on token TTL entirely. The option may exist in the dashboard UI; we cannot confirm without dashboard access.
- **Cannot determine *why* the token has actually expired 38 times.** Possibilities consistent with available evidence: (a) tokens are being created with a finite TTL despite the runbook's instruction, (b) Railway is silently revoking tokens (security policy, plan change, billing), (c) the token type is being mis-set on rotation and failing immediately — though the multi-day-old age of repeated failures argues against (c).
- **Frequency/cadence of expirations is not in scope of web research** but worth noting: 38 expirations is far above any plausible "natural" account-token expiry rate. The pattern itself suggests something procedural (or an account-side policy) is wrong, not just the token.

---

## Recommendations

These are research-informed observations, **not** code changes — agents cannot rotate the token (per CLAUDE.md > Railway Token Rotation).

1. **Surface the token-type ambiguity to the human rotating the token.** Update the runbook (or the issue comment) to tell the rotator: "Create an *account* (personal) token at https://railway.com/account/tokens. The validator step uses the GraphQL `me` query, which only accepts account tokens — not workspace or project tokens. The secret being named `RAILWAY_TOKEN` is misleading; it must hold an account token, not a project token."
2. **Verify the "No expiration" claim against the actual Railway dashboard during the next rotation.** If the option exists, confirm it was selected. If it doesn't exist, remove the claim from the runbook — it's misleading the human rotators every time.
3. **Consider whether the validator's error message can be improved** to distinguish "expired" from "wrong token type." The Railway API returns `"Not Authorized"` for both, but the `MSG=` capture step in `staging-pipeline.yml:54` could include a hint pointing to token-type guidance, not just rotation. (Out-of-scope for this task — would need a mayor mail per Polecat scope discipline.)
4. **The Railway Help Station thread suggests opening a Railway support ticket** if rotations continue at this cadence — sustained 30+ token revocations is unusual enough that it may indicate an account-side issue (plan, billing, security flag) only Railway support can diagnose.

---

## Sources

| # | Source | URL | Relevance |
|---|--------|-----|-----------|
| 1 | Railway Public API docs (token types, headers, `me` query) | https://docs.railway.com/integrations/api | Confirms the workflow's auth pattern requires an account token |
| 2 | Railway CLI docs (`RAILWAY_TOKEN` vs `RAILWAY_API_TOKEN` env vars) | https://docs.railway.com/guides/cli | Documents the misleading naming convention |
| 3 | Railway Login & Tokens reference | https://docs.railway.com/reference/oauth/login-and-tokens | Documents OAuth token TTLs only; silent on account-token TTL |
| 4 | Railway Help Station — "RAILWAY_TOKEN invalid or expired" | https://station.railway.com/questions/railway-token-invalid-or-expired-59011e20 | Community evidence that "invalid or expired" is also emitted for token-type mismatch |
| 5 | Railway Help Station — "GraphQL requests returning Not Authorized" | https://station.railway.com/questions/graph-ql-requests-returning-not-authoriz-56dacb52 | Moderator-confirmed that `me` query needs personal/account token |
| 6 | Railway GitHub Actions guide | https://docs.railway.com/tutorials/github-actions-pr-environment | Tutorial context on Railway × GitHub Actions integration |
| 7 | Railway blog — Using GitHub Actions with Railway | https://blog.railway.com/p/github-actions | General CI/CD integration patterns |
