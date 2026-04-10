#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Local build and test script for PulseCoach HA addon
#
# Usage:
#   ./scripts/build-local.sh          # Build the addon image
#   ./scripts/build-local.sh --run    # Build and run locally
#   ./scripts/build-local.sh --clean  # Remove built images

set -euo pipefail

ADDON_DIR="$(cd "$(dirname "$0")/.." && pwd)"
APP_SOURCE="${HOME}/git/ha-garmin-fitness-coach-app"
IMAGE_NAME="ha-garmin-fitness-coach-addon-local"
ARCH="amd64"

RED='\033[0;31m'
GRN='\033[0;32m'
CYN='\033[0;36m'
RST='\033[0m'

log() { echo -e "${CYN}▸${RST} $1"; }
ok()  { echo -e "${GRN}✓${RST} $1"; }
err() { echo -e "${RED}✗${RST} $1"; }

if [ "${1:-}" = "--clean" ]; then
    log "Removing local addon image..."
    docker rmi "${IMAGE_NAME}" 2>/dev/null || true
    ok "Cleaned."
    exit 0
fi

# ─── Step 1: Copy app source into addon build context ─────────────────────────
if [ ! -d "${APP_SOURCE}" ]; then
    err "App source not found at ${APP_SOURCE}"
    exit 1
fi

log "Copying app source from ${APP_SOURCE}..."
rm -rf "${ADDON_DIR}/pulsecoach/ha-garmin-fitness-coach-app"
rsync -a --exclude=node_modules --exclude=.next --exclude=.git \
    "${APP_SOURCE}/" "${ADDON_DIR}/pulsecoach/ha-garmin-fitness-coach-app/"
ok "App source copied."

# ─── Step 2: Build the Docker image ──────────────────────────────────────────
BUILD_FROM=$(python3 -c "import json; print(json.load(open('${ADDON_DIR}/pulsecoach/build.json'))['build_from']['${ARCH}'])")

log "Building addon image (${ARCH})..."
log "  BUILD_FROM: ${BUILD_FROM}"

docker build \
    --build-arg "BUILD_FROM=${BUILD_FROM}" \
    --build-arg "BUILD_ARCH=${ARCH}" \
    -t "${IMAGE_NAME}" \
    -f "${ADDON_DIR}/pulsecoach/Dockerfile" \
    "${ADDON_DIR}/pulsecoach"

ok "Image built: ${IMAGE_NAME}"

# ─── Cleanup build context ───────────────────────────────────────────────────
rm -rf "${ADDON_DIR}/pulsecoach/ha-garmin-fitness-coach-app"
ok "Cleaned up build context."

# ─── Step 3: Optionally run it ────────────────────────────────────────────────
if [ "${1:-}" = "--run" ]; then
    log "Starting addon container on port 3100..."
    mkdir -p "${ADDON_DIR}/.local-data"

    docker run --rm -it \
        --name ha-garmin-fitness-coach-addon-test \
        -p 3100:3000 \
        -v "${ADDON_DIR}/.local-data:/data" \
        -e "SUPERVISOR_TOKEN=" \
        -e "AI_BACKEND=none" \
        -e "GARMIN_EMAIL=" \
        -e "GARMIN_PASSWORD=" \
        -e "DATABASE_URL=file:/data/pulsecoach.db" \
        -e "NODE_ENV=production" \
        -e "AUTH_SECRET=local-test-secret" \
        -e "AUTH_DISCORD_ID=unused" \
        -e "AUTH_DISCORD_SECRET=unused" \
        -e "DEV_BYPASS_AUTH=true" \
        "${IMAGE_NAME}"
fi

echo ""
log "Image size:"
docker images "${IMAGE_NAME}" --format "  {{.Size}}"
echo ""
ok "Done! To test: ./scripts/build-local.sh --run → http://localhost:3100"
