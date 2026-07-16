#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Anil Belur <askb23@gmail.com>
##############################################################################
# sync-to-docs.sh — Copy latest Playwright screenshots to docs/screenshots/
# in both the addon and (optionally) the app repo.
#
# Usage:
#   ./scripts/sync-to-docs.sh [--date YYYY-MM-DD] [--app-repo PATH]
#
# If --date is omitted, uses the most recent date folder in screenshots/.
# If --app-repo is omitted, tries ../../../ha-garmin-fitness-coach-app
# (sibling checkout).
##############################################################################

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOOL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
ADDON_ROOT="$(cd "${TOOL_DIR}/../.." && pwd)"

# Defaults
DATE=""
APP_REPO=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --date) DATE="$2"; shift 2 ;;
        --app-repo) APP_REPO="$2"; shift 2 ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

# Find latest date folder if not specified
if [[ -z "${DATE}" ]]; then
    DATE=$(find "${TOOL_DIR}/screenshots/" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' 2>/dev/null | sort -r | head -1)
    if [[ -z "${DATE}" ]]; then
        echo "ERROR: No screenshot folders found in ${TOOL_DIR}/screenshots/" >&2
        echo "Run 'npm run screenshot' first." >&2
        exit 1
    fi
fi

CAPTURE_DIR="${TOOL_DIR}/screenshots/${DATE}"
if [[ ! -d "${CAPTURE_DIR}" ]]; then
    echo "ERROR: Directory not found: ${CAPTURE_DIR}" >&2
    exit 1
fi

# These are the screenshots we publish to docs/ (desktop only, one per page)
# Map from capture filename → docs filename
declare -A DOCS_MAP=(
    ["home-desktop.png"]="home-desktop.png"
    ["training-desktop.png"]="training-desktop.png"
    ["fitness-28d-desktop.png"]="fitness-28d-desktop.png"
    ["activities-desktop.png"]="activities-desktop.png"
    ["sleep-desktop.png"]="sleep-desktop.png"
    ["trends-desktop.png"]="trends-desktop.png"
    ["hrv-desktop.png"]="hrv-desktop.png"
    ["vitals-desktop.png"]="vitals-desktop.png"
    ["insights-desktop.png"]="insights-desktop.png"
    ["coach-desktop.png"]="coach-desktop.png"
    ["validation-desktop.png"]="validation-desktop.png"
    ["stress-board-desktop.png"]="stress-board-desktop.png"
)

ADDON_DOCS="${ADDON_ROOT}/docs/screenshots"
mkdir -p "${ADDON_DOCS}"

echo "📸 Syncing screenshots from ${CAPTURE_DIR}"
echo ""

copied=0
for src_name in "${!DOCS_MAP[@]}"; do
    dst_name="${DOCS_MAP[$src_name]}"
    src_path="${CAPTURE_DIR}/${src_name}"
    if [[ -f "${src_path}" ]]; then
        cp "${src_path}" "${ADDON_DOCS}/${dst_name}"
        echo "  ✓ ${dst_name}"
        ((copied++))
    else
        echo "  ⚠ MISSING: ${src_name} (skipped)"
    fi
done

echo ""
echo "→ Addon docs: ${copied} screenshots updated in ${ADDON_DOCS}"

# Sync to app repo if available
if [[ -z "${APP_REPO}" ]]; then
    APP_REPO="${ADDON_ROOT}/../ha-garmin-fitness-coach-app"
fi

if [[ -d "${APP_REPO}/.git" ]]; then
    APP_DOCS="${APP_REPO}/docs/screenshots"
    mkdir -p "${APP_DOCS}"
    cp "${ADDON_DOCS}"/*.png "${APP_DOCS}/"
    echo "→ App repo:   ${copied} screenshots synced to ${APP_DOCS}"
    echo ""
    echo "Next steps:"
    echo "  cd ${ADDON_ROOT} && git add docs/screenshots/ && git commit -m 'docs: update screenshots'"
    echo "  cd ${APP_REPO} && git add docs/screenshots/ && git commit -m 'docs: update screenshots'"
else
    echo ""
    echo "⚠ App repo not found at ${APP_REPO}"
    echo "  Pass --app-repo /path/to/ha-garmin-fitness-coach-app to sync there too."
fi
