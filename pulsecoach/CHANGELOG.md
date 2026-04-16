# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.16.3] — 2026-04-16

### Fixed
- **Refresh Insights button now always produces results** — added an always-fire
  "Daily Status Snapshot" insight that summarizes readiness, ACWR, form, sleep,
  HRV, and SpO2 even when no warning rules trigger.

### Added
- **SpO2 alert rule** — critical at <92%, warning when <95% and below 14d baseline.
- **Respiration rate alert rule** — fires when RR exceeds baseline by 2+ brpm.
- Fixed insightType conflicts preventing same-day upsert collisions between rules.

## [0.16.2] — 2026-04-16

### Added
- **Vitals in readiness scoring** — SpO2 (8%), respiration rate (7%), and skin
  temperature (7%) now contribute to the Buchheit-style readiness composite.
  All three use 14-day rolling baseline deviation scoring.
- **New HA sensors** — `sensor.pulsecoach_spo2` (%), `sensor.pulsecoach_respiration_rate`
  (brpm), and `sensor.pulsecoach_skin_temp` (°C) pushed to Home Assistant.

### Changed
- Readiness weight rebalance: HRV 25%, Sleep 20%, Load 15%, RHR 10%,
  Stress 8%, SpO2 8%, RR 7%, Skin Temp 7% (was HRV 35%, Sleep 25%, Load 20%, RHR 10%, Stress 10%).

## [0.16.1] — 2026-04-15

### Fixed
- **Today tab scores showing 0/100** — metrics-compute.py now writes component
  breakdowns (sleep, HRV, load, stress, resting HR) to the readiness_score table.
  Previously only the composite score was stored; individual components were discarded.
  Existing data is backfilled automatically on the next metrics-compute run.

## [0.16.0] — 2026-04-15

### Added
- **HRV Trend Analysis page** — dedicated page with daily HRV, 7d/14d rolling averages, baseline, CV%, and recovery status indicator (app)
- **Shared Date Range Selector** — reusable component across fitness, training, sleep, and HRV pages with preset buttons (app)
- **Recompute Metrics button** — on-demand metrics recompute from Settings; new `/auth/recompute` endpoint in addon auth server
- **Enhanced Export** — Advanced Metrics and HRV CSV exports; JSON backup schema bumped to v1.1 (app)
- **HRV in bottom nav** — replaced Zones with HRV Analysis for quick access (app)

### Fixed
- Sleep page date presets capped at 90d (matching API max)
- Export HRV lookup optimized from O(n²) to O(n) using Map pre-indexing
- Recompute API route now propagates upstream HTTP status codes
- DateRangeSelector type safety improved (readonly presets, no unsafe casts)
- HRV CV% division-by-zero guard when mean is 0
- Proper null check for baseline in recovery status logic

## [0.15.4] — 2026-04-15

### Fixed
- **Refresh Insights button** — clicking "Refresh Insights" now correctly updates existing insights instead of silently skipping (changed `onConflictDoNothing` → `onConflictDoUpdate` in app)
- Refreshed insights are marked as unread with updated severity, title, body, and action suggestions

## [0.15.3] — 2026-04-14

### Fixed
- **readiness_score UNIQUE constraint missing** — Drizzle creates the table without the `UNIQUE(user_id, date)` constraint that `ON CONFLICT` requires; added `CREATE UNIQUE INDEX IF NOT EXISTS` to ensure it exists

## [0.15.2] — 2026-04-14

### Fixed
- **readiness_score schema mismatch** — metrics-compute.py column names (`readiness_zone`, `readiness_explanation`) didn't match Drizzle schema (`zone`, `explanation`); aligned all references
- **Conditional migration** — uses `information_schema.columns` check to safely rename only if old columns exist
- **Matview aliases** — `rs.zone AS readiness_zone`, `rs.explanation AS readiness_explanation`

## [0.15.1] — 2026-04-14

### Fixed
- **readiness_score table schema bug** — INSERT referenced column `readiness_score` which matched the table name, causing PostgreSQL error; renamed column to `score`
- **daily_athlete_summary matview** — updated to alias `rs.score AS readiness_score`; matview was failing to create on v0.14.0
- **Migration** — auto-renames column for users upgrading from v0.14.0

## [0.15.0] — 2026-04-14

### Added
- **Garmin weight/body composition sync** — auto-syncs weight (kg) and body fat % from Garmin daily
- **New HA sensor**: `sensor.pulsecoach_weight` with body fat attribute
- **Strava OAuth2 integration** — sync activities from Strava as secondary data source
  - Config options: `strava_client_id`, `strava_client_secret`, `strava_refresh_token`
  - Activities stored alongside Garmin with `source_platform` tracking
  - TRIMP computation for Strava activities (Banister simplified)
  - Incremental sync (7-day window) after initial full sync
- Weight and body fat columns in materialized view for dashboard access

### Changed
- Data quality score now includes weight as a quality indicator
- Activity table extended with `strava_activity_id` and `source_platform` columns

## [0.14.0] — 2026-04-14

### Added

- **Garmin Training Readiness sync** — Syncs Garmin's native Training
  Readiness score (0-100) and 6-factor breakdown (HRV status, sleep,
  recovery time, acute load, stress history, Body Battery) via
  `get_training_readiness()` API.

- **Garmin Training Status sync** — Syncs Training Status
  (Productive/Peaking/Overreaching/Recovery/Unproductive), Load Focus
  distribution (low/high aerobic + anaerobic %), and recovery time
  via `get_training_status()` API.

- **Readiness HA sensor** — New `sensor.pulsecoach_readiness` (0-100)
  with zone and source attributes. Prefers Garmin native readiness,
  falls back to Buchheit composite computation.

