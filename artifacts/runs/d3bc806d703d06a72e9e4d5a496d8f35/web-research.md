# Web Research: fix #774

**Researched**: 2026-04-30T08:02:33Z
**Workflow ID**: d3bc806d703d06a72e9e4d5a496d8f35
**Issue**: alexsiri7/reli#774 — "Prod deploy failed on main" — staging-pipeline workflow's `Validate Railway secrets` step exits with `RAILWAY_TOKEN is invalid or expired: Not Authorized`. This is the **11th recurrence** in the series tracked by `pipeline-health-cron.sh` (preceding incidents: #733, #739, #742, #751, #762, #766, #771, etc.).

---

## Summary

The recurring failure is not a CI bug — it's the `RAILWAY_TOKEN` GitHub Actions secret repeatedly going invalid. Research surfaced three distinct root-cause angles that all match the symptom and that prior runbooks have not fully ruled out: (1) Railway's docs do not document an indefinite TTL for any token type, and account/workspace tokens commonly carry a server-side expiry that the dashboard does not warn about; (2) the `me { id }` validation query the workflow runs **only succeeds for an account-scoped (personal) token**, so a token generated under the wrong workspace context will fail the same way an expired one does; (3) the workflow validates against `https://backboard.railway.app/graphql/v2`, while community reports indicate `https://backboard.railway.com/graphql/v2` is the authoritative endpoint and `.app` returns `Not Authorized`. Issue #774 likely reflects (1) again, but (2) and (3) are worth verifying because they would reproduce the same `Not Authorized` text without an actual expiry.

---

## Findings

### 1. Railway token types and what `me { id }` requires

