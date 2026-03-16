# SPDX-FileCopyrightText: 2025 Anil Belur <askb23@gmail.com>
# SPDX-License-Identifier: Apache-2.0

# AI Coding Agent Instructions

## Project Overview

Home Assistant addon that packages the GarminCoach fitness coaching app
for easy installation on HAOS. Uses s6-overlay for process management,
SQLite for storage, and HA Conversation API (OpenClaw/Claude) for AI.

## Repository Structure

```
.
├── garmincoach/                    # HA addon directory (slug)
│   ├── config.json                 # Addon manifest (options, schema, ingress)
│   ├── build.json                  # Multi-arch build config
│   ├── Dockerfile                  # Multi-stage: Node.js builder → HA base
│   ├── apparmor.txt                # AppArmor security profile
│   ├── DOCS.md                     # Addon documentation
│   ├── CHANGELOG.md
│   ├── translations/en.yaml        # Config UI labels
│   └── rootfs/
│       ├── app/
│       │   ├── lib/ai-backend.ts   # Unified AI: HA Conversation + Ollama
│       │   └── scripts/garmin-sync.py  # Garmin Connect API sync
│       └── etc/s6-overlay/s6-rc.d/ # s6 service definitions
├── scripts/
│   └── build-local.sh              # Local build & test
├── repository.json                 # HA addon repository manifest
├── .github/workflows/              # CI/CD pipelines
└── tests/                          # Test suite
```

## Key Conventions

### HA Addon Structure
- `garmincoach/` is the addon slug — do NOT rename
- `config.json` defines options, schema, and addon metadata
- `rootfs/` is overlaid onto the container filesystem at runtime
- s6-overlay manages the service lifecycle (type: longrun)

### AI Backend
- `ai-backend.ts` abstracts three backends: `ha_conversation`, `ollama`, `none`
- `ha_conversation` uses HA Supervisor API (`POST /core/api/conversation/process`)
- `SUPERVISOR_TOKEN` is auto-injected by HA for addons with `homeassistant_api: true`
- HA Conversation takes single text input, not message arrays

### Garmin Sync
- `garmin-sync.py` uses `garminconnect` Python package
- Tokens cached in `/data/garmin-tokens/` (persistent across restarts)
- Syncs daily: metrics, activities, sleep, VO2max

## Development Commands

```bash
# Local build (requires Docker)
./scripts/build-local.sh

# Build and run on port 3100
./scripts/build-local.sh --run

# Clean build artifacts
./scripts/build-local.sh --clean
```

## Testing

Tests are in `tests/` directory:
- Python tests: `pytest tests/`
- Shell tests: validated via ShellCheck in CI

## Commit Conventions

- Conventional Commits: `Feat:`, `Fix:`, `Chore:`, `Docs:`, etc.
- Title max 72 chars, body max 72 chars per line
- Required: `Signed-off-by: Anil Belur <askb23@gmail.com>`
- Change-Id trailer added automatically

## Pre-commit

Run `pre-commit run --all-files`. Hooks: yamllint, gitlint, shellcheck,
REUSE compliance, actionlint.

## Important Files

- `garmincoach/config.json` — Addon manifest and option schema
- `garmincoach/Dockerfile` — Multi-stage build
- `garmincoach/rootfs/app/lib/ai-backend.ts` — AI abstraction layer
- `garmincoach/rootfs/app/scripts/garmin-sync.py` — Data sync
- `garmincoach/rootfs/etc/s6-overlay/s6-rc.d/garmincoach/run` — Service entry
- `repository.json` — Addon store manifest
