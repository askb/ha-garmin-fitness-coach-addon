# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.8.0] — 2026-04-03

### Fixed

- **Smart workout recommendations** — replaced unconditional "Rest Day"
  for poor readiness with evidence-based decision logic. Complete rest now
  only prescribed for critical signals (ACWR >1.5, TSB <-25, Body Battery
  <20, sleep debt >3h). Otherwise suggests Active Recovery with
  sport-specific guidance.
- **VO2max trend filtering** — low-confidence VO2max sources (Uth method)
  excluded from trend calculations to prevent non-workout-day data from
  skewing improving/declining detection.

### Added

- **RecoveryContext type** — ACWR, TSB, body battery, sleep debt, and
  stress score passed from database to coaching engine for evidence-based
  workout modulation.
- **Active Recovery workout type** — new workout category with structured
  warmup/main/cooldown phases, sport-specific descriptions (running:
  conversational jog, cycling: easy spin, strength: mobility work).
- **Comprehensive vitest coverage** — VO2max trend source filtering and
  coaching modulation tests (20+ test cases covering all critical triggers).

### References

- Hulin BT et al. (2016) Br J Sports Med — ACWR >1.5 injury risk
- Meeusen R et al. (2013) Eur J Sport Sci — overreaching indicators
- Mah CD et al. (2011) Sleep — sleep debt impact on performance
- Barnett A (2006) Sports Med — active recovery modalities
- Uth N et al. (2004) Eur J Appl Physiol — VO2max HR ratio accuracy

## [0.7.0] — 2026-04-03

### Fixed

- **GHCR image pull support** — added `image` field to `config.json` so HA
  Supervisor pulls pre-built images from GHCR instead of building the
  Dockerfile locally on the HAOS device. Eliminates the need for manual SSH
  rebuilds and reduces install/update time from 10-20+ minutes to ~30 seconds.
- **Per-date VO2max fallback** — changed Uth method fallback from
  all-or-nothing to per-date; only computes estimates for dates missing
  `garmin_official` data, preventing overwrites when the Garmin API partially
  fails.
- **Stale Dockerfile label** — updated `io.hass.version` from `0.2.0` to
  match actual release version.

### Added

- **AI workout recommendation sensor** — new
  `sensor.garmincoach_workout_recommendation` pushed to HA with workout type,
  intensity, duration, HR zone target, and evidence-based rationale. Uses
  ACWR, TSB, body battery, sleep debt, and consecutive hard days to suggest
  rest/recovery/aerobic/quality sessions. Replaces reliance on Garmin Coach
  which has a known watch-phone sync desynchronization bug.

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
