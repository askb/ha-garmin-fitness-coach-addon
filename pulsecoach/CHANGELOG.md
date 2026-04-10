# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.11.1] — 2026-04-11

### Fixed

- **PulseCoach branding in app UI** — Frontend now shows "PulseCoach" instead
  of "GarminCoach" in page titles, navigation menu, onboarding, and settings.
- Scripts use `docker compose exec` instead of hardcoded container names.
- PORT env var supports backward-compatible fallback chain
  (`PORT → PULSECOACH_PORT → GARMINCOACH_PORT`).

## [0.11.0] — 2026-04-13

### ⚠️ Breaking Changes

- **Renamed addon from GarminCoach to PulseCoach** to avoid Garmin trademark
  conflict. Addon slug, image name, and HA sensor entity IDs have all changed
  (`sensor.garmincoach_*` → `sensor.pulsecoach_*`).
- Existing automations referencing old sensor entity IDs must be updated.

### Added

- **Watch Compatibility** section in README — Full/Partial/Basic tiers by
  Garmin watch model (Forerunner, Fenix, Venu, Vivosmart, etc.)
- **Disclaimer** — Explicitly states the addon is unofficial and not affiliated
  with Garmin Ltd.
- **Migration logic** — Automatically copies `/share/garmincoach/` data to
  `/share/pulsecoach/` on first start after upgrade.
- **Addon icon** (`icon.png`) and **logo** (`logo.png`) — teal heartbeat-pulse
  theme with running figure silhouette.

### Changed

- All sensor entity IDs: `sensor.garmincoach_*` → `sensor.pulsecoach_*`
- Addon slug: `garmincoach` → `pulsecoach`
- GHCR image: `garmincoach-addon-{arch}` → `pulsecoach-addon-{arch}`
- s6 service directory: `garmincoach` → `pulsecoach`
- Backup path: `/share/garmincoach/` → `/share/pulsecoach/`

## [0.10.0] — 2026-04-10

### Added

- **HA Automation Blueprints** — 5 ready-to-import blueprints:
  - Low Body Battery Recovery (scene activation)
  - Morning Training Briefing (TTS with ACWR/form/workout)
  - Injury Risk Alert (push notification + optional DND)
  - Training Freshness Reminder (TSB threshold notification)
  - Weekly Training Summary (comprehensive metrics digest)
- **AI Trend Tests** — 21 new unit tests covering workout recommendations,
  injury risk assessment, EWMA constants, and confidence degradation.

### Fixed

- **Release workflow** — per-arch image naming to match HA addon conventions
  (`pulsecoach-addon-{arch}:version`). Removed unnecessary multi-arch
  manifest job since HA handles arch selection via config.json `image` field.
- **Hadolint config** — added `.hadolint.yaml` to suppress non-critical
  Dockerfile lint rules (DL3018, DL3013, DL3042, DL3016, DL3003).

## [0.9.0] — 2026-04-03

### Fixed

- **VO2max Uth overestimation** — replaced flat 15.3 constant with
  age-corrected factor (13.5 for 35-45, 12.5 for 45-55, 11.5 for 55+).
  The original constant was validated only on trained men 21-51 and
  overestimates by 10-28% for older users (PMC8443998, 2021).
- **HRmax formula** — replaced 220-age (SD ±10-12 bpm) with Tanaka
  formula: 208 - 0.7×age (Tanaka 2001, N=18,712).
- **VO2max source priority** — dashboard now shows garmin_official values
  over Uth estimates. Priority: garmin_official > running_pace_hr > cooper
  > uth_method.
- **Race predictions** — now use highest-priority VO2max source within
  90 days instead of most recent date (prevents inflated Uth values from
  producing unrealistic race times).

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
  `sensor.pulsecoach_workout_recommendation` pushed to HA with workout type,
  intensity, duration, HR zone target, and evidence-based rationale. Uses
  ACWR, TSB, body battery, sleep debt, and consecutive hard days to suggest
  rest/recovery/aerobic/quality sessions. Replaces reliance on PulseCoach
  which has a known watch-phone sync desynchronization bug.

## [0.1.0] — 2025-07-09

### Added

- Initial release of the PulseCoach Home Assistant addon
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
- **SQLite storage** — embedded database at `/data/pulsecoach.db`
- **s6-overlay service management** — Next.js server and Garmin sync daemon
  managed as s6 services
- **Local build tooling** — `scripts/build-local.sh` for development builds
- **CI/CD pipeline** — GitHub Actions workflow for multi-arch Docker builds
  and tagged releases
- **Comprehensive documentation** — README, DOCS.md (addon UI), CONTRIBUTING.md
- **License** — Apache-2.0 (SPDX-compliant with REUSE)