- **Training Status HA sensor** — New `sensor.pulsecoach_training_status`
  showing Garmin's official training status with recovery hours and
  load focus attributes.

- **Buchheit readiness engine** — Computed readiness score using weighted
  HRV (35%), sleep (25%), Body Battery (20%), resting HR (10%), and
  stress (10%) with 14-day rolling baseline normalization.

- **Enhanced workout recommendation** — Coaching engine now uses
  readiness score and Garmin training status for decisions. Low
  readiness (<25) and OVERREACHING status trigger rest; PEAKING and
  PRODUCTIVE enable quality sessions.

- **15 coaching engine tests** — Comprehensive test coverage for rest
  triggers, active recovery, quality sessions, aerobic workouts, and
  edge cases.

### Changed

- Workout recommendation rationale now includes readiness score context
- Recovery signal threshold includes readiness < 40 as additional signal
- Quality session eligibility considers readiness >= 70 and Garmin
  PEAKING/PRODUCTIVE status alongside TSB and Body Battery

## [0.13.0] — 2026-04-14

### Added

- **Materialized view** — `daily_athlete_summary` PostgreSQL materialized
  view joins `daily_metric`, `advanced_metric`, `readiness_score`, and
  `vo2max_estimate` into a 60-column single source of truth. Refreshed
  non-concurrently after every sync and compute cycle.
- **Data quality flags** — Each synced day now gets a `data_quality`
  percentage (0-100) based on key field presence (steps, HR, sleep, HRV,
  stress, SpO2). Available in the matview for UI display.
- **Drift detection** — `metrics-compute.py` logs a WARNING if computed
  metrics lag behind synced data by more than 1 day.
- **Test suite** — 12 new metrics-compute tests covering EWMA properties,
  decay constants, injury risk levels, and edge cases. 90-day synthetic
  fixture data for deterministic validation.
- **Docker cachebust fix** — Replaced GitHub API `ADD` (403 rate-limited)
  with `CACHEBUST` build arg across all CI/release workflows.

### Changed

- **TRIMP formula** — Upgraded from simplified HR-ratio formula to Banister
  (1991) with resting HR delta ratio: `duration × ΔHR × e^(k × ΔHR)`.
  More accurate for aerobic activities where HR is closer to resting.
- **Matview startup order** — Created after schema push + restore + migrations
  (not before) for deterministic first-boot behavior.
- **ha-notify fallback** — Catches specific `psycopg2.errors.UndefinedTable`
  instead of blanket exception; logs unexpected errors to stderr.

### Fixed

- **Cursor leak** — `_refresh_matview()` now uses `finally` block to ensure
  cursor is always closed, even on error.
- **REFRESH CONCURRENTLY** — Switched to standard `REFRESH MATERIALIZED VIEW`
  inside PL/pgSQL function (CONCURRENTLY cannot run inside transaction blocks).

## [0.12.1] — 2026-04-15

### Added

- **Materialized view** — New `daily_athlete_summary` PostgreSQL materialized
  view joins `daily_metric`, `advanced_metric`, `readiness_score`, and
  `vo2max_estimate` into a single 60-column source of truth. Automatically
  created on startup and refreshed after every sync and metrics compute cycle.
- **Matview refresh** — `garmin-sync.py` and `metrics-compute.py` both call
  `refresh_daily_athlete_summary()` (CONCURRENTLY) so downstream queries
  always see fresh, consistent data without manual intervention.
- **Fallback queries** — `ha-notify.py` tries the matview first, falls back
  to separate table queries if the view doesn't exist yet (first-boot safety).

## [0.12.0] — 2026-04-14

### Added

- **Timezone configuration** — New `user_timezone` option in addon config
  (e.g., `Australia/Brisbane`). All date boundary calculations now use
  the user's local timezone instead of UTC, fixing sync/display mismatches
  for non-UTC users.
- **Sensor attributes** — All 7 HA sensors now include `timezone` and
  `last_computed` timestamp in their attributes for debugging.
- **Timezone tests** — New test cases for sleep time extraction and
  timezone-aware date boundaries.

### Fixed

- **Sleep time extraction** — `_extract_sleep_time()` now uses explicit
  `utcfromtimestamp()` for Garmin Local timestamps instead of system-dependent
  `fromtimestamp()`, ensuring correct wall-clock time regardless of container TZ.
- **Date boundary drift** — Sync, metrics compute, and HA notification services
  all use the configured timezone for "today" calculations, preventing
  off-by-one date errors in UTC+10 and similar timezones.

## [0.11.4] — 2026-04-13

### Fixed

- **AI agent cannot query SpO2 data (#73)** — `garmin-sync.py` now fetches
  SpO2 (pulse oximetry) and respiration rate from the Garmin Connect API and
  writes them to the `daily_metric` table. SpO2 cascades through three sources:
  dedicated `get_spo2_data()` API → `stats.avgSpo2` → `sleep.averageSpO2Value`.
  Respiration cascades: `get_respiration_data()` → `stats.respirationAvg`.

## [0.11.2] — 2026-04-11

### Fixed

- **Garmin sync authentication broken** — `garminconnect` 0.3.x dropped the
  `garth` library dependency and changed to a native token format
  (`garmin_tokens.json`). The sync script now supports both formats and
  auto-migrates legacy garth OAuth tokens on first run.
- **DATABASE_URL pointing to SQLite** — `config.json` environment block had
  `file:/data/pulsecoach.db` instead of the PostgreSQL connection string.
  HA Supervisor injects these as Docker ENV vars, overriding the s6 script.
- **`garth` added as explicit dependency** in Dockerfile to support users with
  legacy token files generated by `generate-garmin-tokens.py`.
- Token restore from `/share/` backup now checks for both native and legacy
  token formats.

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
