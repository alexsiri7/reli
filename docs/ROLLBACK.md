# Deployment Rollback — Issue #495

## When to Use This

Use when a production deployment is unhealthy and you need to restore the previous known-good image.

Production is deployed via Railway using the image `ghcr.io/alexsiri7/reli:<SHA>`. CI pushes one
for every commit on `main` and deletes none of them (#1660). To roll back, identify the target SHA
and redeploy it.

## Step 1: Identify the target SHA

```bash
# List recent commits on main to find the SHA before the bad deploy
git log --format="%H %s" main | head -10
```

Or browse recent CI runs:
```bash
gh run list --repo alexsiri7/reli --branch main --limit 10
```

## Step 2: Redeploy via Railway API

You need three values — find them as follows:
- `RAILWAY_TOKEN`: GitHub → Settings → Secrets → Actions → `RAILWAY_TOKEN`
- `RAILWAY_PRODUCTION_SERVICE_ID`: Railway dashboard → project → service → Settings → copy Service ID
- `RAILWAY_PRODUCTION_ENVIRONMENT_ID`: Railway dashboard → project → Environments → Production → copy Environment ID

```bash
export RAILWAY_TOKEN=<token>
export SERVICE_ID=<RAILWAY_PRODUCTION_SERVICE_ID>
export ENV_ID=<RAILWAY_PRODUCTION_ENVIRONMENT_ID>
export TARGET_SHA=<the SHA to roll back to>
./scripts/railway-deploy.sh "ghcr.io/alexsiri7/reli:${TARGET_SHA}"
```

The script is the one the pipeline deploys with. It refuses an image GHCR cannot serve — the old
prune step left some pre-#1660 images tagged but unpullable — before changing anything on Railway,
and exits non-zero unless Railway reports the deployment `SUCCESS`.

## Step 3: Verify health

```bash
export PROD_URL=<RAILWAY_PRODUCTION_URL>
curl -f "${PROD_URL}/healthz"
# Expect: {"status":"ok",...}
```

## After Rollback

1. File a post-mortem issue describing what the bad deploy contained.
2. Fix forward in a new PR — do not leave production on an old SHA indefinitely.
3. The next successful main CI run will move `latest` forward and deploy it.
