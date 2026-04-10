---
description: Development guidelines for the PulseCoach Home Assistant addon.
applyTo: '**'
---

<!--
SPDX-FileCopyrightText: 2026 Anil Belur <askb23@gmail.com>
SPDX-License-Identifier: Apache-2.0
-->

# PulseCoach Addon Development Guidelines

Auto-generated from feature plans. Last updated: 2026-03-25

## Active Technologies
- Docker multi-stage build (Node.js 22 builder → HA base image)
- Python 3.11+ (Garmin sync, HA notifications, testing)
- TypeScript (Next.js standalone, tRPC, AI backend)
- Bash (s6-overlay services, build scripts)
- s6-overlay for process management
- PostgreSQL 16 / SQLite (Drizzle ORM)
- pytest for Python testing (19 tests)

## Project Structure

```text
pulsecoach/                    # HA addon directory (slug)
├── config.json                 # Addon manifest & schema
├── Dockerfile                  # Multi-stage build
├── build.json                  # Multi-arch config
├── rootfs/app/lib/             # TypeScript (AI backend)
├── rootfs/app/scripts/         # Python (sync, notifications)
├── rootfs/etc/s6-overlay/      # Service definitions
├── translations/               # i18n
scripts/                        # Build helpers
tests/                          # Python test suite
```

## Commands

```bash
./scripts/build-local.sh            # Build addon Docker image
./scripts/build-local.sh --run      # Build & run (localhost:3100)
./scripts/build-local.sh --clean    # Clean up
pytest tests/ -v                    # Run Python tests
```

## Code Style
- Python 3.11+: Follow project conventions
- TypeScript: Match app repo patterns
- Bash: shellcheck-clean, set -euo pipefail
- YAML: yamllint compliant

## Recent Changes
- Initial speckit bootstrap

<!-- MANUAL ADDITIONS START -->
<!-- MANUAL ADDITIONS END -->
