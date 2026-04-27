# Railway Secrets Configuration

## Issue

Fixed #728: Production deploy failed due to missing Railway API secrets in GitHub Actions.

## Solution

Configured all 7 required Railway secrets in GitHub Actions repository secrets:

- `RAILWAY_TOKEN` — API authentication token (OAuth, temporary)
- `RAILWAY_STAGING_SERVICE_ID` — Service identifier for staging environment
- `RAILWAY_STAGING_ENVIRONMENT_ID` — Environment identifier for staging
- `RAILWAY_STAGING_URL` — Staging deployment URL
- `RAILWAY_PRODUCTION_SERVICE_ID` — Service identifier for production
- `RAILWAY_PRODUCTION_ENVIRONMENT_ID` — Environment identifier for production
- `RAILWAY_PRODUCTION_URL` — Production deployment URL

## Verification

Pipeline run #24997271741 completed successfully after secret configuration.

## Action Items

⚠️ **RAILWAY_TOKEN must be replaced with a permanent token**

The temporary OAuth token expires at 15:07 UTC on 2026-04-27. To replace:

1. Go to https://railway.com/account/tokens
2. Create a new token named "github-actions"
3. Run: `echo "<token>" | gh secret set RAILWAY_TOKEN --repo alexsiri7/reli`

Other secrets (service IDs, environment IDs, URLs) are stable and do not expire.
