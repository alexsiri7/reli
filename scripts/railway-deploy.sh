#!/usr/bin/env bash
# railway-deploy.sh — Point a Railway service at a GHCR image, deploy it, and wait for the outcome.
#
# Usage: RAILWAY_TOKEN=… SERVICE_ID=… ENV_ID=… ./scripts/railway-deploy.sh ghcr.io/<owner>/<repo>:<tag>
#
# Fails before touching Railway when the image cannot be pulled, and fails after the deploy when
# Railway reports the deployment did not come up (#1660). Railway accepting the mutations proves
# nothing, and /healthz keeps answering from the previous container when the new one never starts.
set -Eeuo pipefail

IMAGE="$1"
: "${RAILWAY_TOKEN:?}" "${SERVICE_ID:?}" "${ENV_ID:?}"
POLL_SECONDS="${RAILWAY_POLL_SECONDS:-10}"
POLL_ATTEMPTS="${RAILWAY_POLL_ATTEMPTS:-60}"
RAILWAY_API="https://backboard.railway.app/graphql/v2"

REPOSITORY="${IMAGE#ghcr.io/}"
REPOSITORY="${REPOSITORY%:*}"
TAG="${IMAGE##*:}"
MANIFEST_TYPES="application/vnd.oci.image.index.v1+json,application/vnd.oci.image.manifest.v1+json"
MANIFEST_TYPES="$MANIFEST_TYPES,application/vnd.docker.distribution.manifest.list.v2+json"
MANIFEST_TYPES="$MANIFEST_TYPES,application/vnd.docker.distribution.manifest.v2+json"

refuse() {
    echo "::error::$1" >&2
    exit 1
}

manifest() {
    curl -sf -H "Authorization: Bearer $GHCR_TOKEN" -H "Accept: $MANIFEST_TYPES" \
        "https://ghcr.io/v2/${REPOSITORY}/manifests/$1"
}

# A tag can outlive the image it names: a multi-manifest push stores the platform image as its
# own untagged registry entry, and deleting that leaves the tag resolving to an index whose image
# is gone. Railway then fails at CREATE_CONTAINER, so every image the index points at must resolve
# too. Attestation manifests are skipped — Railway never pulls them.
require_pullable_image() {
    GHCR_TOKEN=$(curl -sf "https://ghcr.io/token?scope=repository:${REPOSITORY}:pull&service=ghcr.io" | jq -r .token) ||
        refuse "Could not get a GHCR pull token for ${REPOSITORY}"
    local top
    top=$(manifest "$TAG") || refuse "Image $IMAGE does not exist in GHCR — not deploying it."
    local digest
    for digest in $(echo "$top" | jq -r \
        '.manifests[]? | select(.annotations["vnd.docker.reference.type"] != "attestation-manifest") | .digest'); do
        manifest "$digest" > /dev/null ||
            refuse "Image $IMAGE is tagged in GHCR but its image manifest $digest is gone — not deploying it."
    done
}

railway() {
    local resp
    resp=$(curl -sf -X POST "$RAILWAY_API" \
        -H "Authorization: Bearer $RAILWAY_TOKEN" \
        -H "Content-Type: application/json" \
        -d "$1") || refuse "Railway API request failed"
    echo "$resp" | jq -e 'if .errors then error("Railway API error: \(.errors[0].message)") else . end'
}

require_pullable_image
echo "Deploying $IMAGE..."

railway "$(jq -n --arg svc "$SERVICE_ID" --arg env "$ENV_ID" --arg img "$IMAGE" \
    '{query: "mutation($svc:String!,$env:String!,$img:String!){serviceInstanceUpdate(input:{source:{image:$img}},serviceId:$svc,environmentId:$env)}",
      variables:{svc:$svc,env:$env,img:$img}}')"

DEPLOYMENT_ID=$(railway "$(jq -n --arg svc "$SERVICE_ID" --arg env "$ENV_ID" \
    '{query: "mutation($svc:String!,$env:String!){serviceInstanceDeployV2(serviceId:$svc,environmentId:$env)}",
      variables:{svc:$svc,env:$env}}')" | jq -r '.data.serviceInstanceDeployV2')
echo "Railway deployment $DEPLOYMENT_ID"

for i in $(seq 1 "$POLL_ATTEMPTS"); do
    STATUS=$(railway "$(jq -n --arg id "$DEPLOYMENT_ID" \
        '{query: "query($id:String!){deployment(id:$id){status}}", variables:{id:$id}}')" |
        jq -r '.data.deployment.status')
    echo "Attempt $i/$POLL_ATTEMPTS: $STATUS"
    case "$STATUS" in
        SUCCESS) exit 0 ;;
        FAILED | CRASHED | REMOVED | REMOVING | SKIPPED)
            refuse "Railway deployment $DEPLOYMENT_ID of $IMAGE ended $STATUS" ;;
    esac
    sleep "$POLL_SECONDS"
done
refuse "Railway deployment $DEPLOYMENT_ID of $IMAGE was still not SUCCESS after $POLL_ATTEMPTS polls"
