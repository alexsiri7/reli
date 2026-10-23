#!/usr/bin/env bash
# deploy-railway.sh — Point a Railway service at a GHCR image, deploy it, and wait for the outcome.
# Called by: .github/workflows/staging-pipeline.yml, once per environment.
#
# Usage:
#   RAILWAY_TOKEN=… SERVICE_ID=… ENV_ID=… ./scripts/deploy-railway.sh ghcr.io/<owner>/<name>:<tag>
#   RAILWAY_TOKEN=… SERVICE_ID=… ENV_ID=… ./scripts/deploy-railway.sh ghcr.io/<owner>/<name>@sha256:<hex>
#
# #1660: Railway failed to pull an image whose index referenced a deleted manifest, the previous
# container kept answering /healthz, and the pipeline went green. So the image is checked the way
# Railway pulls it before anything is sent, and the job's verdict is the deployment's own status.
#
# #1711: a tag can be moved after it is checked, so Railway is given the digest of the manifest
# that was checked, never the tag. Under Actions the pinned reference is written to $GITHUB_OUTPUT
# as `image`, so production deploys exactly what staging did.
set -euo pipefail

POLL_INTERVAL=${RAILWAY_POLL_INTERVAL:-10}
POLL_ATTEMPTS=${RAILWAY_POLL_ATTEMPTS:-90}
RAILWAY_API="https://backboard.railway.app/graphql/v2"
MANIFEST_TYPES="application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json, application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json"

image=${1:-}
if [ -z "$image" ] || [ -z "${RAILWAY_TOKEN:-}" ] || [ -z "${SERVICE_ID:-}" ] || [ -z "${ENV_ID:-}" ]; then
    echo "::error::usage: RAILWAY_TOKEN=… SERVICE_ID=… ENV_ID=… $0 ghcr.io/<owner>/<name>:<tag>|@sha256:<hex>"
    exit 2
fi
repo=${image#ghcr.io/}
case "$repo" in
    "$image") ref="" ;;
    *@sha256:*) ref=${repo#*@} repo=${repo%@*} ;;
    *:*) ref=${repo##*:} repo=${repo%:*} ;;
    *) ref="" ;;
esac
if [ -z "$ref" ]; then
    echo "::error::$image is not a tagged or digest-pinned ghcr.io image"
    exit 2
fi
manifest=$(mktemp)
trap 'rm -f "$manifest"' EXIT

# Anonymous, because that is how Railway pulls a public package: what passes here is what it sees.
check_image() {
    local token digest count=1
    token=$(curl -sf "https://ghcr.io/token?scope=repository:${repo}:pull" | jq -r .token)
    if ! curl -sf -o "$manifest" -H "Authorization: Bearer $token" -H "Accept: $MANIFEST_TYPES" \
        "https://ghcr.io/v2/${repo}/manifests/${ref}"; then
        echo "::error::Image ${image} does not exist in GHCR — refusing to deploy"
        exit 1
    fi
    digest="sha256:$(sha256sum "$manifest" | cut -d' ' -f1)"
    if [ "${ref#sha256:}" != "$ref" ] && [ "$digest" != "$ref" ]; then
        echo "::error::GHCR served ${digest} for ${image} — refusing to deploy"
        exit 1
    fi
    pinned="ghcr.io/${repo}@${digest}"
    for digest in $(jq -r '.manifests[]?.digest' "$manifest"); do
        if ! curl -sf -o /dev/null -H "Authorization: Bearer $token" -H "Accept: $MANIFEST_TYPES" \
            "https://ghcr.io/v2/${repo}/manifests/${digest}"; then
            echo "::error::Image ${image} cannot be pulled: its index references ${digest}, which GHCR no longer holds — refusing to deploy"
            exit 1
        fi
        count=$((count + 1))
    done
    echo "Image ${image} is pullable as ${pinned} (${count} manifests checked)"
}

railway() {
    curl -sf -X POST "$RAILWAY_API" \
        -H "Authorization: Bearer $RAILWAY_TOKEN" \
        -H "Content-Type: application/json" \
        -d "$1"
}

fail_on_errors() {
    echo "$1" | jq -e 'if .errors then error("Railway API error: \(.errors[0].message)") else . end'
}

check_image
if [ -n "${GITHUB_OUTPUT:-}" ]; then
    echo "image=$pinned" >> "$GITHUB_OUTPUT"
fi

echo "Deploying $pinned to Railway..."
RESP=$(railway "$(jq -n --arg svc "$SERVICE_ID" --arg env "$ENV_ID" --arg img "$pinned" \
    '{query: "mutation($svc:String!,$env:String!,$img:String!){serviceInstanceUpdate(input:{source:{image:$img}},serviceId:$svc,environmentId:$env)}",
      variables:{svc:$svc,env:$env,img:$img}}')")
echo "serviceInstanceUpdate response: $RESP"
fail_on_errors "$RESP"

RESP=$(railway "$(jq -n --arg svc "$SERVICE_ID" --arg env "$ENV_ID" \
    '{query: "mutation($svc:String!,$env:String!){serviceInstanceDeployV2(serviceId:$svc,environmentId:$env)}",
      variables:{svc:$svc,env:$env}}')")
echo "serviceInstanceDeployV2 response: $RESP"
fail_on_errors "$RESP"
DEPLOYMENT_ID=$(echo "$RESP" | jq -r '.data.serviceInstanceDeployV2 // empty')
if [ -z "$DEPLOYMENT_ID" ]; then
    echo "::error::Railway returned no deployment id"
    exit 1
fi
echo "Railway deployment $DEPLOYMENT_ID created"

STATUS_QUERY=$(jq -n --arg id "$DEPLOYMENT_ID" \
    '{query: "query($id:String!){deployment(id:$id){status}}", variables:{id:$id}}')
for i in $(seq 1 "$POLL_ATTEMPTS"); do
    # One failed poll is an API blip, not a verdict: keep waiting rather than fail the job.
    status=$(railway "$STATUS_QUERY" 2>/dev/null | jq -r '.data.deployment.status // empty' 2>/dev/null || true)
    echo "Attempt $i/$POLL_ATTEMPTS: ${status:-no status}"
    case "$status" in
        SUCCESS | SLEEPING)
            echo "Railway deployment $DEPLOYMENT_ID is live"
            exit 0
            ;;
        FAILED | CRASHED | REMOVED | REMOVING | SKIPPED | NEEDS_APPROVAL)
            echo "::error::Railway deployment $DEPLOYMENT_ID ended $status — the previous deployment is still serving; see the Railway dashboard for its logs"
            exit 1
            ;;
    esac
    sleep "$POLL_INTERVAL"
done
echo "::error::Railway deployment $DEPLOYMENT_ID did not finish within $((POLL_ATTEMPTS * POLL_INTERVAL))s"
exit 1
