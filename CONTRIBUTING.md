# Contributing to GarminCoach Addon

> For architecture context and AI agent conventions, see [AGENTS.md](AGENTS.md).

## Repository Structure

```
ha-garmin-fitness-coach-addon/  ← This repo (addon wrapper)
├── garmincoach/                ← HA addon directory
│   ├── config.json             ← Addon manifest
│   ├── Dockerfile              ← Multi-stage build
│   ├── build.json              ← Multi-arch config
│   ├── DOCS.md                 ← Addon documentation
│   ├── translations/           ← i18n
│   └── rootfs/                 ← Files injected into container
│       ├── app/lib/            ← AI backend abstraction
│       ├── app/scripts/        ← Garmin sync script
│       └── etc/s6-overlay/     ← Service management
├── scripts/
│   └── build-local.sh          ← Local build & test
├── tests/                      ← Python test suite
└── .github/workflows/
    └── build.yml               ← CI/CD pipeline

~/git/ha-garmin-fitness-coach-app/ ← App repo (separate)
├── packages/engine/            ← Sport science compute
├── packages/api/               ← tRPC API
├── packages/db/                ← Database schema
└── apps/nextjs/                ← Web frontend
```

## Local Development

### Prerequisites

- Docker
- Python 3.11+
- The [ha-garmin-fitness-coach-app](https://github.com/askb/ha-garmin-fitness-coach-app) app repo
  cloned to `~/git/ha-garmin-fitness-coach-app`
- `pre-commit` (`pip install pre-commit`)
- `hadolint` ([installation guide](https://github.com/hadolint/hadolint#install))

### Build Docker Image Locally

`scripts/build-local.sh` copies the app source into the Docker build context,
builds the multi-stage image, and optionally runs it.

```bash
# Build the addon image
./scripts/build-local.sh

# Build and run (accessible at http://localhost:3100)
./scripts/build-local.sh --run

# Clean up built images
./scripts/build-local.sh --clean
```

The `--run` flag starts the container with `AI_BACKEND=none` and
`DEV_BYPASS_AUTH=true` so you can test without real credentials. A local
data directory is mounted at `.local-data/` inside the repo root.

### How CI Works

1. CI checks out both repos (addon + app)
2. Multi-stage Docker build: Node.js builder → HA base image
3. Pushes multi-arch images (amd64 + aarch64) to GHCR
4. Tagged releases create GitHub Releases

## Running Tests

### Python Tests (pytest)

Tests live in `tests/` and use `pytest`.

```bash
# Install test dependencies
pip install -e ".[test]"

# Run all tests
pytest tests/ -v

# Run only unit tests
pytest tests/ -v -m unit
```

Fixtures are defined in `tests/conftest.py` (mock Garmin client, in-memory
SQLite DB, environment variables). Note: the test fixtures use an in-memory
SQLite database for fast, isolated test runs, whereas the production addon
uses embedded PostgreSQL. Tests must run without real credentials or
network access.

### Dockerfile Linting (hadolint)

```bash
hadolint garmincoach/Dockerfile
```

### YAML / Shell / JSON Linting

```bash
yamllint .
shellcheck -x scripts/build-local.sh
python3 -m json.tool garmincoach/config.json > /dev/null
python3 -m json.tool garmincoach/build.json  > /dev/null
python3 -m json.tool repository.json         > /dev/null
```

All of the above checks run automatically in CI via the `validate.yaml`
workflow.

## Pre-commit Hooks

Install the hooks once after cloning:

```bash
pre-commit install
```

Run against all files at any time:

```bash
pre-commit run --all-files
```

Hooks configured in `.pre-commit-config.yaml`:

| Hook | What it checks |
|---|---|
| `check-added-large-files` | Files larger than 2 MB |
| `check-json` | JSON syntax |
| `check-yaml` | YAML syntax |
| `end-of-file-fixer` | Trailing newline |
| `trailing-whitespace` | Trailing spaces |
| `no-commit-to-branch` | Prevents direct pushes to `main` |
| `gitlint` | Commit message format |
| `yamllint` | YAML style |
| `shellcheck` | Shell script correctness |
| `reuse` | SPDX license headers |
| `actionlint` | GitHub Actions workflow syntax |

## Commit Message Format

This project uses [Conventional Commits](https://www.conventionalcommits.org/)
and requires a DCO sign-off on every commit.

### Type Prefixes

| Type | When to use |
|---|---|
| `Feat:` | New feature |
| `Fix:` | Bug fix |
| `Docs:` | Documentation only |
| `Chore:` | Maintenance, dependency updates |
| `Refactor:` | Code restructure without behavior change |
| `Test:` | Adding or fixing tests |
| `CI:` | CI/CD pipeline changes |
| `Build:` | Build system changes |
| `Perf:` | Performance improvement |
| `Revert:` | Reverting a previous commit |

### Format

```
<Type>: <short summary — max 72 chars>

<Optional body — wrap at 72 chars per line>

Signed-off-by: Your Name <your.email@example.com>
```

### Sign-off (DCO)

Add `-s` to every `git commit` command to append the `Signed-off-by` trailer
automatically:

```bash
git commit -s -m "Feat: add resting HR trend chart"
```

Or configure git to always sign off:

```bash
git config --global format.signoff true
```

## s6-overlay Service Manager

The addon uses [s6-overlay](https://github.com/just-containers/s6-overlay) to
manage multiple long-running services inside the container. Service definitions
live in `garmincoach/rootfs/etc/s6-overlay/s6-rc.d/`.

### Services

| Service | Path | Role |
|---|---|---|
| `postgresql` | `rootfs/etc/s6-overlay/s6-rc.d/postgresql/` | Starts the embedded PostgreSQL database |
| `garmincoach` | `rootfs/etc/s6-overlay/s6-rc.d/garmincoach/` | Main service: runs Next.js, Garmin sync, metrics compute, ingress proxy |
| `garmin-auth` | `rootfs/etc/s6-overlay/s6-rc.d/garmin-auth/` | Flask server that handles Garmin OAuth from the UI |

Each service directory contains:

- `type` — set to `longrun` for persistent processes
- `run` — executable script that s6 calls to start the service
- `dependencies.d/<dep>` — (optional) ensures another service starts first

### How `garmincoach/run` Works

1. Reads addon options via `bashio::config` (Garmin credentials, AI backend, sync interval)
2. Waits for PostgreSQL to be ready (`pg_isready`)
3. Pushes the database schema with `drizzle-kit push`
4. Starts background loops for Garmin sync, metrics compute, and HA sensor push
5. Starts the Next.js app (`node server.js`) and the ingress proxy (`node ingress-proxy.js`)
6. Enters a monitoring loop that restarts any child process that exits unexpectedly
7. On `EXIT`/`INT`/`TERM`, backs up tokens and the database to `/share/garmincoach/`
   before stopping all child processes

### Adding a New Service

1. Create `rootfs/etc/s6-overlay/s6-rc.d/<name>/type` containing `longrun`
2. Create `rootfs/etc/s6-overlay/s6-rc.d/<name>/run` (executable shell script)
3. Add `rootfs/etc/s6-overlay/s6-rc.d/user/contents.d/<name>` (empty file)
4. If it depends on another service, add
   `rootfs/etc/s6-overlay/s6-rc.d/<name>/dependencies.d/<dep>`

## Adding New Garmin Sync Fields

Garmin data is fetched in `garmincoach/rootfs/app/scripts/garmin-sync.py` and
stored in PostgreSQL.

### Step-by-step

1. **Find the Garmin API field**

   The `garminconnect` Python library mirrors the Garmin Connect API.
   Check the response dictionaries returned by methods such as
   `client.get_stats()`, `client.get_sleep_data()`, `client.get_hrv_data()`,
   and `client.get_stress_data()`.

2. **Add the column to the database schema**

   Edit the Drizzle schema in the
   [ha-garmin-fitness-coach-app](https://github.com/askb/ha-garmin-fitness-coach-app)
   repo at `packages/db/src/schema.ts`. Add the new column to the
   appropriate table (`daily_metric`, `activity`, or `vo2max_estimate`).

3. **Update `sync_daily_stats()` or `sync_activities()`**

   In `garmin-sync.py`, extend the `INSERT INTO ... VALUES (...)` statement
   and the `ON CONFLICT ... DO UPDATE SET ...` clause to include the new
   column. Map the value from the API response dict:

   ```python
   # Example: adding respiration_rate
   stats.get("averageRespirationValue"),
   ```

4. **Update the `in_memory_db` fixture**

   In `tests/conftest.py`, add the new column to the `CREATE TABLE` statement
   inside `in_memory_db` so existing tests continue to pass:

   ```python
   respiration_rate REAL,
   ```

5. **Add or update tests**

   Add a test in `tests/unit/test_garmin_sync.py` that verifies the new field
   is stored correctly. Use the `mock_garmin_client` fixture and assert on the
   value written to the in-memory database.

6. **Run the full test suite and pre-commit hooks**

   ```bash
   pytest tests/ -v
   pre-commit run --all-files
   ```

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
- **Addon**: Embedded PostgreSQL via Drizzle (same schema, same driver)
- Data is persisted in `/data/` and backed up to `/share/garmincoach/` on shutdown

## Releasing

1. Update version in `garmincoach/config.json`
2. Update `CHANGELOG.md`
3. Tag: `git tag v0.1.0 && git push --tags`
4. CI builds images and creates a GitHub Release
