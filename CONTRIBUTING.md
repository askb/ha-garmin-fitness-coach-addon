# Contributing to GarminCoach Addon

## Repository Structure

```
garmincoach-addon/              ← This repo (addon wrapper)
├── garmincoach/                ← HA addon directory
│   ├── config.json             ← Addon manifest
│   ├── Dockerfile              ← Multi-stage build
│   ├── build.json              ← Multi-arch config
│   ├── apparmor.txt            ← Security profile
│   ├── DOCS.md                 ← Addon documentation
│   ├── translations/           ← i18n
│   └── rootfs/                 ← Files injected into container
│       ├── app/lib/            ← AI backend abstraction
│       ├── app/scripts/        ← Garmin sync script
│       └── etc/s6-overlay/     ← Service management
├── scripts/
│   └── build-local.sh          ← Local build & test
└── .github/workflows/
    └── build.yml               ← CI/CD pipeline

~/git/garmin-coach/             ← App repo (separate)
├── packages/engine/            ← Sport science compute
├── packages/api/               ← tRPC API
├── packages/db/                ← Database schema
└── apps/nextjs/                ← Web frontend
```

## Local Development

### Prerequisites
- Docker
- The [garmin-coach](https://github.com/askb/garmin-coach) app repo at `~/git/garmin-coach`

### Build Locally
```bash
# Build the addon image
./scripts/build-local.sh

# Build and run (accessible at http://localhost:3100)
./scripts/build-local.sh --run

# Clean up
./scripts/build-local.sh --clean
```

### How CI Works
1. CI checks out both repos (addon + app)
2. Multi-stage Docker build: Node.js builder → HA base image
3. Pushes multi-arch images (amd64 + aarch64) to GHCR
4. Tagged releases create GitHub Releases

## AI Backend

The addon supports 3 AI backends:

| Backend | How it works |
|---|---|
| `ha_conversation` | Calls HA Conversation API → routes to your configured agent (OpenClaw, Claude, etc.) |
| `ollama` | Direct HTTP to local Ollama instance |
| `none` | Rules-based coaching (no LLM) |

The abstraction lives in `rootfs/app/lib/ai-backend.ts`.

## Database Strategy

- **App (standalone)**: PostgreSQL via Drizzle ORM
- **Addon**: SQLite via Drizzle (same schema, different driver)
- Migration path: Drizzle supports both — swap the driver config

## Releasing

1. Update version in `garmincoach/config.json`
2. Update `CHANGELOG.md`
3. Tag: `git tag v0.1.0 && git push --tags`
4. CI builds images and creates a GitHub Release
