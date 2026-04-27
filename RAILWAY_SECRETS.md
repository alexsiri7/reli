# Railway Secrets Configuration

## ⚠️ IMMEDIATE ACTION REQUIRED — Token Rotation

**The current `RAILWAY_TOKEN` is a temporary OAuth token that expires at 15:07 UTC on 2026-04-27.**
Deploys after that deadline will fail with "Not Authorized". Rotate before merging this PR:

1. Go to https://railway.com/account/tokens
2. Create a new permanent token named "github-actions"
3. Run: `gh secret set RAILWAY_TOKEN --repo alexsiri7/reli`
   (gh will prompt you to paste the token — it will not appear in shell history)

Once rotated, remove this section and update the token entry below to "permanent token, no expiry".

---

## Issue

Fixed #728: Production deploy failed due to missing Railway API secrets in GitHub Actions.

## Solution

Configured all 7 required Railway secrets in GitHub Actions repository secrets:

- `RAILWAY_TOKEN` — API authentication token (OAuth, temporary — see rotation notice above)
- `RAILWAY_STAGING_SERVICE_ID` — Service identifier for staging environment
- `RAILWAY_STAGING_ENVIRONMENT_ID` — Environment identifier for staging
- `RAILWAY_STAGING_URL` — Staging deployment URL
- `RAILWAY_PRODUCTION_SERVICE_ID` — Service identifier for production
- `RAILWAY_PRODUCTION_ENVIRONMENT_ID` — Environment identifier for production
- `RAILWAY_PRODUCTION_URL` — Production deployment URL

## Verification

Verified: 2026-04-27. Pipeline completed successfully after secret configuration.

Other secrets (service IDs, environment IDs, URLs) are stable and do not expire.
