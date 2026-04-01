# Rollback Procedure

## How Versioning Works

Every deploy tags the Docker image with the git commit SHA and pushes it to
`ghcr.io/alexsiri7/reli:<sha>`. The last 3 deployed versions are tracked in
`data/deploy-versions.txt` on the server (one SHA per line, newest first).

Old image versions are automatically cleaned up by the CI `cleanup` job, which
retains the 3 most recent versions in GHCR.

## Automatic Rollback

If a deploy fails the health check, the CI pipeline automatically rolls back to
the previous version using the SHA from `deploy-versions.txt`.

## Manual Rollback

To roll back to a specific version on the server:

```bash
ssh <deploy-host>
cd /home/asiri/gt/reli/mayor/rig

# Check available versions
cat data/deploy-versions.txt

# Roll back to a specific SHA
IMAGE="ghcr.io/alexsiri7/reli"
TARGET_SHA="<sha-from-versions-file>"
docker pull "$IMAGE:$TARGET_SHA"
RELI_IMAGE_TAG="$TARGET_SHA" docker compose up -d

# Verify health
curl -sf http://localhost:8000/healthz
```

## Finding Available Versions

### From the server

```bash
cat /home/asiri/gt/reli/mayor/rig/data/deploy-versions.txt
```

### From GHCR

```bash
gh api user/packages/container/reli/versions --jq '.[].metadata.container.tags[]'
```

### From git log

Every deployed commit was pushed to `master`. Find recent SHAs:

```bash
git log --oneline -5 origin/master
```
