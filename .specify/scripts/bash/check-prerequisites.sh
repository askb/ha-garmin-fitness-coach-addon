#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Anil Belur <askb23@gmail.com>
##############################################################################
# check-prerequisites.sh
#
# Validates which spec documents exist for the current feature.
# Checks for: spec, plan, tasks, data-model, research, contracts.
# Supports --require-tasks and --include-tasks flags.
# Outputs JSON.
#
# Usage: check-prerequisites.sh [--require-tasks] [--include-tasks] [spec-dir]
##############################################################################

set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

REQUIRE_TASKS=false
INCLUDE_TASKS=false
SPEC_DIR=""

function usage() {
    echo "Usage: $(basename "$0") [OPTIONS] [spec-dir]"
    echo ""
    echo "Check which spec documents exist for a feature."
    echo ""
    echo "Options:"
    echo "  --require-tasks   Exit with error if tasks.md is missing"
    echo "  --include-tasks   Include tasks.md in the prerequisites check"
    echo "  -h, --help        Show this help"
    echo ""
    echo "Arguments:"
    echo "  spec-dir          Path to spec directory (auto-detected from branch if omitted)"
    exit 0
}

function detect_spec_dir() {
    cd "${REPO_ROOT}"

    local branch
    branch="$(git branch --show-current 2>/dev/null || echo "")"

    if [[ "$branch" =~ ^speckit/(.+)$ ]]; then
        local spec_id="${BASH_REMATCH[1]}"
        if [[ -d "specs/${spec_id}" ]]; then
            echo "specs/${spec_id}"
            return 0
        fi
    fi

    # Fallback: find the most recently modified specs dir
    if [[ -d "specs" ]]; then
        local latest
        latest="$(find specs -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' 2>/dev/null \
            | sort -rn | head -1 | cut -d' ' -f2)"
        if [[ -n "$latest" ]]; then
            echo "$latest"
            return 0
        fi
    fi

    return 1
}

function check_file() {
    local filepath="$1"
    local name="$2"

    if [[ -f "$filepath" ]]; then
        local size
        size="$(wc -c < "$filepath")"
        echo "    \"${name}\": {\"exists\": true, \"path\": \"${filepath}\", \"size\": ${size}}"
    else
        echo "    \"${name}\": {\"exists\": false, \"path\": \"${filepath}\", \"size\": 0}"
    fi
}

function main() {
    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --require-tasks)
                REQUIRE_TASKS=true
                shift
                ;;
            --include-tasks)
                INCLUDE_TASKS=true
                shift
                ;;
            -h|--help)
                usage
                ;;
            *)
                SPEC_DIR="$1"
                shift
                ;;
        esac
    done

    cd "${REPO_ROOT}"

    # Detect or validate spec directory
    if [[ -z "$SPEC_DIR" ]]; then
        SPEC_DIR="$(detect_spec_dir)" || {
            echo '{"error": "Cannot detect spec directory. Provide it as an argument or switch to a speckit/* branch."}'
            exit 1
        }
    fi

    if [[ ! -d "$SPEC_DIR" ]]; then
        echo "{\"error\": \"Spec directory '${SPEC_DIR}' does not exist.\"}"
        exit 1
    fi

    # Build document list
    local docs=("spec" "plan" "checklist" "data-model" "research" "contracts")

    if [[ "$INCLUDE_TASKS" == "true" ]] || [[ "$REQUIRE_TASKS" == "true" ]]; then
        docs+=("tasks")
    fi

    # Check each document
    local all_exist=true
    local tasks_exist=true
    local results=""

    for doc in "${docs[@]}"; do
        local filepath="${SPEC_DIR}/${doc}.md"
        if [[ -n "$results" ]]; then
            results="${results},"$'\n'
        fi
        results="${results}$(check_file "$filepath" "$doc")"

        if [[ ! -f "$filepath" ]]; then
            all_exist=false
            if [[ "$doc" == "tasks" ]]; then
                tasks_exist=false
            fi
        fi
    done

    # Check tasks requirement
    local status="ok"
    local message="All checked documents present."

    if [[ "$all_exist" == "false" ]]; then
        status="incomplete"
        message="Some documents are missing."
    fi

    if [[ "$REQUIRE_TASKS" == "true" ]] && [[ "$tasks_exist" == "false" ]]; then
        status="error"
        message="Required tasks.md is missing."
    fi

    cat <<EOF
{
  "spec_dir": "${SPEC_DIR}",
  "status": "${status}",
  "message": "${message}",
  "documents": {
${results}
  }
}
EOF

    if [[ "$status" == "error" ]]; then
        exit 1
    fi
}

main "$@"
