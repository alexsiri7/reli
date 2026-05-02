# Web Research: fix #891

**Researched**: 2026-05-02T10:30:00Z
**Workflow ID**: 606f720ddc2c93cdc49cc98e87e5c9c8
**Issue**: [Prod deploy failed on main #891](https://github.com/alexsiri7/reli/issues/891)

---

## Summary

Issue #891 is the **55th occurrence** of the recurring `RAILWAY_TOKEN is invalid or expired: Not Authorized` failure (15th today alone). Per `CLAUDE.md` policy, agents cannot rotate Railway API tokens — only a human with railway.com access can. Web research confirms: the root cause is almost certainly that successive token rotations have used Railway's default short TTL instead of "No expiration"; Railway's own docs explicitly recommend using a long-lived account/workspace token for GitHub Actions, and the existing runbook `docs/RAILWAY_TOKEN_ROTATION_742.md` already prescribes the correct fix.

---

## Findings

### 1. Railway token types and scopes

**Source**: [Railway Docs — Public API](https://docs.railway.com/integrations/api), [Railway Help Station — Token for GitHub Action](https://station.railway.com/questions/token-for-git-hub-action-53342720)
**Authority**: Official Railway documentation and Railway employee guidance
**Relevant to**: Determining which kind of token should be in the `RAILWAY_TOKEN` GitHub secret

**Key information**:
- Railway has three token types: **account token**, **workspace token**, and **project token**.
- **Project tokens** are scoped to a single environment, perform deployment-only actions, and use the `Project-Access-Token` HTTP header.
- **Account/workspace tokens** are broader-scope and use the standard `Authorization: Bearer` header.
- For GitHub Actions, Railway employees recommend an **account-scoped token** stored as `RAILWAY_API_TOKEN`. Project tokens (`RAILWAY_TOKEN`) work only for narrow "deploy this project" CLI calls.
- If both env vars are set, `RAILWAY_TOKEN` takes precedence.

**Implication for this repo**: `.github/workflows/staging-pipeline.yml` validates the token with `curl -H "Authorization: ***"` against `backboard.railway.app/graphql/v2`. That request style works for account/workspace tokens, not project tokens. Whatever is currently stored as the `RAILWAY_TOKEN` secret is therefore a **non-project token misnamed as `RAILWAY_TOKEN`**. This is allowed but means the standard "project token" expiration rules don't apply.

---

### 2. Token expiration policies

**Source**: [Railway Docs — Login & Tokens](https://docs.railway.com/integrations/oauth/login-and-tokens)
**Authority**: Official Railway OAuth documentation
**Relevant to**: Why the token keeps expiring every few hours

**Key information**:
- OAuth access tokens expire after **1 hour**.
- Refresh tokens get a **1-year lifetime** on issuance and are rotated on every use.
- The OAuth doc does not document a "no expiration" setting, but the dashboard token-creation UI offers TTL choices.
- The existing runbook `docs/RAILWAY_TOKEN_ROTATION_742.md` (line 20–21) states: *"When creating tokens on Railway, the default TTL may be short (e.g., 1 day or 7 days). Previous rotations may have used these defaults. The new token must be created with 'No expiration'."*

**Implication**: The 55-rotation pattern is consistent with humans repeatedly accepting the default short TTL (1 day or 7 days) when rotating in the dashboard. The rotation runbook *already* identifies the fix; it just is not being applied.

---

### 3. CLI environment variable naming gotcha

**Source**: [Railway Help Station — RAILWAY_API_TOKEN not being respected](https://station.railway.com/questions/railway-api-token-not-being-respected-364b3135), [railwayapp/cli#668](https://github.com/railwayapp/cli/issues/105)
**Authority**: Railway community + CLI maintainer responses
**Relevant to**: Whether to migrate the secret to `RAILWAY_API_TOKEN`

**Key information**:
- Older Railway CLI versions did not respect `RAILWAY_API_TOKEN`; this was fixed in a later release (PR #668 referenced in community thread).
- Account/team tokens belong in `RAILWAY_API_TOKEN`. Project tokens belong in `RAILWAY_TOKEN`.
- Mixing them silently fails with "Unauthorized" / "Not Authorized" responses identical to the one in this issue.

---

### 4. Recent Railway-side incidents (rule out provider outage)

**Source**: [Railway Incident Report: January 28–29, 2026](https://blog.railway.com/p/incident-report-january-26-2026)
**Authority**: Official Railway blog
**Relevant to**: Confirming the failure is local (token), not a Railway-side outage

**Key information**:
- Most recent reported Railway auth incident was Jan 28–29, 2026 — 3+ months before this failure.
- That incident affected GitHub OAuth login and "GitHub repo not found" errors, not GraphQL token validation.
- No active Railway incident matches the symptoms or timing of issue #891.

**Conclusion**: The failure is not on Railway's side; it is a stale local token.

---

## Code Examples

The validation step that is failing (extracted from the CI log):

```bash
# From .github/workflows/staging-pipeline.yml — Validate Railway secrets
RESP=$(curl -sf -X POST "https://backboard.railway.app/graphql/v2" \
  -H "Authorization: ***" \
  -H "Content-Type: application/json" \
  -d '{"query":"{me{id}}"}')
if ! echo "$RESP" | jq -e '.data.me.id' > /dev/null 2>&1; then
  MSG=$(echo "$RESP" | jq -r '.errors[0].message // "could not reach Railway API or token rejected"')
  echo "::error::RAILWAY_TOKEN is invalid or expired: $MSG"
  exit 1
fi
```

Recommended rotation command (from the existing runbook):

```bash
# After creating a NEW token at https://railway.com/account/tokens
# with Expiration: "No expiration"
gh secret set RAILWAY_TOKEN --repo alexsiri7/reli
# Paste the new token when prompted

# Rerun the failed CI:
gh run list --repo alexsiri7/reli --status failure --limit 1 \
  --json databaseId --jq '.[0].databaseId' \
  | xargs -I{} gh run rerun {} --repo alexsiri7/reli --failed
```

---

## Gaps and Conflicts

- **Gap**: Railway's public docs do not document the "No expiration" option in the dashboard token-creation UI. The runbook's instruction relies on that option being available; the only way to verify is to log into railway.com — which agents cannot do.
- **Gap**: No public Railway changelog entry was found explaining whether the dashboard ever silently changed default token TTLs. If the option was removed or renamed, the runbook would be wrong.
- **Conflict**: Railway docs use `RAILWAY_TOKEN` for "project-level actions" and `RAILWAY_API_TOKEN` for "account-level actions", but the workflow stores what is functionally an account/workspace token under `RAILWAY_TOKEN`. This works (because `RAILWAY_TOKEN` takes precedence and the validation uses the right header for account tokens) but is non-idiomatic and may be the source of confusion during rotations.
- **Cannot verify from outside**: Whether the most recent rotations actually selected "No expiration" but the token was revoked/rotated by another mechanism (e.g., dashboard UI change, workspace permission changes, inactivity revocation).

---

## Recommendations

1. **Immediate (human action required)**: A human must rotate the token per `docs/RAILWAY_TOKEN_ROTATION_742.md`. The agent has filed/will file the standard "human-required" mail to mayor as required by `CLAUDE.md`. **Do not** create a `.github/RAILWAY_TOKEN_ROTATION_*.md` file — `CLAUDE.md` flags that as a Category 1 error.
2. **Strict adherence to "No expiration"**: When the human rotates, they MUST select "No expiration" in the railway.com dashboard. The 55-rotation history strongly suggests this step is being skipped. If "No expiration" is not available in the UI, escalate to Railway support — short-TTL tokens are not viable for unattended CI.
3. **Long-term hardening (out of scope for this issue)**: Consider renaming the secret from `RAILWAY_TOKEN` to `RAILWAY_API_TOKEN` to match Railway's documented convention for account-scoped tokens, and update the workflow accordingly. This avoids future confusion when rotating. Per Polecat Scope Discipline, this should be filed as a separate mail to mayor, not bundled into this fix.
4. **Do not** attempt to pre-validate or "refresh" the token from CI — Railway's OAuth refresh flow requires a refresh token, which is not what is stored in `RAILWAY_TOKEN`. There is no agent-side workaround.

---

## Sources

| # | Source | URL | Relevance |
|---|--------|-----|-----------|
| 1 | Railway Docs — Public API | https://docs.railway.com/integrations/api | Token type definitions (account/workspace/project) |
| 2 | Railway Docs — CLI | https://docs.railway.com/cli | `RAILWAY_TOKEN` vs `RAILWAY_API_TOKEN` env var conventions |
| 3 | Railway Docs — Using the CLI | https://docs.railway.com/guides/cli | Recommended CI/CD CLI usage pattern |
| 4 | Railway Docs — Login & Tokens | https://docs.railway.com/integrations/oauth/login-and-tokens | Token expiration policies (1h access / 1y refresh) |
| 5 | Railway Help Station — Token for GitHub Action | https://station.railway.com/questions/token-for-git-hub-action-53342720 | Employee guidance: use account-scoped token |
| 6 | Railway Help Station — Unauthorized with RAILWAY_TOKEN | https://station.railway.com/questions/cli-throwing-unauthorized-with-railway-24883ba1 | Common cause of the exact error in #891 |
| 7 | Railway Help Station — RAILWAY_API_TOKEN not respected | https://station.railway.com/questions/railway-api-token-not-being-respected-364b3135 | Older CLI bug; informs the env-var rename recommendation |
| 8 | Railway Blog — Incident Report Jan 28–29 2026 | https://blog.railway.com/p/incident-report-january-26-2026 | Rules out a current Railway-side outage |
| 9 | Railway Blog — Using GitHub Actions with Railway | https://blog.railway.com/p/github-actions | Reference architecture for the workflow |
| 10 | railwayapp/cli#105 | https://github.com/railwayapp/cli/issues/105 | History of token-handling behavior in CLI |
| 11 | Local: `docs/RAILWAY_TOKEN_ROTATION_742.md` | (in repo) | Existing rotation runbook — already prescribes the fix |
