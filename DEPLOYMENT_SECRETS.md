# Railway Deployment Secrets Configuration

This document outlines the GitHub repository secrets required for the Railway API-based deployment pipeline introduced in PR #723.

## Issue Context

GitHub issue: #725 — Prod deploy failed on main

The deployment pipeline fails because the following secrets were never configured in the GitHub repository, despite being documented as required in PR #723.

## Required Secrets

Add these secrets to GitHub (Settings → Secrets and variables → Actions). The Railway token is one per GitHub environment; the rest are repository secrets.

| Secret Name | Purpose | Where to find |
|---|---|---|
| `RAILWAY_PROJECT_TOKEN` (environment secret, in both `staging` and `production`) | Railway project token scoped to that one Railway environment | Railway dashboard → reli project → Settings → Tokens; kept in Doppler `reli/stg_ci` and `reli/prd_ci` |
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

Each deploy job runs in a GitHub environment (`staging` or `production`) that only `main` may deploy from, and reads that environment's `RAILWAY_PROJECT_TOKEN`: a Railway **project** token scoped to the matching Railway environment, sent as `Project-Access-Token`. A workflow pushed on any other branch cannot read either token (SEC-003, #1803).

If a token is expired or revoked, CI fails at "Validate Railway secrets" with `RAILWAY_PROJECT_TOKEN is invalid, expired or not scoped to this environment`, and the daily token health check opens an issue naming the environment. To rotate one:

1. Railway dashboard → reli project → Settings → Tokens → create a token for the `staging` or `production` environment.
2. Store it in Doppler: `doppler secrets set RAILWAY_PROJECT_TOKEN --project reli --config stg_ci` (or `prd_ci`), pasting the value at the prompt.
3. Copy it to the GitHub environment without printing it:
   `doppler secrets get RAILWAY_PROJECT_TOKEN --project reli --config stg_ci --plain | gh secret set RAILWAY_PROJECT_TOKEN --env staging --repo alexsiri7/reli`
4. Re-run the failed job: `gh run rerun <run-id> --repo alexsiri7/reli`, or `gh workflow run staging-pipeline.yml --repo alexsiri7/reli`.

## Token Health Check

A weekly GitHub Actions workflow (`.github/workflows/railway-token-health.yml`) validates the Railway token every Monday at 09:00 UTC. If the token is missing or expired, it files a GitHub issue (deduplication prevents multiple issues for the same problem). Use `workflow_dispatch` to trigger an on-demand check after a rotation.

## Workflow References

The staging-pipeline.yml workflow uses these secrets in:
- `deploy-staging` job (lines 33-37)
- `deploy-production` job (lines 123-126)
- Health check polling — staging: line 64, production: line 153
- E2E smoke tests (line 109)

See `.github/workflows/staging-pipeline.yml` for full workflow details.

## Deploy-environment variables (not GitHub Actions secrets)

These are read by the running container, not by the workflow, so they belong in the deploy
environment (Railway variables, or the host's `.env` for docker compose) rather than in
`Settings → Secrets and variables → Actions`.

| Variable | Purpose | Notes |
|---|---|---|
| `DATABASE_URL` | Postgres connection string | Required. The service refuses to start without it. The connection requires TLS (#1695). On a deploy (`RAILWAY_ENVIRONMENT_NAME` or `PRODUCTION` set) it also verifies the server (#1816): it connects with `sslmode=verify-full` against the Supabase root CA bundled at `backend/certs/supabase-root-2021-ca.crt`, so the URL must name a hostname, not an IP address, and either no `sslmode` or `verify-full` — any other mode fails the boot. A certificate that does not verify fails the boot with an error naming the bundled CA. When Supabase rotates its CA, replace that file with the certificate the Supabase dashboard serves under Database settings → SSL configuration. Off a deploy a URL with no `sslmode` connects with `sslmode=require` and one naming a mode keeps it. |
| `SECRET_KEY` | Signs the JWTs the OAuth authorization server mints for `/mcp` — the only credential `/mcp` accepts | Human-provisioned; at least 32 random bytes (`python -c "import secrets; print(secrets.token_urlsafe(48))"`). Empty — or shorter than 32 bytes (#1534) — is not a dev-mode bypass: no JWT is issued or accepted, `/mcp` answers 401 to every request, `/healthz` stays green, and a warning is logged at startup. Use a different key on each environment: a token names the deploy that minted it in `iss` and another deploy refuses it (#1697), but a key two deploys share is still one secret leaked twice. |
| `ALLOWED_EMAILS` | Google accounts allowed to sign in, comma-separated | Human-provisioned. Empty admits nobody. |
| `GOOGLE_AUTH_REDIRECT_URI` | Where Google sends the browser back after sign-in | `https://<host>/api/auth/google/callback`, and the same value authorised on the OAuth client in the Google Cloud console. Empty closes the sign-in. |
| `RELI_BASE_URL` | Issuer and base of the OAuth metadata documents | Optional; derived from `GOOGLE_AUTH_REDIRECT_URI` when empty. |
| `TRUSTED_PROXY_CIDRS` | Proxy ranges whose `X-Forwarded-For` the rate limiter believes, comma-separated | Optional and human-provisioned: the ranges in front of the container (Railway's edge, and Cloudflare's if it proxies the host). Empty trusts no header, so every caller without a credential shares one rate-limit bucket per tier — except a `POST /oauth/token` presenting a live refresh token or authorization code, which is keyed by the client that grant was issued to (#1802). A malformed entry fails the boot. |
