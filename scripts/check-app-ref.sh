#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Anil Belur <askb23@gmail.com>
# SPDX-License-Identifier: Apache-2.0
##############################################################################
# Warn if the bundled app ref is newer than the addon manifest version.
##############################################################################

set -euo pipefail
IFS=$'\n\t'

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
dockerfile="${repo_root}/pulsecoach/Dockerfile"
config_json="${repo_root}/pulsecoach/config.json"

app_ref="$(sed -n 's/^ARG APP_REF=v//p' "${dockerfile}" | head -n1)"
addon_version="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' "${config_json}")"

if [[ -z "${app_ref}" ]]; then
    echo "WARNING: pulsecoach/Dockerfile does not define ARG APP_REF=v..." >&2
    exit 0
fi

if [[ "$(printf '%s\n%s\n' "${app_ref}" "${addon_version}" | sort -V | head -n1)" != "${app_ref}" ]]; then
    echo "WARNING: addon version ${addon_version} is older than APP_REF ${app_ref}" >&2
fi
