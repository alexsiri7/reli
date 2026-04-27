# Railway Secrets Configuration

## Issue

Fixed #728: Production deploy failed due to missing Railway API secrets in GitHub Actions.

## Solution

Configured all 7 required Railway secrets in GitHub Actions repository secrets:

- `RAILWAY_TOKEN` — API authentication token (permanent token, no expiry)
- `RAILWAY_STAGING_SERVICE_ID` — Service identifier for staging environment
- `RAILWAY_STAGING_ENVIRONMENT_ID` — Environment identifier for staging
- `RAILWAY_STAGING_URL` — Staging deployment URL
- `RAILWAY_PRODUCTION_SERVICE_ID` — Service identifier for production
- `RAILWAY_PRODUCTION_ENVIRONMENT_ID` — Environment identifier for production
- `RAILWAY_PRODUCTION_URL` — Production deployment URL

## Verification

Verified: 2026-04-27. Pipeline completed successfully after secret configuration.

Other secrets (service IDs, environment IDs, URLs) are stable and do not expire.