**Source**: [Public API | Railway Docs](https://docs.railway.com/integrations/api)
**Authority**: Official Railway documentation
**Relevant to**: Why the validation step fails even with newly minted tokens

**Key Information**:

- Four token types exist: **Account Token** (broadest scope, "All your resources and workspaces"), **Workspace Token** ("Single workspace", "Best For: Team CI/CD, shared automation"), **Project Token** ("Single environment in a project", "Deployments, service-specific automation"), and **OAuth**.
- Account & Workspace tokens are generated from `https://railway.com/account/tokens`. To get a true *account* token (not workspace-scoped), the workspace dropdown must be left at **"No workspace"**.
- Project tokens are generated from a different page — inside Project → Settings → Tokens.
- Crucially, the `RAILWAY_TOKEN` env var and `RAILWAY_API_TOKEN` env var have *different* expected token types: `RAILWAY_TOKEN` for project-level actions, `RAILWAY_API_TOKEN` for account-level actions ([CLI guide](https://docs.railway.com/guides/cli)).

---

### 2. The `{ me { id } }` query rejects project & misconfigured workspace tokens

**Source**: [API Token "Not Authorized" Error for Public API and MCP — Railway Help Station](https://station.railway.com/questions/api-token-not-authorized-error-for-pub-82b4ccf1)
**Authority**: Railway-staff-answered support thread
**Relevant to**: Direct reproduction of `Not Authorized` from a non-expired token

**Key Information**:

- > "From the dashboard home, click your user banner at the very BOTTOM of the navigation sidebar. Click the 3 dots and then 'Account Settings'" then navigate to Tokens. Critically, when creating the token, users should leave the workspace field as "No workspace" rather than assigning it to a specific workspace.
- A token created from a *project* or *team/workspace* context lacks the permissions that the `me`/`teams` queries require, and the API answers `Not Authorized` — visually identical to expiry.
- Cross-confirmed by [GraphQL requests returning "Not Authorized" for PAT](https://station.railway.com/questions/graph-ql-requests-returning-not-authoriz-56dacb52) and [RAILWAY_TOKEN invalid or expired](https://station.railway.com/questions/railway-token-invalid-or-expired-59011e20): "RAILWAY_TOKEN now only accepts *project token*" — i.e. environments where the CLI consumes `RAILWAY_TOKEN` won't accept account tokens, and yet the workflow's *validation* `me` query won't accept project tokens. There's a built-in trap here.

---

### 3. Token expiration is undocumented for project/account/workspace tokens

**Source**: [Login & Tokens | Railway Docs](https://docs.railway.com/integrations/oauth/login-and-tokens)
**Authority**: Official Railway documentation
**Relevant to**: Whether a true "no expiration" token even exists

**Key Information**:

- The OAuth flow has explicit TTLs: > "Access tokens expire after one hour." and > "The new refresh token has a fresh one-year lifetime from the time of issuance."
- For **project / account / workspace tokens, no TTL is documented anywhere** — `docs.railway.com/integrations/api`, `docs.railway.com/guides/cli`, and the Login & Tokens page are silent on it.
- Implication: `docs/RAILWAY_TOKEN_ROTATION_742.md` in this repo recommends "Expiration: No expiration" as a UI option. Per the public docs there is no such documented setting; if the dashboard offers it, that's good — but there is no published guarantee that such a token survives indefinitely. The 1-year refresh-token lifetime is suggestive of an industry pattern (~365 days) which would explain *some* recurrences but not an 11-incident cadence.

---

### 4. GraphQL endpoint host discrepancy (`.app` vs `.com`)

**Source**: [Public API | Railway Docs](https://docs.railway.com/integrations/api), corroborated by [Railway GraphQL API on Postman](https://www.postman.com/railway-4865/railway/documentation/adgthpg/railway-graphql-api) and several Help Station threads ([GraphQL requests returning Not Authorized](https://station.railway.com/questions/graph-ql-requests-returning-not-authoriz-56dacb52))
**Authority**: Official docs + community reports
**Relevant to**: The `Validate Railway secrets` step in `.github/workflows/staging-pipeline.yml`

**Key Information**:

- Community reports state: > "The correct API endpoint is `https://backboard.railway.com/graphql/v2`, whereas `https://backboard.railway.app/graphql/v2` is incorrect" and that `.app` returns `Not Authorized`.
- The current `.github/workflows/staging-pipeline.yml:48` calls `https://backboard.railway.app/graphql/v2`. If `.app` is being phased out / has stricter auth than `.com`, the validation could trip even for a token that the deployment step (which uses the Railway CLI binary, not the workflow's curl) accepts.
- ⚠️ Caveat: the validation step has worked in *previous* successful deploys against the same `.app` URL, so this isn't a clean cause for #774 alone. But it is a low-cost fix that removes a confound.

---

### 5. Railway's official guidance for GitHub Actions has shifted

**Source**: [Token for GitHub Action — Railway Help Station](https://station.railway.com/questions/token-for-git-hub-action-53342720)
**Authority**: Railway employee answer
**Relevant to**: Picking the right token type going forward

**Key Information**:

- > "use a Railway API token scoped to the user account, not a project token" — set as `RAILWAY_API_TOKEN`.
- The same thread contradicts the docs and the [official Railway blog "Using GitHub Actions with Railway"](https://blog.railway.com/p/github-actions), which says to use a *project* token in `RAILWAY_TOKEN`.
- The contradiction is real and current: project tokens are simpler but cannot create preview environments or be validated with `me`; account tokens are more powerful but riskier in scope.
- For reli's narrow use case (single project, single environment, deploy + URL probe), a **project token in `RAILWAY_TOKEN`** would be sufficient *if* the validation step is rewritten to use a project-scoped query (or removed in favour of letting the deploy step itself fail loudly).

---

### 6. Permanent solution direction: GitHub OIDC

**Source**: [OpenID Connect — GitHub Docs](https://docs.github.com/en/actions/concepts/security/openid-connect)
**Authority**: GitHub official
**Relevant to**: Eliminating the rotation problem entirely

**Key Information**:

- OIDC lets workflows mint short-lived cloud tokens at job time, removing the long-lived secret entirely.
- **Railway does not currently advertise OIDC / workload-identity-federation support** — searches across docs, blog, and Help Station turn up no Railway-specific OIDC integration. AWS, GCP, Azure, HCP, Databricks all support it; Railway does not.
- This is therefore a *medium-term* recommendation to file with Railway, not an immediate fix.

---

## Code Examples

The current validation block, for context:

```yaml
# From .github/workflows/staging-pipeline.yml:36-58 (current main)
- name: Validate Railway secrets
  env:
    RAILWAY_TOKEN: ${{ secrets.RAILWAY_TOKEN }}
    SERVICE_ID: ${{ secrets.RAILWAY_STAGING_SERVICE_ID }}
    ENV_ID: ${{ secrets.RAILWAY_STAGING_ENVIRONMENT_ID }}
    STAGING_URL: ${{ secrets.RAILWAY_STAGING_URL }}
  run: |
    # ...presence checks elided...
    RESP=$(curl -sf -X POST "https://backboard.railway.app/graphql/v2" \
      -H "Authorization: Bearer $RAILWAY_TOKEN" \
      -H "Content-Type: application/json" \
      -d '{"query":"{me{id}}"}')
    if ! echo "$RESP" | jq -e '.data.me.id' > /dev/null 2>&1; then
      MSG=$(echo "$RESP" | jq -r '.errors[0].message // "could not reach Railway API or token rejected"')
      echo "::error::RAILWAY_TOKEN is invalid or expired: $MSG"
      exit 1
    fi
```

A more robust validation that doesn't require `me`-class permissions (project-token-friendly):

```yaml
# Alternative: validate by querying the project the token is already scoped to.
# Replace { me { id } } with a project-scoped query, e.g. fetching the
# environment id we already have in secrets:
RESP=$(curl -sf -X POST "https://backboard.railway.com/graphql/v2" \
  -H "Authorization: Bearer $RAILWAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"query\":\"query{environment(id:\\\"$ENV_ID\\\"){id name}}\"}")
```

(Note the host change to `.com`. Verify against Railway's current API docs before merging.)

---

## Gaps and Conflicts

- **Conflict**: Railway's official blog says "use a project token" for GitHub Actions; Railway employees on Help Station say "use an account token". Both are reachable from a Google search today.
- **Gap**: No official documentation states whether project / account / workspace tokens *expire* on a fixed schedule. The 11-incident cadence in this repo is the strongest evidence we have, and even that is noisy — some past rotations may have used a TTL'd token by accident.
- **Gap**: Whether `backboard.railway.app` is deprecated, soft-deprecated, or fully equivalent to `.com` is not authoritatively documented; community reports differ.
- **Gap**: No public Railway OIDC / federated-identity flow exists at the time of writing.
- **Limitation of this research**: I could not query Railway support directly or test the two endpoints, so the `.app` vs `.com` finding is based on community reports and would benefit from a one-curl confirmation.

---

## Recommendations

1. **Short term (fixes #774):** Rotate `RAILWAY_TOKEN` per the existing runbook in `docs/RAILWAY_TOKEN_ROTATION_742.md`. Per CLAUDE.md, this is a human action — file the rotation request, do not produce a "rotation done" doc. Then re-run the failed deploy.

2. **Medium term (reduce recurrence):** Confirm the token currently in `RAILWAY_TOKEN` is an **account token created with workspace = "No workspace"** at `https://railway.com/account/tokens`, with the dashboard's "no expiration" option selected if available. Document the exact UI path used in the rotation runbook so the next rotator does not accidentally pick a TTL'd or workspace-scoped token (which both produce the same `Not Authorized` symptom as expiry).

3. **Medium term (remove the validation confound):** Switch the validation curl from `https://backboard.railway.app/graphql/v2` to `https://backboard.railway.com/graphql/v2`. Independently, replace `{ me { id } }` with a project-scoped query so the validation works regardless of whether the secret is an account or project token. This makes future failures unambiguously about the token, not about the validator.

4. **Long term (eliminate rotation entirely):** File a feature request with Railway for GitHub Actions OIDC / workload-identity support. Until then, accept that rotation is part of operating against Railway and consider adding a calendar reminder ~330 days after each rotation rather than waiting for the cron-filed issue.

5. **Do NOT:** Attempt to rotate the token from CI, write a "rotation done" markdown file, or in any way claim success on the rotation action — per CLAUDE.md "Railway Token Rotation" section, this is a Category 1 error.

---

## Sources

| # | Source | URL | Relevance |
|---|--------|-----|-----------|
| 1 | Railway Docs — Public API | https://docs.railway.com/integrations/api | Authoritative list of token types and scopes |
| 2 | Railway Docs — Login & Tokens | https://docs.railway.com/integrations/oauth/login-and-tokens | OAuth TTL details; silence on PAT TTL |
| 3 | Railway Docs — Using the CLI | https://docs.railway.com/guides/cli | RAILWAY_TOKEN vs RAILWAY_API_TOKEN |
| 4 | Railway Blog — Using GitHub Actions with Railway | https://blog.railway.com/p/github-actions | Official "use project token" guidance |
| 5 | Help Station — Token for GitHub Action | https://station.railway.com/questions/token-for-git-hub-action-53342720 | Railway staff: "use account token" (contradicts blog) |
| 6 | Help Station — RAILWAY_TOKEN invalid or expired | https://station.railway.com/questions/railway-token-invalid-or-expired-59011e20 | "RAILWAY_TOKEN now only accepts project token" |
| 7 | Help Station — API Token "Not Authorized" | https://station.railway.com/questions/api-token-not-authorized-error-for-pub-82b4ccf1 | Token-creation UX trap: workspace field must be "No workspace" |
| 8 | Help Station — GraphQL requests returning Not Authorized for PAT | https://station.railway.com/questions/graph-ql-requests-returning-not-authoriz-56dacb52 | Same `Not Authorized` text from valid-but-wrong-scope tokens |
| 9 | Postman — Railway GraphQL API | https://www.postman.com/railway-4865/railway/documentation/adgthpg/railway-graphql-api | Endpoint host reference |
| 10 | railwayapp/cli#699 | https://github.com/railwayapp/cli/issues/699 | Linux-specific CLI auth failure (not the cause here, but useful for ruling out) |
| 11 | GitHub Docs — OpenID Connect | https://docs.github.com/en/actions/concepts/security/openid-connect | OIDC mechanics for the long-term recommendation |
| 12 | docs/RAILWAY_TOKEN_ROTATION_742.md (in-repo) | n/a | Existing rotation runbook — referenced by CLAUDE.md |
