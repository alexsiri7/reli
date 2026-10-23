# Deployment Rollback — Issue #495

## When to Use This

Use when a production deployment is unhealthy and you need to restore the previous known-good image.

Production is deployed via Railway from the image CI pushes as `ghcr.io/alexsiri7/reli:<SHA>`,
pinned to its digest (`ghcr.io/alexsiri7/reli@sha256:…`) by `scripts/deploy-railway.sh` (#1711). The
last 3 SHA-tagged images are retained in GHCR. To roll back, identify the target SHA and redeploy it.

## Step 1: Identify the target SHA

```bash
# List recent commits on main to find the SHA before the bad deploy
git log --format="%H %s" main | head -10
```

Or browse recent CI runs:
```bash
gh run list --repo alexsiri7/reli --branch main --limit 10
```

## Step 2: Verify the image exists in GHCR

```bash
# Replace <SHA> with the 40-char commit SHA
docker manifest inspect ghcr.io/alexsiri7/reli:<SHA>
```

CI no longer prunes images (#1660), but images from before that change may be gone or unpullable.
In that case, re-trigger CI on the target commit to rebuild it, or pick another SHA.

## Step 3: Redeploy through the deploy script

Run `scripts/deploy-railway.sh`, the same script the pipeline runs: it checks the image is pullable,
pins it to its digest, deploys that digest and waits for Railway's verdict. Do not call the Railway
API by hand — a tag sent to Railway can move after it was checked.

You need three values — find them as follows:
- `RAILWAY_TOKEN`: GitHub → Settings → Secrets → Actions → `RAILWAY_TOKEN`
- `RAILWAY_PRODUCTION_SERVICE_ID`: Railway dashboard → project → service → Settings → copy Service ID
- `RAILWAY_PRODUCTION_ENVIRONMENT_ID`: Railway dashboard → project → Environments → Production → copy Environment ID

```bash
export RAILWAY_TOKEN=<token>
export SERVICE_ID=<RAILWAY_PRODUCTION_SERVICE_ID>
export ENV_ID=<RAILWAY_PRODUCTION_ENVIRONMENT_ID>
export TARGET_SHA=<the SHA to roll back to>

./scripts/deploy-railway.sh "ghcr.io/alexsiri7/reli:${TARGET_SHA}"
```

The script prints the digest it deployed and exits non-zero if the image is not pullable or the
deployment does not come up; in that case the previous deployment is still serving.

## Step 4: Verify health

```bash
export PROD_URL=<RAILWAY_PRODUCTION_URL>
curl -f "${PROD_URL}/healthz"
# Expect: {"status":"ok",...}
```

## After Rollback

1. File a post-mortem issue describing what the bad deploy contained.
2. Fix forward in a new PR — do not leave production on an old SHA indefinitely.
3. The next successful main CI run will move `latest` forward and deploy it.
