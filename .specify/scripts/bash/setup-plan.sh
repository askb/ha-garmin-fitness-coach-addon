#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Anil Belur <askb23@gmail.com>
##############################################################################
# setup-plan.sh
#
# Detects the current feature branch, finds the corresponding spec directory,
# and copies the plan template if a plan.md doesn't already exist.
# Outputs JSON with the detected context.
#
# Usage: setup-plan.sh
##############################################################################

set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

function json_output() {
    local branch="$1"
    local spec_id="$2"
    local spec_dir="$3"
    local plan_path="$4"
    local plan_status="$5"
    local message="$6"

    cat <<EOF
{
  "branch": "${branch}",
  "spec_id": "${spec_id}",
  "spec_dir": "${spec_dir}",
  "plan_path": "${plan_path}",
  "plan_status": "${plan_status}",
  "message": "${message}"
}
EOF
}

function main() {
    cd "${REPO_ROOT}"

    # Detect current branch
    local branch
    branch="$(git branch --show-current 2>/dev/null || echo "")"

    if [[ -z "$branch" ]]; then
        json_output "" "" "" "" "error" "Not on any branch (detached HEAD?)"
        exit 1
    fi

    # Extract spec ID from branch name (speckit/NNN-name → NNN-name)
    local spec_id=""
    if [[ "$branch" =~ ^speckit/(.+)$ ]]; then
        spec_id="${BASH_REMATCH[1]}"
    else
        # Try to find spec dir matching branch name fragments
        local branch_suffix="${branch##*/}"
        if [[ -d "specs/${branch_suffix}" ]]; then
            spec_id="${branch_suffix}"
        fi
    fi

    if [[ -z "$spec_id" ]]; then
        json_output "$branch" "" "" "" "error" \
            "Cannot determine spec ID from branch '${branch}'. Expected format: speckit/NNN-name"
        exit 1
    fi

    local spec_dir="specs/${spec_id}"
    local plan_path="${spec_dir}/plan.md"

    # Check if spec directory exists
    if [[ ! -d "$spec_dir" ]]; then
        json_output "$branch" "$spec_id" "$spec_dir" "$plan_path" "error" \
            "Spec directory '${spec_dir}' does not exist. Run create-new-feature.sh first."
        exit 1
    fi

    # Check if plan already exists
    if [[ -f "$plan_path" ]]; then
        json_output "$branch" "$spec_id" "$spec_dir" "$plan_path" "exists" \
            "Plan already exists at ${plan_path}"
        exit 0
    fi

    # Copy plan template
    local template=".specify/templates/plan-template.md"
    if [[ ! -f "$template" ]]; then
        json_output "$branch" "$spec_id" "$spec_dir" "$plan_path" "error" \
            "Plan template not found at ${template}"
        exit 1
    fi

    cp "$template" "$plan_path"

    json_output "$branch" "$spec_id" "$spec_dir" "$plan_path" "created" \
        "Plan template copied to ${plan_path}"
}

main "$@"
