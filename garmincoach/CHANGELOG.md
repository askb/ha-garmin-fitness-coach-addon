# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] — 2025-07-09

### Added

- Initial release of the GarminCoach Home Assistant addon
- **Garmin Connect integration** — web-based auth flow with email, password,
  and MFA support via the Settings page; session token stored locally
- **Data sync daemon** — periodic sync (configurable 5 – 1440 min) using
  garminconnect-python; fetches HR, HRV, sleep, activities, VO2max, stress,
  body battery, and up to 6 years of historical data
- **Readiness scoring** — evidence-based daily score (0-100) using Z-score
  composites (Buchheit 2014)
- **Training load analysis** — CTL / ATL / TSB computed via the Banister
  fitness-fatigue model (1975)
- **Injury risk tracking** — ACWR (acute:chronic workload ratio) using
  Hulin's method (2016)
- **Zone analytics** — HR zone distribution, Seiler polarization index,
  efficiency trends, calendar heatmap
- **VO2max tracking** — ACSM fitness classification with trend charts
- **Race predictions** — Riegel formula for 5K / 10K / half-marathon / marathon
- **Sleep coaching** — Sleep stage analysis, quality trends, debt tracking,
  bedtime recommendations
- **AI specialist agents** — Sport scientist, sport psychologist, nutritionist,
  and recovery coach with data-driven personalized advice
- **Three AI backends** — `ha_conversation` (default), `ollama` (local), and
  `none` (rules-based)
- **Dashboard pages** — Today, Trends, Training, Zones, Sleep, Coach, Fitness,
  Settings
- **Home Assistant Ingress** — seamless sidebar integration (port 3000/tcp,
  ingress-only)
- **Multi-arch support** — amd64 and aarch64 images via GHCR
- **SQLite storage** — embedded database at `/data/garmincoach.db`
- **s6-overlay service management** — Next.js server and Garmin sync daemon
  managed as s6 services
- **Local build tooling** — `scripts/build-local.sh` for development builds
- **CI/CD pipeline** — GitHub Actions workflow for multi-arch Docker builds
  and tagged releases
- **Comprehensive documentation** — README, DOCS.md (addon UI), CONTRIBUTING.md
- **License** — Apache-2.0 (SPDX-compliant with REUSE)
