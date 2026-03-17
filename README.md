# GarminCoach — Home Assistant Addon

[![Open your Home Assistant instance and show the add add-on repository dialog with a specific repository URL pre-filled.](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Faskb%2Fha-garmin-fitness-coach-addon)

AI-powered sport scientist that turns your Garmin data into actionable
coaching, training analysis, and recovery optimization — running entirely on
your local network.

---

## Table of Contents

- [Features](#features)
- [Architecture](#architecture)
- [Installation](#installation)
- [Configuration](#configuration)
- [Garmin Authentication](#garmin-authentication)
- [AI Backend Options](#ai-backend-options)
- [Known Issues](#known-issues)
- [Development](#development)
- [Contributing](#contributing)
- [License](#license)

## Features

- 🏋️ **Training Load Analysis** — CTL / ATL / TSB (Banister fitness-fatigue
  model), ACWR injury-risk tracking (Hulin 2016)
- 📊 **Zone Analytics** — HR zone distribution, Seiler polarization index,
  efficiency trends, calendar heatmap
- 🧠 **AI Specialist Agents** — Sport scientist, psychologist, nutritionist,
  recovery coach (via HA Conversation, local Ollama, or rules-based)
- 🏃 **Race Predictions** — Riegel formula for 5K / 10K / half-marathon /
  marathon
- 💤 **Sleep Coaching** — Sleep debt tracking, bedtime recommendations, quality
  trends, stage analysis
- 📈 **6+ Year Trends** — Long-term multi-metric overlay charts with rolling
  averages and notable-change detection
- 🩺 **Readiness Score** — Evidence-based daily score (0-100) using HRV, sleep,
  training load, and stress (Buchheit 2014)
- 🔒 **Fully Private** — All data stays local; AI runs on your hardware

## Architecture

```text
Home Assistant Supervisor
│
├── GarminCoach Addon  (this repository)
│   ├── Next.js 15 standalone server  (:3000 via Ingress)
│   ├── SQLite database               (/data/garmincoach.db)
│   ├── Garmin sync daemon             (garminconnect-python, s6-overlay)
│   └── AI backend abstraction         (ha_conversation | ollama | none)
│
├── Ollama Addon  (optional — local LLM inference)
│
└── Home Assistant Core
    └── Conversation Agent  (optional — used by ha_conversation backend)
```

Supported architectures: **amd64**, **aarch64**.

## Installation

### One-Click Install

Click the button at the top of this README, or:

[![Add Repository](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Faskb%2Fha-garmin-fitness-coach-addon)

Then install **GarminCoach** from the add-on store and start it.

### Manual Install

1. In Home Assistant go to **Settings → Add-ons → Add-on Store → ⋮ →
   Repositories**.
2. Paste the repository URL:
   ```
   https://github.com/askb/ha-garmin-fitness-coach-addon
   ```
3. Click **Add**, then find **GarminCoach** in the store and click **Install**.
4. Start the addon — it appears in your sidebar automatically.

## Configuration

| Option | Type | Default | Required | Description |
|---|---|---|---|---|
| `garmin_email` | email | — | **Yes** | Your Garmin Connect email address |
| `garmin_password` | password | — | **Yes** | Your Garmin Connect password |
| `ai_backend` | list | `ha_conversation` | No | AI coaching backend (`ha_conversation`, `ollama`, or `none`) |
| `ollama_url` | url | — | No | Ollama server URL (only when `ai_backend` is `ollama`) |
| `sync_interval_minutes` | integer | `60` | No | How often to pull new data from Garmin (5 – 1440 minutes) |

## Garmin Authentication

GarminCoach authenticates with Garmin Connect using a **web-based auth flow**:

1. Open the addon **Web UI** (sidebar → GarminCoach).
2. Navigate to **Settings → Connect Garmin**.
3. Enter your **email** and **password**. If your account has MFA enabled you
   will be prompted for the one-time code during the same flow.
4. On success the addon stores an OAuth session token locally in
   `/data/garmincoach.db`. No credentials are sent to any third-party service.

> **Token lifetime:** The session token is valid for roughly **one year**
> before Garmin forces a re-authentication.  The addon will surface a
> notification when a token refresh is needed.

## AI Backend Options

| Backend | Description |
|---|---|
| `ha_conversation` **(default)** | Routes prompts through the Home Assistant Conversation API to whatever agent you have configured (e.g., OpenAI, Claude, local LLM). Zero extra setup if you already use one. |
| `ollama` | Direct HTTP connection to a local [Ollama](https://ollama.com/) instance — fully private, runs on your hardware. Set `ollama_url` to the instance address. |
| `none` | Rules-based coaching only — no LLM required. Still provides all data-driven insights, readiness scores, and training-load analytics. |

## Known Issues

| Issue | Details |
|---|---|
| **Garmin MFA prompt** | If MFA is enabled on your Garmin account the addon will request the code during the web-based Settings flow. Re-authenticate from Settings if the MFA step is missed. |
| **Token expiry (~1 year)** | Garmin session tokens expire after approximately one year. The addon will show an alert; re-authenticate from **Settings → Connect Garmin**. |
| **Rate limiting** | Garmin may temporarily block requests if the sync interval is too aggressive. Keep `sync_interval_minutes` at 30 or above. |
| **First sync delay** | The initial sync fetches up to 6 years of history and can take several minutes depending on data volume. |

## Development

This addon packages the
[GarminCoach App](https://github.com/askb/ha-garmin-fitness-coach-app) for
Home Assistant. See the app repo for the full Next.js / tRPC / Drizzle
codebase.

### Prerequisites

- Docker
- The app repo cloned at `~/git/ha-garmin-fitness-coach-app`

### Build Locally

```bash
# Build the addon Docker image
./scripts/build-local.sh

# Build and run (accessible at http://localhost:3100)
./scripts/build-local.sh --run

# Remove built images
./scripts/build-local.sh --clean
```

### Run Tests

```bash
# From the repository root
python -m pytest tests/ -v
```

### CI / CD

CI checks out both repos, runs a multi-stage Docker build (Node.js builder →
HA base image), and pushes multi-arch images (amd64 + aarch64) to GHCR.
Tagged releases create GitHub Releases automatically.

## Contributing

Contributions are welcome! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for
repository structure, local development setup, AI backend details, and the
release process.

## License

This project is licensed under the
[Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0).
See [LICENSE](LICENSE) for the full text.

SPDX-License-Identifier: Apache-2.0
