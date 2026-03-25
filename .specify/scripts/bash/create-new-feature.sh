#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Anil Belur <askb23@gmail.com>
##############################################################################
# create-new-feature.sh
#
# Creates a numbered feature branch and spec directory for a new feature.
# Uses specs/NNN-name/ convention.
# Auto-detects next number from remote/local branches and specs dirs.
#
# Usage: create-new-feature.sh <feature-name-in-kebab-case>
# Example: create-new-feature.sh garmin-sync-scheduler
##############################################################################

set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

function usage() {
    echo "Usage: $(basename "$0") <feature-name>"
    echo ""
    echo "Creates a numbered speckit feature branch and spec directory."
    echo ""
    echo "Arguments:"
    echo "  feature-name    Kebab-case feature name (e.g., garmin-sync-scheduler)"
    echo ""
    echo "Example:"
    echo "  $(basename "$0") garmin-sync-scheduler"
    echo "  → Branch: speckit/001-garmin-sync-scheduler"
    echo "  → Directory: specs/001-garmin-sync-scheduler/"
    exit 1
}

function get_next_number() {
    local max_num=0
    local num

    # Check remote branches for speckit/* pattern
    while IFS= read -r branch; do
        if [[ "$branch" =~ speckit/([0-9]+)- ]]; then
            num="${BASH_REMATCH[1]}"
            num=$((10#$num))  # Remove leading zeros for arithmetic
            if (( num > max_num )); then
                max_num=$num
            fi
        fi
    done < <(git branch -r --list 'origin/speckit/*' 2>/dev/null | sed 's|origin/||; s/^[[:space:]]*//')

    # Check local branches for speckit/* pattern
    while IFS= read -r branch; do
        if [[ "$branch" =~ speckit/([0-9]+)- ]]; then
            num="${BASH_REMATCH[1]}"
            num=$((10#$num))
            if (( num > max_num )); then
                max_num=$num
            fi
        fi
    done < <(git branch --list 'speckit/*' 2>/dev/null | sed 's/^[[:space:]]*//')

    # Check existing specs directories
    if [[ -d "${REPO_ROOT}/specs" ]]; then
        while IFS= read -r dir; do
            dir_name="$(basename "$dir")"
            if [[ "$dir_name" =~ ^([0-9]+)- ]]; then
                num="${BASH_REMATCH[1]}"
                num=$((10#$num))
                if (( num > max_num )); then
                    max_num=$num
                fi
            fi
        done < <(find "${REPO_ROOT}/specs" -mindepth 1 -maxdepth 1 -type d 2>/dev/null)
    fi

    echo $(( max_num + 1 ))
}

function main() {
    if [[ $# -lt 1 ]] || [[ "$1" == "-h" ]] || [[ "$1" == "--help" ]]; then
        usage
    fi

    local feature_name="$1"

    # Validate feature name is kebab-case
    if [[ ! "$feature_name" =~ ^[a-z][a-z0-9-]*[a-z0-9]$ ]]; then
        echo "ERROR: Feature name must be kebab-case (e.g., garmin-sync-scheduler)" >&2
        exit 1
    fi

    cd "${REPO_ROOT}"

    # Fetch latest remote state
    echo "Fetching latest remote branches..."
    git fetch --quiet origin 2>/dev/null || true

    # Determine next number
    local next_num
    next_num=$(get_next_number)
    local padded_num
    padded_num=$(printf "%03d" "$next_num")

    local branch_name="speckit/${padded_num}-${feature_name}"
    local spec_dir="specs/${padded_num}-${feature_name}"

    # Check if branch already exists
    if git show-ref --verify --quiet "refs/heads/${branch_name}" 2>/dev/null; then
        echo "ERROR: Branch '${branch_name}' already exists locally" >&2
        exit 1
    fi

    if git show-ref --verify --quiet "refs/remotes/origin/${branch_name}" 2>/dev/null; then
        echo "ERROR: Branch '${branch_name}' already exists on remote" >&2
        exit 1
    fi

    # Create feature branch from main
    echo "Creating branch: ${branch_name}"
    git checkout -b "${branch_name}" main

    # Create spec directory
    echo "Creating spec directory: ${spec_dir}"
    mkdir -p "${spec_dir}"

    # Copy spec template if available
    local template=".specify/templates/spec-template.md"
    if [[ -f "$template" ]]; then
        echo "Copying spec template to ${spec_dir}/spec.md"
        cp "$template" "${spec_dir}/spec.md"
    fi

    echo ""
    echo "✅ Feature setup complete!"
    echo ""
    echo "  Branch:    ${branch_name}"
    echo "  Spec dir:  ${spec_dir}/"
    echo "  Next step: Edit ${spec_dir}/spec.md or use @speckit.specify"
}

main "$@"
