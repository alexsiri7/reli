# Web Research: fix #909 — Main CI red: Deploy to staging (RAILWAY_TOKEN invalid/expired)

**Researched**: 2026-05-02
**Workflow ID**: 71a21444dc75f75167bd149ae06d3f82

---

## Summary

Issue #909 is the 62nd recurrence of `RAILWAY_TOKEN is invalid or expired: Not Authorized`
during the staging deployment's "Validate Railway secrets" step. The validation step
posts a `query { me { id } }` GraphQL request to `https://backboard.railway.app/graphql/v2`.
Web research surfaces two distinct failure modes that produce the same error message:
(1) a Railway Personal Access Token (PAT) that has expired (the runbook's working
hypothesis), and (2) a token-type/query mismatch — the `me` query requires a Personal
Access Token and returns "Not Authorized" when called with a Project Token or Workspace
Token, even when the token is valid. The recurring nature of this incident (62 times,
~21 today) plus Railway's own guidance suggesting Project Tokens for CI/CD warrants
verifying which failure mode is actually firing before another rotation.

---

## Findings

### 1. Railway has four token types with different scopes and capabilities

**Source**: [Public API | Railway Docs](https://docs.railway.com/integrations/api)
**Authority**: Official Railway documentation
**Relevant to**: Token selection for CI/CD validation logic

**Key Information**:

- Four token types: **Account token** (all resources/workspaces), **Workspace token**
  (single workspace), **Project token** (single environment in a project), **OAuth token**
  (user-granted permissions).
- The official docs **do not document expiration policies or TTL options** for any token
  type — there is no documented "No Expiration" setting. The current runbook
  (`docs/RAILWAY_TOKEN_ROTATION_742.md` line 20) instructs operators to choose
  "No expiration", but that option's existence and behavior is not corroborated by
  official docs.
- Account tokens are passed via `Authorization: Bearer <token>`. Project tokens
  reportedly use a different header (`Project-Access-Token`) — see Finding 3.

---

### 2. The `me` query requires a Personal/Account Token — Project Tokens get "Not Authorized"

**Source**: [GraphQL requests returning "Not Authorized" for PAT — Railway Help Station](https://station.railway.com/questions/graph-ql-requests-returning-not-authoriz-56dacb52)
**Authority**: Railway-hosted community forum with moderator response
**Relevant to**: Whether the validation step in `.github/workflows/staging-pipeline.yml`
is even correct for the token type being stored as `RAILWAY_TOKEN`

**Key Information**:

- Direct quote from Railway moderator: *"`query { me { id email } }` requires personal
  access token iirc, not using your personal access token here is the only reason I can
  see why it would be returning an authentication error."*
- The `me` query is account-scoped and **cannot be used with Project or Workspace tokens**.
- This means: a perfectly valid, non-expired Project Token will produce the exact same
  `Not Authorized` error our validation reports.

---

### 3. Railway recommends Project Tokens for CI/CD (CLI deploy via `railway up`)

**Source**: [Token for GitHub Action — Railway Help Station](https://station.railway.com/questions/token-for-git-hub-action-53342720)
and [RAILWAY_TOKEN Invalid or Expired — Railway Help Station](https://station.railway.com/questions/railway-token-invalid-or-expired-59011e20)
**Authority**: Railway-hosted community forum
**Relevant to**: Token-type vs query-type mismatch hypothesis

**Key Information**:

- `RAILWAY_TOKEN` is conventionally a **Project Token**; `RAILWAY_API_TOKEN` is conventionally
  an **Account/Workspace Token**.
- Quote: *"RAILWAY_TOKEN now only accepts project token, if u put the normal account
  token... it literally says 'invalid or expired' even if u just made it 2 seconds ago."*
- Project Tokens use the `Project-Access-Token` header (not `Authorization: Bearer`)
  per multiple community posts.
- Cross-implication: if the secret is a Project Token (Railway's recommended choice for
  `railway up`), then *both* the query (`me`) and the header (`Authorization`) used by
  our validation are wrong. If it's an Account Token, the validation logic is correct
  and the failure mode is genuine expiration.

---

### 4. OAuth access tokens expire in ~1 hour; non-OAuth token TTLs are undocumented

**Source**: [Login & Tokens | Railway Docs](https://docs.railway.com/integrations/oauth/login-and-tokens)
**Authority**: Official Railway documentation
**Relevant to**: Whether tokens can plausibly expire 21 times in a single day

**Key Information**:

- OAuth access tokens expire in 1 hour; refresh tokens are used for renewal.
- For Account/Workspace/Project tokens (the dashboard-generated kind), Railway publishes
  no TTL or expiration policy. Anecdotal community reports describe tokens "just stopping
  working" without a documented schedule.
- A token expiring 21 times in one calendar day is implausible for a static-secret token
  with reasonable TTL — pointing toward either (a) a token-type/validation mismatch
  surfacing as "expired", (b) a Railway-side revocation event, or (c) the validation
  step being executed against many CI runs after a single underlying invalidation.

---

### 5. Best-practice guidance: use OIDC / dynamic secrets instead of long-lived static tokens

**Source**: [Best Practices for Managing and Rotating Secrets in GitHub Repositories — GitHub Community](https://github.com/orgs/community/discussions/168661)
and [Secretless Access for GitHub Actions and Workflows — Aembit](https://aembit.io/blog/secretless-access-for-github-actions/)
**Authority**: Official GitHub community discussion and security vendor blog
**Relevant to**: Long-term mitigation for the recurring rotation cycle

**Key Information**:

- Recommended pattern: short-lived dynamic secrets fetched at runtime via OIDC trust
  rather than long-lived secrets stored in GitHub Actions secrets.
- "Always set an expiration date" is also called out — the *opposite* of the current
  runbook's "No expiration" instruction. The runbook's advice optimizes for fewer
  rotation incidents; the security guidance optimizes for blast-radius. These are
  in tension and the project should pick one deliberately.
- Railway does not appear to advertise OIDC-based auth for GitHub Actions as of the
  search date — so OIDC is aspirational, not directly available.

---

### 6. Validation endpoint domain — `.app` vs `.com` is reportedly cosmetic

**Source**: Railway Help Station search results (multiple threads)
**Authority**: Railway-hosted community forum
**Relevant to**: Sanity-checking the exact URL used in validation

**Key Information**:

- Some community posts mention `https://backboard.railway.com/graphql/v2` as "the
  correct API endpoint" instead of `.app`. However, the same posts note that switching
  domains does not by itself fix authorization issues.
- The validation script currently uses `backboard.railway.app` — likely fine, but worth
  noting if other diagnostics fail.

---

## Code Examples

### Validation that works for an Account/Personal token (current code, kept verbatim)

```yaml
# From .github/workflows/staging-pipeline.yml (current implementation)
RESP=$(curl -sf -X POST "https://backboard.railway.app/graphql/v2" \
  -H "Authorization: $RAILWAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query":"{me{id}}"}')
```

This works *only* if `$RAILWAY_TOKEN` is an Account/Personal Access Token. With a
Project Token it will return `Not Authorized` (per [Finding 2](https://station.railway.com/questions/graph-ql-requests-returning-not-authoriz-56dacb52)).

### Validation pattern that would work for a Project Token (from community guidance)

```bash
# Header: Project-Access-Token, not Authorization: Bearer
# Query: a project-scoped query, not `me`
curl -sf -X POST "https://backboard.railway.app/graphql/v2" \
  -H "Project-Access-Token: $RAILWAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query":"{ projectToken { projectId environmentId } }"}'
```

> Note: exact project-token introspection query is not in official docs and would need
> verification against Railway's GraphQL schema before adoption.

---

## Gaps and Conflicts

- **Gap**: Railway's official docs publish no TTL/expiration policy for Account,
  Workspace, or Project tokens. The "No expiration" option referenced in the project's
  rotation runbook is not corroborated by official documentation in 2026.
- **Gap**: No published Railway GraphQL query is documented as "the canonical health
  check for a Project Token". Validation patterns are folklore from community posts.
- **Conflict**: The project's runbook (#742) advises creating tokens with
  "No expiration" (longevity-first); industry secret-rotation guidance advises always
  setting expiration (security-first). Both can't be right for the same threat model.
- **Conflict**: Some sources call `.com` the canonical API host; the current code uses
  `.app`. Both appear to work, but only the `.app` form is actively tested in the repo.
- **Unknown**: Whether the secret currently stored as `RAILWAY_TOKEN` is an Account
  token or a Project token. Distinguishing this is the critical next step — it
  determines whether the validation logic is correct or structurally broken.

---

## Recommendations

1. **Before another rotation, verify token type.** Ask the human operator (only they
   have railway.com access) whether the `RAILWAY_TOKEN` secret is generated from
   *Account Settings → Tokens* (Personal/Account token) or from a specific
   *Project → Settings → Tokens* page (Project Token). If it's a Project Token,
   the recurring "expired" failures may be a validation-logic bug, not real expirations,
   and rotating the token will not fix the underlying issue.

2. **If the secret is an Account/Personal token**, the runbook's existing fix
   (rotate + select "No expiration") is the right path — and the token-type/query
   mismatch hypothesis is ruled out. The recurring rotations then point at either
   defaults being re-selected during rotation, or Railway-side invalidation events.
   Consider documenting a short post-rotation smoke test that re-runs the validation
   immediately so token-type errors are caught at rotation time, not at next deploy.

3. **If the secret is a Project Token**, *do not rotate* — change the validation to
   use a project-scoped query and the `Project-Access-Token` header (or skip
   pre-validation and let the actual `railway up` step fail loudly). This would
   eliminate a structural source of false-positive "expirations".

4. **Out of scope for this bead but worth a mail-to-mayor**: the long-term fix is
   either (a) Railway-side OIDC integration if/when offered, or (b) a stable secret
   manager (Doppler, HashiCorp Vault, AWS Secrets Manager + GitHub OIDC) that handles
   rotation centrally. Per CLAUDE.md's Polecat Scope Discipline, file as a separate
   issue rather than expanding this one.

5. **Per CLAUDE.md, agents cannot rotate the token.** This research informs the
   diagnostic framing only — the actual remediation (token rotation, dashboard access)
   remains a human task. The research output should be attached to a GitHub issue
   directing the human operator to the runbook plus the question in Recommendation #1.

---

## Sources

| # | Source | URL | Relevance |
|---|--------|-----|-----------|
| 1 | Railway Docs — Public API | https://docs.railway.com/integrations/api | Official enumeration of token types and scopes |
| 2 | Railway Docs — Login & Tokens | https://docs.railway.com/integrations/oauth/login-and-tokens | OAuth token TTL (1h); silent on dashboard token TTL |
| 3 | Railway Help Station — Not Authorized for PAT | https://station.railway.com/questions/graph-ql-requests-returning-not-authoriz-56dacb52 | Moderator confirms `me` query requires PAT |
| 4 | Railway Help Station — RAILWAY_TOKEN invalid or expired | https://station.railway.com/questions/railway-token-invalid-or-expired-59011e20 | RAILWAY_TOKEN expects Project Token; mismatch shows as "expired" |
| 5 | Railway Help Station — API Token "Not Authorized" | https://station.railway.com/questions/api-token-not-authorized-error-for-pub-82b4ccf1 | Workspace assignment can affect token validity |
| 6 | Railway Help Station — Token for GitHub Action | https://station.railway.com/questions/token-for-git-hub-action-53342720 | RAILWAY_TOKEN vs RAILWAY_API_TOKEN convention |
| 7 | Railway Blog — Using GitHub Actions with Railway | https://blog.railway.com/p/github-actions | Project tokens enable CLI access; no rotation guidance |
| 8 | GitHub Community — Best Practices for Rotating Secrets | https://github.com/orgs/community/discussions/168661 | Industry guidance: short-lived secrets, always set expiration |
| 9 | Aembit — Secretless Access for GitHub Actions | https://aembit.io/blog/secretless-access-for-github-actions/ | OIDC-based dynamic secrets as long-term mitigation |
| 10 | Railway Incident Report — Jan 2026 | https://blog.railway.com/p/incident-report-january-26-2026 | Recent Railway-side incidents (background context) |
