# Railway Token Rotation — Issue #752

**Date**: 2026-04-27
**Operator**: {operator}
**Reason**: Expired RAILWAY_TOKEN in GitHub Actions secrets (recurring — 6th occurrence)

## Action Taken

Rotated `RAILWAY_TOKEN` GitHub Actions secret to a new permanent Railway API token.

### Steps Performed

1. Generated new Railway API token via https://railway.com/account/tokens
   - Token name: `github-actions`
   - Expiry: **No expiry** (permanent)
   - Deleted old `github-actions` token

2. Verified token validity before setting:
   ```bash
   curl -sf -X POST "https://backboard.railway.app/graphql/v2" \
     -H "Authorization: Bearer $NEW_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"query":"{me{id}}"}' | jq '.data.me.id'
   # Returned valid UUID
   ```

3. Updated GitHub Actions secret:
   ```bash
   gh secret set RAILWAY_TOKEN --repo alexsiri7/reli
   ```

## Preventing Recurrence

A scheduled token-health workflow (`.github/workflows/railway-token-health.yml`)
now validates the token weekly and files a GitHub issue if it expires.
