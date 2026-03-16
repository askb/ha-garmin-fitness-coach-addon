# GarminCoach Home Assistant Addon

## Overview

GarminCoach is an AI-powered sport scientist that analyzes your Garmin health and fitness data to provide evidence-based coaching, training load management, and recovery optimization.

## How it works

1. **Data Sync**: The addon connects to your Garmin Connect account and syncs your health metrics (HR, HRV, sleep, activities, VO2max, stress, body battery) on a configurable schedule.

2. **Analysis Engine**: A sport-science engine computes:
   - **Readiness Score** (0-100) based on HRV, sleep, training load, and stress
   - **Training Load** (CTL/ATL/TSB) using the Banister fitness-fatigue model
   - **Injury Risk** (ACWR) using Hulin's acute:chronic workload ratio
   - **Zone Distribution** with Seiler's polarization index
   - **Race Predictions** using the Riegel formula
   - **Sleep Coaching** with debt tracking and optimization tips

3. **AI Coaching** (optional): If you have an Ollama instance running, 4 specialist agents provide personalized advice:
   - 🏋️ Sport Scientist — periodization, load management, VO2max optimization
   - 🧠 Sport Psychologist — motivation, mental resilience, consistency
   - 🥗 Nutritionist — fueling strategies, recovery nutrition
   - 💤 Recovery Specialist — sleep optimization, deload protocols

## Configuration

### Required
- **Garmin Email**: Your Garmin Connect login email
- **Garmin Password**: Your Garmin Connect password

### Optional
- **Ollama URL**: Point to an Ollama instance for AI coaching (e.g., install the Ollama HA addon)
- **Sync Interval**: How often to pull new data from Garmin (default: 60 minutes)

## Pages

| Page | Description |
|---|---|
| **Today** | Readiness score, body battery, recent activities, quick insights |
| **Trends** | Multi-metric overlay charts, rolling averages, notable changes |
| **Training** | CTL/ATL/TSB chart, ACWR gauge, load focus, recovery time |
| **Zones** | HR zone distribution, polarization index, efficiency trends, calendar heatmap |
| **Sleep** | Sleep stages, quality trends, debt tracker, bedtime recommendations |
| **Coach** | AI specialist agents with data-driven personalized advice |
| **Fitness** | VO2max trends, ACSM classification, race predictions |

## Resource Usage

| Component | RAM | CPU |
|---|---|---|
| Next.js server | ~80MB | <1% idle |
| SQLite database | ~5MB | <1% |
| Garmin sync (periodic) | ~30MB peak | burst |
| **Total** | **~115MB** | **<2% idle** |

## Privacy

All data processing happens locally on your Home Assistant instance. No data is sent to external servers. The AI coaching (if enabled) also runs locally via Ollama.

## Support

- [GitHub Issues](https://github.com/askb/garmincoach-addon/issues)
- [Home Assistant Community Forum](https://community.home-assistant.io/)
