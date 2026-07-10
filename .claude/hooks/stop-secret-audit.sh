#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Anil Belur <askb23@gmail.com>
# SPDX-License-Identifier: Apache-2.0
#
# Stop hook: refuse to end the session while secret files are staged.

set -euo pipefail

cd "${CLAUDE_PROJECT_DIR:-.}"

staged=$(git diff --cached --name-only \
  | grep -E '(^|/)\.env|gcal-token\.json$|(^|/)secrets/' \
  | grep -v '\.env\.example$' || true)

if [ -n "${staged}" ]; then
  echo "[Stop hook] Secret files are staged — unstage before finishing:" >&2
  echo "${staged}" >&2
  exit 2
fi
