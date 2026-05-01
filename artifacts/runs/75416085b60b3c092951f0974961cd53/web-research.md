# Web Research: fix #833

**Researched**: 2026-05-01T09:05:00Z
**Workflow ID**: 75416085b60b3c092951f0974961cd53
**Issue**: [#833 — Prod deploy failed on main](https://github.com/alexsiri7/reli/issues/833)
**Failing run**: https://github.com/alexsiri7/reli/actions/runs/25201008471
**Failing step**: `Validate Railway secrets` → `RAILWAY_TOKEN is invalid or expired: Not Authorized`
**Recurrence**: 33rd identical-shape cycle (this is the 3rd archon re-fire on #833 after PR #834 merged)

---

## Summary

This is the 33rd `RAILWAY_TOKEN is invalid or expired: Not Authorized` recurrence and the third re-fire on the same issue. Per `CLAUDE.md > Railway Token Rotation`, agents cannot rotate the secret — only a human with railway.com dashboard access can. Research surfaces four points the human rotator should act on: (1) **the validator at `.github/workflows/staging-pipeline.yml:49-58` uses `Authorization: Bearer` against `{me{id}}`, which is account-token semantics — a project token cannot pass it** (project tokens have no `me` user); (2) account tokens created with a *workspace selected* become workspace-scoped and **also fail `{me{id}}`** even when freshly minted, producing the same misleading "invalid or expired" message; (3) Railway's recent (Jan 26–29 2026) public incident was about GitHub OAuth installation tokens, not `RAILWAY_TOKEN` — unrelated to this recurrence; (4) Railway still does not support GitHub OIDC federation, so static-token rotation remains the only viable CI auth path until that changes.

---

## Findings

### 1. The validator is account-token-shaped — project tokens cannot pass it

**Source**: Repo file `.github/workflows/staging-pipeline.yml:49-58` (read 2026-05-01)
**Authority**: Authoritative — this is the actual code that fails
**Relevant to**: Disambiguating which Railway token class the rotator must produce

**Key Information**:

```yaml
RESP=$(curl -sf -X POST "https://backboard.railway.app/graphql/v2" \
  -H "Authorization: Bearer $RAILWAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query":"{me{id}}"}')
if ! echo "$RESP" | jq -e '.data.me.id' > /dev/null 2>&1; then
  ...
  echo "::error::RAILWAY_TOKEN is invalid or expired: $MSG"
  exit 1
fi
```

The validator (and the subsequent `serviceInstanceUpdate` mutation at lines 70–78) uses:
- Header: `Authorization: Bearer $RAILWAY_TOKEN`
- Query: `{me{id}}` against `https://backboard.railway.app/graphql/v2`

`{me{id}}` resolves a *user* identity. Project tokens have no associated user — they identify a project, and Railway exposes them via the `Project-Access-Token: <token>` header per the [Railway Public API docs](https://docs.railway.com/integrations/api). Pushing a project token through this validator returns `data.me = null`, which the validator surfaces as `RAILWAY_TOKEN is invalid or expired: Not Authorized` — the same string emitted on a genuinely expired account token. **The validator can only pass with an account token (non-workspace-scoped — see Finding 2).**

The repo runbook [`docs/RAILWAY_TOKEN_ROTATION_742.md`](https://github.com/alexsiri7/reli/blob/main/docs/RAILWAY_TOKEN_ROTATION_742.md) is consistent with this — it directs the rotator to `https://railway.com/account/tokens` (the account/personal token page).

---

### 2. Workspace-scoped account tokens also fail `{me{id}}` — likely root cause of recurrences

**Source**: [RAILWAY_TOKEN invalid or expired — Railway Help Station](https://station.railway.com/questions/railway-token-invalid-or-expired-59011e20) and search-result excerpt from the same thread
**Authority**: Railway-staffed community help; corroborated by multiple user reports
**Relevant to**: Why a freshly rotated account token can still fail validation immediately — the missing piece in prior cycles

**Key Information** (paraphrased from search-result excerpt of the thread, since the WebFetch summary truncated this detail):

> "When creating the token in the accounts page, if you weren't leaving the workspace blank and were setting it to your default workspace, it makes a workspace-scoped token. To create an account-scoped token, you have to create one in the accounts page, but leave the workspace blank."

**Why this matters for #833**: Railway's UI at `https://railway.com/account/tokens` may pre-select a default workspace. Tokens created with a workspace selected resolve to workspace identity, not user identity, and the GraphQL `{me{id}}` query returns null for them — producing the exact "invalid or expired" failure mode we keep seeing, *even when the rotator just created the token*. After 33 recurrences with the same shape, this is a credible explanation: prior rotators may have left the workspace selector at its default value, producing workspace-scoped tokens that the validator silently treats as expired.

**Action for the rotator**: at the create-token form on https://railway.com/account/tokens, **explicitly clear the workspace field** so the token is account-scoped, *not* workspace-scoped.

---

### 3. Pre-save verification — quote the same probe before storing

**Source**: Synthesis of Findings 1 and 2 plus general API-key rotation hygiene from prior research's [securebin.ai rotation guide](https://securebin.ai/blog/api-key-rotation-best-practices/)
**Authority**: Combination of the workflow's own contract + standard pre-flight pattern
**Relevant to**: Eliminating the round-trip cost of "rotate → push → re-run CI → discover wrong token type"

**Key Information**:

Before running `gh secret set RAILWAY_TOKEN`, the rotator can verify in one curl that the new token will pass the workflow's exact validator:

```bash
curl -sf -X POST "https://backboard.railway.app/graphql/v2" \
  -H "Authorization: Bearer <NEW_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"query":"{me{id}}"}' | jq '.data.me.id'
```

- Output is a non-null string → token is account-scoped (good, store it).
- Output is `null` or the response carries an `errors` array → token is project-scoped, workspace-scoped, or expired (bad, do not store).

This makes Finding 2's failure mode visible *before* a red CI run forces a 34th cycle.

---

### 4. Railway's January 26–29, 2026 incident is not the cause of this recurrence

**Source**: [Incident Report: January 28-29, 2026 — Railway Blog](https://blog.railway.com/p/incident-report-january-26-2026)
**Authority**: Railway's own post-mortem
**Relevant to**: Ruling out a Railway-side outage as the explanation for `Not Authorized` here

**Key Information**:

- Window: January 26–29, 2026 (well before this incident on 2026-05-01).
- Affected: GitHub login auth, connecting new GitHub repos, deploys from GitHub repos.
- Root cause: `installationTokenById` dataloader regenerated GitHub OAuth installation tokens per request, exhausting GitHub's 2,000-tokens-per-hour rate limit (~82 new tokens/sec at peak).
- Resolution: token caching, migration from user-OAuth to installation tokens, manual repo sync.

**Verdict**: this incident is unrelated to `RAILWAY_TOKEN`. It involved GitHub-issued OAuth tokens that Railway uses internally to fetch repo state. `RAILWAY_TOKEN` is a Railway-issued static API token. They share neither lifecycle nor identity surface. Don't conflate.

---

### 5. Railway still does not support GitHub OIDC federation

**Sources**:
- [Public API | Railway Docs](https://docs.railway.com/integrations/api) — no OIDC mention
- [Login & Tokens | Railway Docs](https://docs.railway.com/integrations/oauth/login-and-tokens) — covers OAuth-for-third-party-apps only
- [Configuring OpenID Connect in cloud providers — GitHub Docs](https://docs.github.com/actions/deployment/security-hardening-your-deployments/configuring-openid-connect-in-cloud-providers) — Railway not listed among supported providers
- 2026 OIDC search results return guides for GCP/AWS/Azure exclusively; no Railway implementations surfaced

**Authority**: Combined Railway and GitHub primary docs
**Relevant to**: Whether the rotation pain can be eliminated by adopting short-lived federated credentials

**Key Information**:

GitHub Actions OIDC lets a runner exchange its built-in JWT for a short-lived cloud credential per job — no static secret required. For this to work on Railway, Railway must implement an OIDC trust relationship and accept GitHub's JWTs at its API surface. As of this research (2026-05-01), no such surface exists in Railway's docs, blog, or community. Until Railway ships OIDC federation, **the only available levers are reducing rotation frequency (no-expiration tokens) and detecting expiry early (scheduled validation cron)**.

---

### 6. Existing prior research on this exact recurrence is comprehensive — this re-fire's contribution is incremental

**Source**: [`artifacts/runs/09146632082d189318409846f65d7fd6/web-research.md`](https://github.com/alexsiri7/reli/blob/main/artifacts/runs/09146632082d189318409846f65d7fd6/web-research.md) (merged via PR #834)
**Authority**: Prior archon re-fire on the same issue, already merged to `main`
**Relevant to**: Avoiding duplicate documentation while still surfacing what changed

**Key Information**:

The prior re-fire's `web-research.md` already documents:
- Railway's four token types (account/workspace/project/OAuth) and their respective headers
- Token TTL configuration and the "No expiration" option
- Lack of GitHub OIDC support on Railway
- Industry rotation hygiene (dual-secret rotation, scheduled validation, audit logs)

**What this re-fire adds**:
- Explicit reconciliation of the prior research's *project-token* recommendation against the workflow's actual *account-token-shaped* validator (Finding 1) — these are not contradictory once the validator code is read.
- The **workspace-scoped account-token failure mode** (Finding 2) — a credible explanation for why even a freshly rotated token can fail the same way.
- A **pre-save verification curl** the rotator can run before pushing to GitHub secrets (Finding 3).
- Confirmation that Railway's recent (Jan 2026) incident is not the cause (Finding 4).

---

## Code Examples

### Pre-save token verification (recommended for the rotator)

```bash
# Run BEFORE `gh secret set RAILWAY_TOKEN` to catch wrong-class / workspace-scoped tokens.
NEW_TOKEN="<paste_just-created_railway_token>"
curl -sf -X POST "https://backboard.railway.app/graphql/v2" \
  -H "Authorization: Bearer $NEW_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query":"{me{id}}"}' | jq '.data.me.id // "FAIL — not account-scoped"'
# Expected: a non-null string (e.g. "abcd1234-...").
# Anything else means the token will not pass .github/workflows/staging-pipeline.yml validation.
```

### Existing validator step (excerpt from the failing workflow, for reference)

```bash
# .github/workflows/staging-pipeline.yml:49-58
RESP=$(curl -sf -X POST "https://backboard.railway.app/graphql/v2" \
  -H "Authorization: Bearer $RAILWAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query":"{me{id}}"}')
if ! echo "$RESP" | jq -e '.data.me.id' > /dev/null 2>&1; then
  MSG=$(echo "$RESP" | jq -r '.errors[0].message // "could not reach Railway API or token rejected"')
  echo "::error::RAILWAY_TOKEN is invalid or expired: $MSG"
  echo "Rotate the token — see DEPLOYMENT_SECRETS.md Token Rotation section."
  exit 1
fi
```

---

## Gaps and Conflicts

- **Apparent conflict between prior research and current finding** — *resolved*. Prior research cited the Railway help thread saying "`RAILWAY_TOKEN` only accepts project tokens." That guidance is *for the Railway CLI*, which expects the env var named `RAILWAY_TOKEN` to be a project token. **Our workflow does not use the Railway CLI** in the failing step — it directly issues a GraphQL POST with `Authorization: Bearer`, which is account-token semantics regardless of what env var name the secret happens to use. Both statements can be true simultaneously.
- **Workspace-scoping evidence strength**: the workspace-blank claim comes from a community help thread (bytekeim's reply on station.railway.com), not from official Railway docs. It is consistent with both Railway's GraphQL schema and the recurrence pattern, but a primary-source citation would be stronger. Worth confirming during rotation by running the pre-save curl in Finding 3.
- **No-expiration tokens**: Railway's public docs still do not formally document a hard upper bound on "No expiration" tokens. Whether the recurrence pattern reflects an undocumented cap, repeated workspace-scoping mistakes, or both cannot be determined from public sources.
- **OIDC roadmap**: no public Railway statement on OIDC federation plans. No change since prior research.

---

## Recommendations

For the human handling this incident (agents must not rotate per `CLAUDE.md`):

1. **At https://railway.com/account/tokens, create a token with**:
   - Name: descriptive (e.g. `github-actions-2026-05`)
   - **Expiration**: `No expiration`
   - **Workspace**: *leave blank* — explicitly clear any default selection so the token is account-scoped, not workspace-scoped. This is the most likely cause of the 33-cycle recurrence.
2. **Verify the token before storing it**: run the curl in Finding 3 and confirm a non-null `data.me.id` is returned. If the result is `null` or an error, the token is wrong-class (project) or wrong-scope (workspace) — discard and recreate.
3. **Push to GitHub**: `gh secret set RAILWAY_TOKEN --repo alexsiri7/reli`.
4. **Re-run the failed pipeline**: `gh run rerun 25201008471 --repo alexsiri7/reli --failed`. If the run is too old to rerun, push a no-op commit to `main`.
5. **Close issues #832, #833, and #836** once `Validate Railway secrets` passes and `Deploy to production` reaches Railway.
6. **Do not** create a `.github/RAILWAY_TOKEN_ROTATION_833.md` "completion" file — `CLAUDE.md` flags this as a Category 1 error because the underlying action cannot be performed by agents. The investigation/web-research artifacts under `artifacts/runs/<workflow-id>/` are the correct place for documentation.

Out-of-scope follow-ups (already mailed to mayor in prior cycles, do **not** re-mail):
- Replace `{me{id}}` validator with a workspace-and-project-tolerant probe so token-class mistakes fail loudly with class-specific guidance.
- Add a scheduled (e.g. weekly) validation cron that runs only the secrets validator and opens an issue on failure — catches expiry before the next deploy.
- Open a Railway feature request for GitHub OIDC federation.
- Migration off Railway tracked separately in [#629](https://github.com/alexsiri7/reli/issues/629).

---

## Sources

| # | Source | URL | Relevance |
|---|--------|-----|-----------|
| 1 | Repo workflow file | `.github/workflows/staging-pipeline.yml:49-58` (in repo) | Authoritative — the validator code that defines what counts as a valid token |
| 2 | Repo runbook | [`docs/RAILWAY_TOKEN_ROTATION_742.md`](https://github.com/alexsiri7/reli/blob/main/docs/RAILWAY_TOKEN_ROTATION_742.md) | Step-by-step rotation procedure tailored to Reli |
| 3 | Railway Help — RAILWAY_TOKEN invalid or expired | https://station.railway.com/questions/railway-token-invalid-or-expired-59011e20 | Workspace-blank requirement for account-scoped tokens; project-vs-account confusion |
| 4 | Railway Help — Token for GitHub Action | https://station.railway.com/questions/token-for-git-hub-action-53342720 | CI guidance: `RAILWAY_TOKEN` (project) vs `RAILWAY_API_TOKEN` (account/workspace) for the Railway CLI |
| 5 | Railway Help — RAILWAY_API_TOKEN not being respected | https://station.railway.com/questions/railway-api-token-not-being-respected-364b3135 | `RAILWAY_TOKEN` precedence over `RAILWAY_API_TOKEN` when both set |
| 6 | Railway Public API docs | https://docs.railway.com/integrations/api | Token classes and required headers (`Authorization: Bearer` vs `Project-Access-Token`) |
| 7 | Railway Login & Tokens docs | https://docs.railway.com/integrations/oauth/login-and-tokens | OAuth-for-third-party-apps (orthogonal to `RAILWAY_TOKEN`) |
| 8 | Railway blog — Incident Report Jan 28–29 2026 | https://blog.railway.com/p/incident-report-january-26-2026 | Confirms recent incident is unrelated to `RAILWAY_TOKEN` |
| 9 | GitHub Docs — Configuring OIDC in cloud providers | https://docs.github.com/actions/deployment/security-hardening-your-deployments/configuring-openid-connect-in-cloud-providers | Railway not among OIDC-supported providers |
| 10 | GitHub Docs — OpenID Connect | https://docs.github.com/en/actions/concepts/security/openid-connect | Reference for the OIDC-federation alternative to static tokens |
| 11 | securebin.ai — API Key Rotation Best Practices | https://securebin.ai/blog/api-key-rotation-best-practices/ | Pre-save verification and dual-secret-rotation patterns |
| 12 | Prior re-fire web research | `artifacts/runs/09146632082d189318409846f65d7fd6/web-research.md` (merged via [PR #834](https://github.com/alexsiri7/reli/pull/834)) | Background on token classes, TTL, OIDC, rotation hygiene |
