# GarminCoach — Home Assistant Addon

AI-powered sport scientist that turns your Garmin data into actionable coaching, training analysis, and recovery optimization — running entirely on your local network.

## Features

- 🏋️ **Training Load Analysis** — CTL/ATL/TSB (Banister model), ACWR injury risk tracking
- 📊 **Zone Analytics** — HR zone distribution, Seiler polarization index, efficiency trends
- 🧠 **AI Specialist Agents** — Sport scientist, psychologist, nutritionist, recovery coach (via local Ollama)
- 🏃 **Race Predictions** — Riegel formula for 5K/10K/half/marathon
- 💤 **Sleep Coaching** — Sleep debt tracking, bedtime recommendations, quality trends
- 📈 **6+ Year Trends** — Long-term analysis with correlation insights
- 🔒 **Fully Private** — All data stays local, AI runs on your hardware

## Architecture

```
Home Assistant Supervisor
├── GarminCoach Addon
│   ├── Next.js (standalone server)
│   ├── SQLite (embedded database)
│   └── Garmin sync (garminconnect-python)
└── Ollama Addon (optional, for AI agents)
```

## Installation

1. Add this repository to your Home Assistant addon store
2. Install the GarminCoach addon
3. Configure your Garmin Connect credentials in the addon settings
4. Start the addon — it appears in your sidebar automatically

## Configuration

| Option | Description | Required |
|---|---|---|
| `garmin_email` | Your Garmin Connect email | Yes |
| `garmin_password` | Your Garmin Connect password | Yes |
| `ollama_url` | Ollama server URL (e.g., `http://homeassistant.local:11434`) | No |
| `sync_interval_minutes` | How often to sync Garmin data (default: 60) | No |

## Requirements

- Home Assistant 2024.1 or newer
- 256MB available RAM
- Garmin Connect account with a compatible device

## Development

This addon packages the [GarminCoach](https://github.com/askb/garmin-coach) application for Home Assistant. See the main repo for the full codebase.

## License

MIT
