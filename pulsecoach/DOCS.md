# PulseCoach Home Assistant Addon

## Overview

PulseCoach is an AI-powered sport scientist that analyzes your Garmin health
and fitness data to provide evidence-based coaching, training load management,
and recovery optimization — all running locally on your Home Assistant
instance.

It connects to Garmin Connect, syncs your metrics (heart rate, HRV, sleep,
activities, VO2max, stress, body battery), and presents everything through a
rich dashboard with optional AI coaching powered by local or cloud LLMs.

## Architecture

```text
Home Assistant OS
├── PulseCoach Addon (s6-overlay services)
│   ├── PostgreSQL 16           (/data/postgresql, longrun)
│   ├── garmin-auth             (Flask :8099, login/MFA/tokens)
│   ├── pulsecoach orchestrator
│   │   ├── garmin-sync.py      (Garmin Connect → PostgreSQL, every N min)
│   │   ├── metrics-compute.py  (CTL/ATL/TSB/ACWR/CP → PostgreSQL, every 60 min)
│   │   ├── ha-notify.py        (PostgreSQL → 7 HA sensors, every 30 min)
│   │   ├── Next.js standalone  (:3001, tRPC + Drizzle ORM)
│   │   ├── ingress-proxy       (:3000 → :3001, HA path rewriting)
│   │   └── process monitor     (restarts dead services every 60s)
│   └── AI backend              (ha_conversation | ollama | none)
├── Ollama Addon (optional — local LLM inference)
└── Home Assistant Core
    └── Conversation Agent (optional — used by ha_conversation backend)
```

## Setup Guide

### 1. Install the Addon

