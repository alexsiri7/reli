# Web Research: fix #904

**Researched**: 2026-05-02T16:02:19Z
**Workflow ID**: 75b15c412e2ed710932ed11f8917d23a
**Issue**: alexsiri7/reli#904 — "Prod deploy failed on main"
**Failed run**: https://github.com/alexsiri7/reli/actions/runs/25255409159

---

## Summary

The deploy failure is yet another `RAILWAY_TOKEN is invalid or expired: Not Authorized` event (60th in the series, 20th today). Railway's GraphQL API explicitly rejected the token used by `.github/workflows/staging-pipeline.yml` at the `Validate Railway secrets` step — this is a token-level rejection, not a network or endpoint failure. Per `CLAUDE.md`, agents cannot rotate the token; the fix requires a human to log into railway.com and rotate `RAILWAY_TOKEN`. Research into Railway's token system surfaced two systemic issues that may explain why this keeps recurring: (1) tokens must be created with **No workspace selected** (account-scoped) for the `{me{id}}` validation query to succeed, and (2) the workflow uses the legacy `backboard.railway.app` host rather than the documented `backboard.railway.com` host (currently still works but is not the published endpoint).

---

## Findings

### 1. Failure mode is a confirmed token rejection (not endpoint/transport)

**Source**: [Failed run logs — alexsiri7/reli #25255409159](https://github.com/alexsiri7/reli/actions/runs/25255409159)
**Authority**: First-party CI output for the failing deploy at SHA `86aca5cf`
**Relevant to**: Root-cause classification

**Key Information**:

- The validation step performs `POST https://backboard.railway.app/graphql/v2` with body `{"query":"{me{id}}"}` and `Authorization: Bearer $RAILWAY_TOKEN`.
- Railway returned a **GraphQL response** with `errors[0].message = "Not Authorized"` — the request reached Railway, was parsed, and was explicitly rejected at the auth layer. This rules out DNS, TLS, and endpoint-availability issues for this incident.
- Workflow log lines `2026-05-02T15:34:37.3162996Z ##[error]RAILWAY_TOKEN is invalid or expired: Not Authorized`.

---

### 2. Railway's official GraphQL endpoint is `backboard.railway.com`, not `backboard.railway.app`

**Source**: [Public API | Railway Docs](https://docs.railway.com/integrations/api)
**Authority**: Official Railway documentation
**Relevant to**: Latent risk — explains why future Railway changes could break the pipeline silently

**Key Information**:

- Documentation states the API endpoint is `https://backboard.railway.com/graphql/v2`.
- Project tokens use the `Project-Access-Token` header; account/workspace/OAuth tokens use `Authorization: Bearer`.
- The Reli workflow consistently uses `https://backboard.railway.app/graphql/v2`. This still resolves and returns valid GraphQL responses today (evidenced by the parsed error in finding #1), so it is **not** the cause of the current failure — but it is undocumented behavior and could be deprecated without notice.

---

### 3. "Not Authorized" with a fresh token usually means the wrong token scope was created

**Source**: [API Token "Not Authorized" Error for Public API and MCP — Railway Help Station](https://station.railway.com/questions/api-token-not-authorized-error-for-pub-82b4ccf1)
**Authority**: Railway's official community forum; resolution provided by another community member with the same problem
**Relevant to**: Why rotations may "succeed" but immediately fail again

**Key Information**:

- Multiple users (`noobginger`, `chalumurigirish`, `arthurojohn`) reported tokens being rejected with `Not Authorized` immediately after creation, even as workspace owners with correct headers and endpoint.
- Resolution from `toxzak-svg`: the token must be created via **Account Settings → Tokens** with **"No workspace" selected**. Tokens created with a workspace selected are workspace-scoped and **cannot answer the `{me{id}}` query** that the Reli validation step uses — they fail with `Not Authorized` against the `Authorization: Bearer` flow.
- This is the most likely systemic cause for the recurring "expirations" in this repo if any prior rotation forgot the "No workspace" toggle.

---

### 4. Account tokens have no documented expiration; OAuth/refresh tokens do

**Source**: [Login & Tokens | Railway Docs](https://docs.railway.com/integrations/oauth/login-and-tokens)
**Authority**: Official Railway docs
**Relevant to**: Whether "expiration" is even the right framing

**Key Information**:

- OAuth **access tokens** expire after one hour; **refresh tokens** rotate and have a one-year lifetime from issuance.
- The docs page does **not** specify an expiration policy for **Account tokens** or **Project tokens** — they are presented as long-lived static credentials, configurable via the dashboard.
- Implication: If the Reli `RAILWAY_TOKEN` is an account token, it should not "expire" on a fixed schedule. Recurring failures point to either (a) revocation, (b) wrong scope at creation time (finding #3), or (c) a TTL that was set explicitly when the token was created.

---

### 5. Token TTL is selectable at creation time and defaults can be short

**Source**: [`docs/RAILWAY_TOKEN_ROTATION_742.md`](../../docs/RAILWAY_TOKEN_ROTATION_742.md) (in-repo runbook authored after issue #742)
**Authority**: Internal runbook from a prior rotation incident
**Relevant to**: How to make the next rotation stick

**Key Information** (direct quote):

> "When creating tokens on Railway, the default TTL may be short (e.g., 1 day or 7 days). Previous rotations may have used these defaults. **The new token must be created with 'No expiration'.**"

- Combined with finding #3, this gives the rotator a two-item checklist: **No workspace** AND **No expiration** at creation time.

---

### 6. Refresh-token quota: 100 per user, oldest auto-revoked

**Source**: [Login & Tokens | Railway Docs](https://docs.railway.com/integrations/oauth/login-and-tokens)
**Authority**: Official Railway docs
**Relevant to**: Speculative — secondary cause if the rotation loop has been very long-running

**Key Information**:

- "Each user authorization can have a maximum of 100 refresh tokens. If you exceed this limit, the oldest tokens are revoked automatically."
- This is explicitly for OAuth refresh tokens, not account tokens, so it likely does not apply here. Worth noting only because the Reli repo is on its 60th rotation event — if the project ever migrated to OAuth, this quota would become a concern.

---

### 7. GitHub Actions setup pattern matches Reli's workflow

**Source**: [Using Github Actions with Railway — Railway Blog](https://blog.railway.com/p/github-actions)
**Authority**: Railway's official blog
**Relevant to**: Confirms the secret name `RAILWAY_TOKEN` and Bearer header are correct for the chosen token type

**Key Information**:

- The blog confirms `RAILWAY_TOKEN` is the canonical env var for Railway-issued project tokens; `RAILWAY_API_TOKEN` is the alternative for account tokens. If both are set, `RAILWAY_TOKEN` takes precedence.
- For the validation query `{me{id}}` to succeed, the token must be account-scoped — i.e., the secret should hold an account token, even though the var is named `RAILWAY_TOKEN`. This naming mismatch is a known footgun.

---

## Code Examples

The current Reli validation step (`.github/workflows/staging-pipeline.yml:49-58`) uses an account-token query against the `.app` host:

```yaml
# From .github/workflows/staging-pipeline.yml
RESP=$(curl -sf -X POST "https://backboard.railway.app/graphql/v2" \
  -H "Authorization: Bearer $RAILWAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query":"{me{id}}"}')
```

Railway's documented equivalent ([Public API docs](https://docs.railway.com/integrations/api)):

```bash
# From https://docs.railway.com/integrations/api
curl --request POST \
  --url https://backboard.railway.com/graphql/v2 \
  --header 'Authorization: Bearer <API_TOKEN_GOES_HERE>' \
  --header 'Content-Type: application/json' \
  --data '{"query":"query { me { name email } }"}'
```

For project tokens, the header changes (Reli does **not** use this pattern):

```bash
# From https://docs.railway.com/integrations/api
curl --request POST \
  --url https://backboard.railway.com/graphql/v2 \
  --header 'Project-Access-Token: <PROJECT_TOKEN_GOES_HERE>' \
  --header 'Content-Type: application/json' \
  --data '{"query":"query { projectToken { projectId environmentId } }"}'
```

---

## Gaps and Conflicts

- **No public Railway statement** on whether account tokens silently rotate or get revoked server-side. The recurring (60×) rotation cadence in this repo is not explained by any documented Railway behavior.
- **Date currency**: The Railway docs pages do not show "last updated" timestamps; the community forum thread (finding #3) is undated in the search excerpt. Conclusions about "current behavior" are best-effort.
- **`.app` vs `.com` host**: No public deprecation notice was found for `backboard.railway.app`, but no docs page references it either. We cannot tell from research alone whether the two hosts are aliased or whether `.app` is a soft-deprecated mirror that could disappear.
- **"No expiration" availability**: I could not find an official screenshot or doc page confirming a "No expiration" option exists in the current Railway dashboard token-creation UI. The Reli runbook asserts it does; community posts neither confirm nor deny.

---

## Recommendations

These are research-derived recommendations. **The agent cannot rotate the token itself** — per `CLAUDE.md`, that requires a human at railway.com. Recommendations are for the human rotator and for follow-up cleanup work.

1. **For the current rotation (human action required)**: At railway.com → Account Settings (top-right user menu) → Tokens, create a new token with **(a) No workspace selected** AND **(b) No expiration** set. Then `gh secret set RAILWAY_TOKEN --repo alexsiri7/reli` and rerun the failed deploy. Both checkboxes matter — finding #3 explains why "No expiration" alone has not stopped the recurrence.

2. **Stop the rotation treadmill — investigate the root cause**: 60 rotations in this repo (with 20 today) is not normal token-expiration behavior; account tokens are not documented to expire on any schedule. Plausible explanations to investigate next:
   - Whether prior rotations selected a workspace at creation (finding #3) and so were never valid for `{me{id}}` from the start;
   - Whether someone or some automation is repeatedly revoking the token via the dashboard;
   - Whether the token was originally created with a TTL that was carried forward into rotated copies.

3. **Switch the validation query to the documented host**: Update `.github/workflows/staging-pipeline.yml` to use `https://backboard.railway.com/graphql/v2` (4 occurrences in that file). Today the `.app` host still works, but the official docs only reference `.com`, and Railway can drop the `.app` alias without notice. This is a low-risk hardening change separate from the token rotation.

4. **Do NOT create another `.github/RAILWAY_TOKEN_ROTATION_*.md` file**: `CLAUDE.md` flags this as a Category 1 error — it claims an action the agent cannot perform. The correct path is to file a GitHub issue (this work is being done under #904) and direct the human to `docs/RAILWAY_TOKEN_ROTATION_742.md`.

---

## Sources

| # | Source | URL | Relevance |
|---|--------|-----|-----------|
| 1 | Failed CI run logs | https://github.com/alexsiri7/reli/actions/runs/25255409159 | Confirms `Not Authorized` is a Railway-side GraphQL error, not a transport failure |
| 2 | Railway Public API docs | https://docs.railway.com/integrations/api | Authoritative endpoint, headers, and example queries |
| 3 | Railway Login & Tokens docs | https://docs.railway.com/integrations/oauth/login-and-tokens | Token types, OAuth expiration policy, refresh-token rotation, 100-token quota |
| 4 | Railway Help — "API Token Not Authorized" | https://station.railway.com/questions/api-token-not-authorized-error-for-pub-82b4ccf1 | Community thread identifying "No workspace" at token-creation as the fix for `Not Authorized` errors |
| 5 | Railway Help — "RAILWAY_TOKEN invalid or expired" | https://station.railway.com/questions/railway-token-invalid-or-expired-59011e20 | Reports of identical error message in CI contexts |
| 6 | Railway blog — GitHub Actions setup | https://blog.railway.com/p/github-actions | Canonical secret name (`RAILWAY_TOKEN`) and CI usage pattern |
| 7 | In-repo runbook | `docs/RAILWAY_TOKEN_ROTATION_742.md` | Internal procedure asserting "No expiration" must be set at creation |
| 8 | Reli `staging-pipeline.yml` | `.github/workflows/staging-pipeline.yml` | The failing workflow; uses `Authorization: Bearer` against `backboard.railway.app` |
