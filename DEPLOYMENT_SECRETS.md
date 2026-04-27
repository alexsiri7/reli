# Railway Deployment Secrets Configuration

This document outlines the GitHub repository secrets required for the Railway API-based deployment pipeline introduced in PR #723.

## Issue Context

GitHub issue: #725 — Prod deploy failed on main

The deployment pipeline fails because the following secrets were never configured in the GitHub repository, despite being documented as required in PR #723.

## Required Secrets

Add these 7 secrets to GitHub repository settings (Settings → Secrets and variables → Actions):

| Secret Name | Purpose | Where to find |
|---|---|---|
| `RAILWAY_TOKEN` | Authentication token for Railway API | Railway dashboard → Account Settings → Tokens |
| `RAILWAY_STAGING_SERVICE_ID` | Staging service identifier | Railway dashboard → staging project → service → Settings → Service ID |
| `RAILWAY_STAGING_ENVIRONMENT_ID` | Staging environment identifier | Railway dashboard → staging project → environment ID in URL |
| `RAILWAY_PRODUCTION_SERVICE_ID` | Production service identifier | Railway dashboard → production project → service → Settings → Service ID |
| `RAILWAY_PRODUCTION_ENVIRONMENT_ID` | Production environment identifier | Railway dashboard → production project → environment ID in URL |
| `RAILWAY_STAGING_URL` | Staging service public URL | Railway dashboard → staging service public URL (e.g. `https://reli-staging.up.railway.app`) |
| `RAILWAY_PRODUCTION_URL` | Production service public URL | Railway dashboard → production service public URL (e.g. `https://reli.up.railway.app`) |

## Setup Instructions

1. Navigate to: https://github.com/alexsiri7/reli/settings/secrets/actions
2. Click "New repository secret" for each secret above
3. Add the secret name and value from Railway dashboard
4. After all secrets are configured, re-run the failed deployment:
   ```bash
   gh workflow run staging-pipeline.yml
   ```

## Token Rotation

⚠️ If using a temporary OAuth token, replace it with a permanent token before it expires:

1. Go to https://railway.com/account/tokens
2. Create a new permanent token named "github-actions"
3. Run: `gh secret set RAILWAY_TOKEN --repo alexsiri7/reli`
   (gh will prompt you to paste the token — it will not appear in shell history)

Permanent service tokens (Railway → Settings → Tokens) do not expire.

## Workflow References

The staging-pipeline.yml workflow uses these secrets in:
- `deploy-staging` job (lines 33-37)
- `deploy-production` job (lines 123-126)
- Health check polling — staging: line 64, production: line 153
- E2E smoke tests (line 109)

See `.github/workflows/staging-pipeline.yml` for full workflow details.