Install **PulseCoach** from the Home Assistant add-on store (see the
[README](https://github.com/askb/ha-garmin-fitness-coach-addon#installation)
for repository setup).

### 2. Connect Your Garmin Account

1. **Start** the addon and open the **Web UI** (sidebar → PulseCoach).
2. Navigate to **Settings → Connect Garmin**.
3. Enter your Garmin Connect **email** and **password**.
4. If your account has **MFA** (multi-factor authentication) enabled, you will
   be prompted for the one-time code during the same flow.
5. On success the addon stores an OAuth session token locally — no credentials
   leave your network.

### 3. Configure the AI Backend

In the addon **Configuration** tab, set `ai_backend` to one of:

| Backend | Description |
|---|---|
| `ha_conversation` | Uses your existing HA Conversation agent (OpenAI, Claude, local LLM, etc.). Requires a conversation agent to be configured in HA under Settings → Voice Assistants. |
| `ollama` | Direct connection to a local [Ollama](https://ollama.com/) instance. Set `ollama_url` to the server address (e.g., `http://homeassistant.local:11434`). Fully private. |
| `none` **(default)** | Rules-based coaching only. No LLM required — still provides all data-driven insights. |

### 4. Data Sync

Once authenticated, data syncs automatically on the configured interval
(default: every 60 minutes). The first sync may take several minutes as it
fetches up to 6 years of historical data.

## Configuration Options

| Option | Type | Default | Required | Description |
|---|---|---|---|---|
| `garmin_email` | email | — | **Yes** | Garmin Connect login email |
| `garmin_password` | password | — | **Yes** | Garmin Connect password |
| `ai_backend` | list | `none` | No | AI coaching backend: `ha_conversation`, `ollama`, or `none` |
| `ollama_url` | url | — | No | Ollama server URL. Required for the `ollama` chat backend, **and** for coach memory/RAG embeddings even when `ai_backend` is `ha_conversation` or `none` (the nightly memory rebuild only runs when this is set) |
| `ollama_embed_model` | string | `nomic-embed-text` | No | Embedding model for coach memory/RAG over multi-year history. Pull it on your Ollama host; falls back to the chat model if unavailable |
| `sync_interval_minutes` | integer | `60` | No | Garmin data sync frequency in minutes (5 – 1440) |

## Garmin Authentication Troubleshooting

| Problem | Solution |
|---|---|
| **MFA code not requested** | Ensure you complete the full Settings → Connect Garmin flow in one session. If the MFA step is missed, disconnect and reconnect. |
| **403 Forbidden errors** | Garmin may rate-limit or block requests. Wait 15-30 minutes and try again. Avoid setting `sync_interval_minutes` below 30. |
| **Token expired** | Session tokens last approximately **one year**. When the addon shows an authentication alert, go to **Settings → Connect Garmin** and re-authenticate. |
| **"Invalid credentials"** | Double-check email/password. If you recently changed your Garmin password, update the addon configuration and reconnect. |
| **Sync stuck or no data** | Check the addon **Log** tab for errors. If a **manual sync** silently does nothing, the underlying error is now captured in `/data/garmin-sync.log` (rotated to `.log.1` on each run). Tail it with `cat /data/garmin-sync.log` from the addon's `Web terminal`/SSH, or call `GET /auth/sync-log` via the ingress endpoint. Restart the addon if the sync daemon is unresponsive. |

## Pages

| Page | Description |
|---|---|
| **Today** | Daily readiness score (0-100), body battery, recent activities, quick insights |
| **Training** | CTL / ATL / TSB fitness-fatigue chart, ACWR injury-risk gauge, load focus, recovery time |
| **Fitness** | VO2max trends, VDOT score, race predictions (5K / 10K / half / marathon) with confidence intervals |
| **Activities** | Activity detail — laps, efficiency factor, GAP, RPE, zone distribution |
| **Insights** | Proactive AI insight cards — 6-rule engine (ACWR, TSB, HRV, sleep debt, ramp rate, interventions) |
| **Journal** | Whoop-style daily check-in (body feel, inputs, cycle tracking) |
| **Interventions** | Recovery intervention log with effectiveness ratings |
| **Sleep** | Sleep stages breakdown, quality trends, debt tracker, bedtime recommendations |
| **Trends** | 6+ year multi-metric overlay charts with rolling averages |
| **Coach** | AI specialist agents (sport scientist, psychologist, nutritionist, recovery coach) |
| **Power** | Critical power curve, power-duration chart, W′ |
| **Zones** | HR zone distribution, Seiler polarization index, calendar heatmap |
| **Settings** | Garmin account connection, AI backend configuration, sync controls |

A visual walkthrough of the main pages — Home, Fitness, Training,
Zones, Trends, and the AI Coach — is in the
[repository README](https://github.com/askb/ha-garmin-fitness-coach-addon#screenshots).

## HA Sensors

The addon pushes 7 sensors to Home Assistant via the Supervisor API:

| Entity ID | Description |
|-----------|-------------|
| `sensor.pulsecoach_ctl` | Chronic Training Load (42-day fitness) |
| `sensor.pulsecoach_atl` | Acute Training Load (7-day fatigue) |
| `sensor.pulsecoach_form` | Training Stress Balance (TSB) |
| `sensor.pulsecoach_acwr` | Acute:Chronic Workload Ratio |
| `sensor.pulsecoach_injury_risk` | Risk level: Low / Moderate / High / Very High |
| `sensor.pulsecoach_body_battery` | Current Garmin Body Battery |
| `sensor.pulsecoach_sleep_debt` | Accumulated sleep debt (hours) |

## Resource Usage

| Component | RAM | CPU |
|---|---|---|
| Next.js server | ~80 MB | < 1 % idle |
| PostgreSQL database | ~30 MB | < 1 % |
| Garmin sync (periodic) | ~30 MB peak | burst |
| **Total** | **~140 MB** | **< 2 % idle** |

The addon requires a minimum of **256 MB** available RAM. Running the
`ollama` backend locally will need additional resources depending on the
model size.

## Privacy

All data processing happens **locally** on your Home Assistant instance. No
health data is sent to external servers.

- **Garmin Connect**: The addon authenticates and fetches data using the
  official Garmin Connect API. Data flows only between Garmin's servers and
  your HA instance.
- **AI Coaching** (`ha_conversation`): Prompts are sent to whatever
  Conversation agent you have configured in HA — this may be a cloud service
  (e.g., OpenAI) depending on your setup.
- **AI Coaching** (`ollama`): All inference runs locally on your hardware.
- **AI Coaching** (`none`): No external calls of any kind.

## Support

- [GitHub Issues](https://github.com/askb/ha-garmin-fitness-coach-addon/issues)
- [Home Assistant Community Forum](https://community.home-assistant.io/)
