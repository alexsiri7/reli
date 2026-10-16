#!/usr/bin/env bash
# deploy-railway.sh — Point a Railway service at a GHCR image, deploy it, and wait for the outcome.
# Called by: .github/workflows/staging-pipeline.yml, once per environment.
#
# Usage:
#   RAILWAY_TOKEN=… SERVICE_ID=… ENV_ID=… ./scripts/deploy-railway.sh ghcr.io/<owner>/<name>:<tag>
#
# #1660: Railway failed to pull an image whose index referenced a deleted manifest, the previous
# container kept answering /healthz, and the pipeline went green. So the image is checked the way
# Railway pulls it before anything is sent, and the job's verdict is the deployment's own status.
set -euo pipefail

POLL_INTERVAL=${RAILWAY_POLL_INTERVAL:-10}
POLL_ATTEMPTS=${RAILWAY_POLL_ATTEMPTS:-90}
RAILWAY_API="https://backboard.railway.app/graphql/v2"
MANIFEST_TYPES="application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json, application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json"

image=${1:-}
if [ -z "$image" ] || [ -z "${RAILWAY_TOKEN:-}" ] || [ -z "${SERVICE_ID:-}" ] || [ -z "${ENV_ID:-}" ]; then
    echo "::error::usage: RAILWAY_TOKEN=… SERVICE_ID=… ENV_ID=… $0 ghcr.io/<owner>/<name>:<tag>"
    exit 2
fi
if [ "${image#ghcr.io/}" = "$image" ] || [ "${image##*:}" = "$image" ]; then
    echo "::error::$image is not a tagged ghcr.io image"
    exit 2
fi
repo=${image#ghcr.io/}
tag=${repo##*:}
repo=${repo%:*}

# Anonymous, because that is how Railway pulls a public package: what passes here is what it sees.
check_image() {
    local token body digest count=1
    token=$(curl -sf "https://ghcr.io/token?scope=repository:${repo}:pull" | jq -r .token)
    if ! body=$(curl -sf -H "Authorization: Bearer $token" -H "Accept: $MANIFEST_TYPES" \
        "https://ghcr.io/v2/${repo}/manifests/${tag}"); then
        echo "::error::Image ${image} does not exist in GHCR — refusing to deploy"
        exit 1
    fi
    for digest in $(echo "$body" | jq -r '.manifests[]?.digest'); do
        if ! curl -sf -o /dev/null -H "Authorization: Bearer $token" -H "Accept: $MANIFEST_TYPES" \
            "https://ghcr.io/v2/${repo}/manifests/${digest}"; then
            echo "::error::Image ${image} cannot be pulled: its index references ${digest}, which GHCR no longer holds — refusing to deploy"
            exit 1
        fi
        count=$((count + 1))
    done
    echo "Image ${image} is pullable (${count} manifests checked)"
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

echo "Deploying $image to Railway..."
RESP=$(railway "$(jq -n --arg svc "$SERVICE_ID" --arg env "$ENV_ID" --arg img "$image" \
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
