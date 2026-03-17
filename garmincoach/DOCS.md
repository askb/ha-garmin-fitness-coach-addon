# GarminCoach Home Assistant Addon

## Overview

GarminCoach is an AI-powered sport scientist that analyzes your Garmin health
and fitness data to provide evidence-based coaching, training load management,
and recovery optimization — all running locally on your Home Assistant
instance.

It connects to Garmin Connect, syncs your metrics (heart rate, HRV, sleep,
activities, VO2max, stress, body battery), and presents everything through a
rich dashboard with optional AI coaching powered by local or cloud LLMs.

## Setup Guide

### 1. Install the Addon

Install **GarminCoach** from the Home Assistant add-on store (see the
[README](https://github.com/askb/ha-garmin-fitness-coach-addon#installation)
for repository setup).

### 2. Connect Your Garmin Account

1. **Start** the addon and open the **Web UI** (sidebar → GarminCoach).
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
| `ha_conversation` **(default)** | Uses your existing HA Conversation agent (OpenAI, Claude, local LLM, etc.) — zero extra setup if you already have one configured. |
| `ollama` | Direct connection to a local [Ollama](https://ollama.com/) instance. Set `ollama_url` to the server address (e.g., `http://homeassistant.local:11434`). Fully private. |
| `none` | Rules-based coaching only. No LLM required — still provides all data-driven insights. |

### 4. Data Sync

Once authenticated, data syncs automatically on the configured interval
(default: every 60 minutes). The first sync may take several minutes as it
fetches up to 6 years of historical data.

## Configuration Options

| Option | Type | Default | Required | Description |
|---|---|---|---|---|
| `garmin_email` | email | — | **Yes** | Garmin Connect login email |
| `garmin_password` | password | — | **Yes** | Garmin Connect password |
| `ai_backend` | list | `ha_conversation` | No | AI coaching backend: `ha_conversation`, `ollama`, or `none` |
| `ollama_url` | url | — | No | Ollama server URL (required only when `ai_backend` is `ollama`) |
| `sync_interval_minutes` | integer | `60` | No | Garmin data sync frequency in minutes (5 – 1440) |

## Garmin Authentication Troubleshooting

| Problem | Solution |
|---|---|
| **MFA code not requested** | Ensure you complete the full Settings → Connect Garmin flow in one session. If the MFA step is missed, disconnect and reconnect. |
| **403 Forbidden errors** | Garmin may rate-limit or block requests. Wait 15-30 minutes and try again. Avoid setting `sync_interval_minutes` below 30. |
| **Token expired** | Session tokens last approximately **one year**. When the addon shows an authentication alert, go to **Settings → Connect Garmin** and re-authenticate. |
| **"Invalid credentials"** | Double-check email/password. If you recently changed your Garmin password, update the addon configuration and reconnect. |
| **Sync stuck or no data** | Check the addon **Log** tab for errors. Restart the addon if the sync daemon is unresponsive. |

## Pages

| Page | Description |
|---|---|
| **Today** | Daily readiness score (0-100), body battery, recent activities, quick insights |
| **Trends** | Multi-metric overlay charts, rolling averages, notable-change detection |
| **Training** | CTL / ATL / TSB fitness-fatigue chart, ACWR injury-risk gauge, load focus, recovery time |
| **Zones** | HR zone distribution, polarization index, efficiency trends, calendar heatmap |
| **Sleep** | Sleep stages breakdown, quality trends, debt tracker, bedtime recommendations |
| **Coach** | AI specialist agents (sport scientist, psychologist, nutritionist, recovery coach) with data-driven personalized advice |
| **Fitness** | VO2max trends, ACSM fitness classification, race predictions (5K / 10K / half / marathon) |
| **Settings** | Garmin account connection, AI backend configuration, sync controls |

## Resource Usage

| Component | RAM | CPU |
|---|---|---|
| Next.js server | ~80 MB | < 1 % idle |
| SQLite database | ~5 MB | < 1 % |
| Garmin sync (periodic) | ~30 MB peak | burst |
| **Total** | **~115 MB** | **< 2 % idle** |

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
