# Deployment Rollback — Issue #495

## When to Use This

Use when a production deployment is unhealthy and you need to restore the previous known-good image.

Production is deployed via Railway using the image `ghcr.io/alexsiri7/reli:<SHA>`. The last 3
SHA-tagged images are retained in GHCR. To roll back, identify the target SHA and redeploy it.

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

If the image is missing, it may have been pruned (only last 3 are retained). In that case,
re-trigger CI on the target commit to rebuild it, or use the next-oldest retained SHA.

## Step 3: Redeploy via Railway API

You need three values — find them as follows:
- `RAILWAY_TOKEN`: GitHub → Settings → Secrets → Actions → `RAILWAY_TOKEN`
- `RAILWAY_PRODUCTION_SERVICE_ID`: Railway dashboard → project → service → Settings → copy Service ID
- `RAILWAY_PRODUCTION_ENVIRONMENT_ID`: Railway dashboard → project → Environments → Production → copy Environment ID

```bash
export RAILWAY_TOKEN=<token>
export SERVICE_ID=<RAILWAY_PRODUCTION_SERVICE_ID>
export ENV_ID=<RAILWAY_PRODUCTION_ENVIRONMENT_ID>
export TARGET_SHA=<the SHA to roll back to>

IMAGE="ghcr.io/alexsiri7/reli:${TARGET_SHA}"

# Point the service at the rollback image
curl -sf -X POST "https://backboard.railway.app/graphql/v2" \
  -H "Authorization: Bearer $RAILWAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d "$(jq -n --arg svc "$SERVICE_ID" --arg env "$ENV_ID" --arg img "$IMAGE" \
    '{query: "mutation($svc:String!,$env:String!,$img:String!){serviceInstanceUpdate(input:{source:{image:$img}},serviceId:$svc,environmentId:$env)}",
      variables:{svc:$svc,env:$env,img:$img}}')"

# Trigger the deployment
curl -sf -X POST "https://backboard.railway.app/graphql/v2" \
  -H "Authorization: Bearer $RAILWAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d "$(jq -n --arg svc "$SERVICE_ID" --arg env "$ENV_ID" \
    '{query: "mutation($svc:String!,$env:String!){serviceInstanceDeploy(serviceId:$svc,environmentId:$env)}",
      variables:{svc:$svc,env:$env}}')"
```

## Step 4: Verify health

```bash
export PROD_URL=<RAILWAY_PRODUCTION_URL>
curl -f "${PROD_URL}/healthz"
# Expect: {"status":"ok",...}
```

## After Rollback

1. File a post-mortem issue describing what the bad deploy contained.
2. Fix forward in a new PR — do not leave production on an old SHA indefinitely.
3. The next successful main CI run will move `latest` forward and prune the oldest retained SHA.
