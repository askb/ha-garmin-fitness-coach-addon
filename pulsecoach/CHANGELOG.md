# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.17.5] - 2026-05-28

### Fixed

- Bundle app v0.17.4 so HAOS containers include the timezone picker,
  adherence activity fallback, and coach chat post-processing fixes.
- Bump Dockerfile `APP_REF` from v0.17.1 to v0.17.4; v0.17.3 still built
  the stale app ref despite addon release notes.

## [0.17.3] - 2026-05-28

### Fixed

- HA actions poller now queries the Drizzle-managed `recommendation_audit`
  table using snake_case identifiers.

### Changed

- Bundle app v0.17.2 with the timezone-aware dashboard greeting fix.

## [0.17.2] - 2026-05-28

### Changed

- Bundle app v0.17.1 with UI polish (Accept/Skip/Defer layout, adherence empty-state fallback,
  duplicate headline removed) and LLM hardening (ordered-list renumbering, activity slug humanization).

## [0.17.1] - 2026-05-28

### Fixed

- Garmin overnight body/skin temperature now syncs into `daily_metric.skin_temp`
  (previously always NULL). Affects the Vitals card, readiness, baselines, sleep
  analysis. Requires a watch with the wrist-temperature sensor (Venu 2 Plus,
  Venu 3, Fenix 7/8, Epix 2/Pro, Forerunner 265/965/970, Enduro 3, Tactix 7+).
  A one-time backfill re-syncs the last 90 days on first startup of v0.17.1.

## [0.17.0] - 2026-05-28 — AI-native coach loop

### Added

- HA action layer polls `RecommendationAudit` and fires Home Assistant
  Supervisor events for recommendation decisions, low readiness,
  completed sessions, and missed sessions (addon #166).
- Release gate workflow verifies the app repository main branch is green
  before addon releases proceed (addon #165).
- Packaged app now builds from the app repo `v0.17.0` tag; see the app
  repository changelog for the full AI-native coach loop details.

### Changed

- Coach loop is now rules-first; LLM only frames explanations
  (test-enforced in the app repo).

## [0.17.0-dev.1] — 2026-05-27

### Added

- **ha-actions.py** polls `RecommendationAudit` rows and fires Home
  Assistant events for recommendations, low readiness, completed
  sessions, and missed sessions. Processing is cursor-based so restarts
  do not replay old audit rows.
- **Addon config** adds `ha_events_enabled`,
  `low_readiness_threshold`, and `missed_session_grace_min` options for
  the new action layer.
- **s6-overlay** starts `pulsecoach-ha-actions` as a longrun service
  alongside the existing PulseCoach services.

## [0.16.31] — 2026-05-22

Diagnostics + capture-pipeline improvements after a sparse-VO2max
investigation that turned out to be expected behaviour.

### Fixed

- **garmin-sync.py** `sync_vo2max` no longer silently swallows
  per-date exceptions from the Garmin `get_max_metrics` API.
  Failures are now grouped by exception class and reported in a
  summary line, e.g.
  `Garmin max-metrics: 8 dates queried, 1 returned data, 7 threw —
  HTTPError: 4 (e.g. '429 Too Many Requests')`, so a real outage
  is no longer indistinguishable from a 'no qualifying runs'
  window. Happy-path output is also clearer:
  `Garmin max-metrics: 8 dates queried, 1 returned VO2max readings`.

### Tooling

- **screenshots** `dashboard.spec.ts` now captures every
  `DateRangeSelector` window (`7d` / `14d` / `28d` / `90d` / `180d`
  / `1y`) on `/fitness`, emitting one PNG per label
  (`fitness-7d-desktop.png`, etc). Catches windowed-render
  regressions the previous single-state capture missed — e.g. a
  28d chart rendering empty while 90d renders a graph.

## [0.16.30] — 2026-05-21

Race-condition hotfix for `metrics-compute.py` constraint setup.

### Fixed

- **metrics-compute.py** `ensure_advanced_metric_table` and
  `ensure_readiness_score_table` no longer crash with
  `DuplicateTable: relation "advanced_metric_user_date_unique"
  already exists` when two computes race past the `IF NOT EXISTS`
  guard. The DO blocks now swallow `duplicate_table`,
  `duplicate_object`, and `unique_violation` so the SQL is
  genuinely idempotent. v0.16.29's `.recompute_status` lock made
  the race rare but did not close the TOCTOU window.

## [0.16.29] — 2026-05-21

Refresh-pipeline overhaul: dashboards now light up automatically
after sync without a page reload.

### Auto-recompute after sync

- **garmin-sync.py** chains `metrics-compute.py --once` at the end
  of every sync run (manual or scheduled), so derived rows
  (`readiness_score`, `advanced_metric`, `daily_athlete_summary`)
  always reflect the freshly synced `daily_metric` + `activity`
  rows. No more clicking "Recompute metrics" to see Home update.
- A `.recompute_status` file lock prevents the post-sync chain
  from overlapping with the s6 periodic compute loop or a manual
  `/auth/recompute` invocation. The s6 loop now writes the same
  marker so all three paths cooperate.
- Chained recompute logs to `/data/metrics-compute.log` (rotated
  on each chain) instead of `/dev/null`, so failures are
  diagnosable.

### Picked up from app

- **Settings invalidates React Query caches** when sync OR
  recompute transitions running → idle. Polls `/auth/sync` and
  `/auth/recompute-status` every 3 s while a job is in flight,
  30 s otherwise. End-to-end UX: tap **Sync now** → sync writes
  rows → recompute auto-runs → caches invalidate → every
  dashboard refetches and renders the new values (app#203).

## [0.16.28] — 2026-05-21

Closes the 2026-05-21 screenshot review loop. Four app polish fixes
picked up from `main` plus a README tidy.

### Picked up from app

- **Zones page charts render again** — Weekly Time in Zones,
  Training Polarization, Monthly Zone Distribution, Pace/HR
  Efficiency, and Weekly Training Volume by Sport were silently
  empty because the chart components consumed raw tRPC payloads
  whose shape didn't match Recharts. Normalised the data sources
  and fixed the efficiency date axis (app#201).
- **Insights "This Week" card no longer inverts** — replaced
  hardcoded `bg-zinc-900` / `border-zinc-800` / `bg-zinc-800/60`
  with theme-aware `bg-card` / `border` / `bg-muted` tokens so the
  weekly summary matches the rest of the page in both light and
  dark themes (app#202).
- **Multi-metric Trend stress line is red** — stress and sleep both
  used `#3b82f6` (blue) and were indistinguishable; stress now uses
  rose-500 (`#f43f5e`) (app#200).
- **Zones legend wraps on mobile** — the Zone 5 chip no longer
  clips on ~375 px viewports, and Pace/HR efficiency subtitle uses
  explicit `+` / `-` signs (app#199).

### Docs

- Drop `activities-desktop.png` from the README screenshot gallery
  — the descriptive copy stays.

## [0.16.27] — 2026-05-20

Closes the 2026-05-20 multi-agent screenshot review loop. Twelve app
fixes plus a screenshot-pipeline harden against floating launchers /
FABs that survived the previous corner walker.

### Picked up from app

- **Trends multi-metric chart now renders data lines** instead of a
  blank grid for HRV / Readiness / Sleep / Stress (app#187).
- **Performance Management Chart contrast fixed** — CTL/ATL/TSB lines
  are now legible on dark theme with widened strokes and a dynamic
  y-domain (app#188).
- **Notable Changes row label cleaned up** — the raw `Week-over-week:`
  prefix is gone (app#189).
- **Vitals "Baseline" no longer duplicated** in the Skin Temperature
  no-data row (app#190).
- **Home readiness ring** no longer word-breaks `confidence` on
  narrow viewports (app#191).
- **Insights mobile "THIS WEEK" widget** uses an explicit dark
  background so the metric colors stay readable (app#192).
- **Vitals SpO2 badge clarified** — the "Low" / "Critical" label now
  carries an absolute-threshold tag so it doesn't contradict the
  "+x% vs baseline" deviation pill (app#193).
- **Validation Sleep Lab measurement type** uses a Lucide SVG icon
  instead of the inconsistent 😴 emoji (app#194).
- **Coach mobile persona tabs** — all four labels (Sport Scientist,
  Psychologist, Nutritionist, Recovery) now fit at 390px without the
  Recovery tab clipping off-screen (app#195).
- **Sleep "Actual vs Need" chart** now renders the Need reference
  line on mobile (it was desktop-only before) (app#196).
- **Sleep Stages chart** plots all 14 nights again — the renderer
  was coercing legitimate null durations to zero and skipping
  rows (app#197).
- **Home workout recommendation** is regenerated when Garmin syncs
  shift readiness into a new zone, eliminating the
  "High readiness / Moderate workout" contradiction (app#198).

### Screenshot pipeline

- Strip edge-anchored floating launchers (coach FAB, monitor / help
  icon, third-party chat bubbles) regardless of corner anchoring.
  The previous walker only caught corner-anchored ≤72×72 indicators;
  the new walker catches anything ≤128×128 within 32px of *any*
  viewport edge and narrower than 25% of the viewport width, so the
  full-width header / nav / footer stay visible (#150).

## [0.16.26] — 2026-05-19

Picks up four more app fixes from the second 2026-05-19 multi-agent
screenshot review plus a screenshot-pipeline harden.

### Picked up from app

- **Insights "Readiness" no longer shows two different numbers on the
  same screen** (app
  [#173](https://github.com/askb/ha-garmin-fitness-coach-app/pull/173)).
  AI Insights had been quoting yesterday's cached readiness while
  Daily Insights computed today's; both now use today's row. When
  today's readiness hasn't been computed yet, the daily summary shows
  "Daily Status — Readiness pending" instead of synthesizing a fake
  50/100, and a critical condition is never masked by neutral tone.
- **Training page Load Focus and 42-day trend charts render
  correctly** (app
  [#175](https://github.com/askb/ha-garmin-fitness-coach-app/pull/175)).
  Load Focus chart had a 0-px width inside a flex column without
  `w-full`. The 42-day Training Strain and Body Stress charts now
  detect all-null data and show a graceful empty state instead of an
  invisible flat line. On mobile, the time-range pills sit cleanly
  below the section header.
- **Activities page subtitle no longer clips behind the menu icon**
  (app
  [#172](https://github.com/askb/ha-garmin-fitness-coach-app/pull/172)).
  Same `pl-12` fix class as #167.
- **Coach persona tab labels visible on phones ≤400px** (app
  [#174](https://github.com/askb/ha-garmin-fitness-coach-app/pull/174)).
  Removes `max-[400px]:hidden` from the label so Sport Scientist /
  Psychologist / Nutritionist / Recovery names are always visible.

### Addon-side

- **Capture pipeline strips Next.js dev/build portal and any small
  corner-anchored indicator badge** (addon
  [#147](https://github.com/askb/ha-garmin-fitness-coach-addon/pull/147)).
  Adds named CSS killers for `nextjs-portal`, `[data-nextjs-toast]`,
  etc, plus a belt-and-braces DOM walk that hides any fixed/sticky
  ≤72×72px element pinned within 16px of a viewport corner with no
  substantial text content. Re-adds iframe a11y selectors that had
  been accidentally dropped.

## [0.16.25] — 2026-05-19

Picks up four app fixes from the 2026-05-19 multi-agent screenshot
review plus two addon-side capture-pipeline fixes.

### Picked up from app

- **AI coach no longer shows raw sport ids or stale VO2max** (app
  [#164](https://github.com/askb/ha-garmin-fitness-coach-app/issues/164)).
  `prettySport()` now strips `_v2`, `_legacy`, `_alt`, `_new`, `_old`,
  `_deprecated`, `_raw` suffixes before they reach the LLM context, and
  `getVO2maxHistory.latestBest` now reads from the same unwindowed
  last-30 pool the /coach page uses, so the two surfaces can no longer
  disagree.
- **Home Load/HRV sub-labels are readable** (app
  [#165](https://github.com/askb/ha-garmin-fitness-coach-app/issues/165)).
  QuickStats sub-labels now force `text-zinc-400` via Tailwind's
  important modifier so sibling zone-color classes can't bleed through
  via `currentColor`.
- **Sleep-debt chart Y-axis no longer clips negative values** (app
  [#166](https://github.com/askb/ha-garmin-fitness-coach-app/issues/166)).
  YAxis width bumped from 35 to 40 so `-2.5h` fits.
- **Validation page title no longer crashes into the back-arrow** (app
  [#167](https://github.com/askb/ha-garmin-fitness-coach-app/issues/167)).
  Both the `<h1>` and its subtitle now share `pl-12` padding.

### Addon-side

- **Screenshot capture strips mobile bottom nav reliably** (addon
  [#141](https://github.com/askb/ha-garmin-fitness-coach-addon/issues/141)).
  `tools/screenshots/tests/dashboard.spec.ts` now DOM-walks for any
  fixed/sticky element whose bottom edge is anchored to the viewport
  (or whose tag/role/class matches nav patterns) and force-hides it,
  instead of relying on brittle CSS selectors.
- **Capture run no longer renders the UserWay accessibility widget**
  (addon
  [#142](https://github.com/askb/ha-garmin-fitness-coach-addon/issues/142)).
  Same spec injects CSS killers for `userway`, `ally-toolbar`, `acsb`,
  and accessibility iframes; `playwright.config.ts` also uses a fresh
  `mkdtempSync` user-data-dir per run so injected extensions never
  leak between captures.

## [0.16.24] — 2026-05-18

Picks up seven screenshot-QA fixes from the app
([#162](https://github.com/askb/ha-garmin-fitness-coach-app/pull/162),
[#163](https://github.com/askb/ha-garmin-fitness-coach-app/pull/163))
addressing UI hierarchy, data correctness, and AI-coach polish issues
surfaced by the 2026-05-18 multi-agent screenshot review.

### Picked up from app
- **AI coach `*` bullets render properly** (app
  [#153](https://github.com/askb/ha-garmin-fitness-coach-app/issues/153)).
  Leading whitespace before block markers (`* `, `### `, `1. `) no
  longer prevents matching, and single-asterisk italics (`*foo*`) —
  which LLMs emit far more often than the underscore form — now
  render as italics instead of literal asterisks.
- **AI coach VO2max number matches the dashboard** (app
  [#154](https://github.com/askb/ha-garmin-fitness-coach-app/issues/154)).
  The coach narrative and the /fitness "Current VO2max" hero card
  now share a single picker
  (`packages/api/src/lib/vo2max.ts::pickBestVO2maxEstimate`) so they
  can never disagree on which estimate is "best" again.
- **Internal sport ids stop leaking to coach text** (app
  [#155](https://github.com/askb/ha-garmin-fitness-coach-app/issues/155)).
  `Tennis_v2` etc. are now humanised before being included in the
  coach's system prompt.
- **Insights "This Week" reports 7 days, not 8** (app
  [#157](https://github.com/askb/ha-garmin-fitness-coach-app/issues/157)).
  `trends.getSummary` had an off-by-one against an inclusive lower
  bound; now reports exactly the requested window length.
- **Activities list filters Garmin's phantom walks** (app
  [#158](https://github.com/askb/ha-garmin-fitness-coach-app/issues/158)).
  The <10 min / <500 m filter already used by the home carousel
  (`activity.getRecent`) is now applied to `activity.list` too, so
  the /activities page is no longer dominated by auto-detected
  incidental walks.
- **Home Quick-Stats hierarchy** (app
  [#161](https://github.com/askb/ha-garmin-fitness-coach-app/issues/161)).
  The status sub-label on each mini-card (e.g. "High Load",
  "Optimal") is dimmed to `text-zinc-400` so the metric value stays
  the dominant visual element, matching the #148 insights polish.
- **Zones heatmap stops clipping on mobile** (app
  [#160](https://github.com/askb/ha-garmin-fitness-coach-app/issues/160),
  regression of #142). Month labels and the day-grid now share one
  `overflow-x-auto` scroll container instead of the labels being
  absolute-positioned in an unconstrained parent.

## [0.16.23] — 2026-05-18

Picks up four UI/data-integrity fixes from the app and ships them via
the addon's startup `drizzle-kit push`, which now materialises nine
previously-missing unique indexes (silently dropped by drizzle-kit
when declared via the plain-object form).

### Picked up from app
- **Journal save now works** (app
  [#150](https://github.com/askb/ha-garmin-fitness-coach-app/issues/150)).
  Saving a journal entry was failing with PostgreSQL `42P10` —
  "there is no unique or exclusion constraint matching the ON
  CONFLICT specification" — because nine schema tables declared their
  table-level uniqueness via a plain `{ name, columns, unique: true }`
  literal that `drizzle-kit push` silently dropped. Converted all
  nine tables (DailyMetric, ReadinessScore, TrainingStatus,
  JournalEntry, SessionReport, Intervention, AdvancedMetric,
  AthleteBaseline, AiInsight) to the canonical `uniqueIndex(name).on(...)`
  form. On first start after upgrading, `drizzle-kit push --force`
  creates the missing unique indexes; subsequent journal saves
  succeed.
- **Track-cycle UI hidden for male profiles** (app
  [#151](https://github.com/askb/ha-garmin-fitness-coach-app/issues/151)).
  The 🩸 Track cycle accordion on /journal no longer appears when
  `profile.sex === "male"`, and `menstrualPhase` is scrubbed from the
  save payload when the section is hidden.
- **Power & CP page no longer three empty cards** (app
  [#149](https://github.com/askb/ha-garmin-fitness-coach-app/issues/149)).
  When the user has no power-meter activities, /power renders a
  single explainer hero ("⚡ Power meter required") instead of three
  identical empty-state cards. The `activity.list` query now also
  returns `avgPower` / `normalizedPower` so users with a power meter
  but no computed CP see their data populate correctly.
- **Insights "This Week" colour hierarchy** (app
  [#148](https://github.com/askb/ha-garmin-fitness-coach-app/issues/148)).
  Sub-labels in the four tiles dimmed from `text-zinc-300` to
  `text-zinc-400` so they stop outshining the bold metric values
  they describe.



Fixes recent workouts disappearing from the app's home page for users
east of UTC (AEST in particular).

### Fixed
- **Activity start-time stored as UTC** (#133). The sync was writing
  Garmin's TZ-naive `startTimeLocal` into a `timestamptz` column, which
  Postgres re-parses in the session's TimeZone (UTC by default in HA's
  postgres image). For AEST (UTC+10) users a 9 AM morning workout was
  timestamped 10 hours in the future, and the app's
  `lte(startedAt, new Date())` filter then silently hid it until the
  wall clock caught up.
  - `_normalize_started_at()` now prefers `startTimeGMT` and stamps
    it with an explicit `+00:00` offset.
  - One-time backfill re-stamps all existing activity rows from
    `raw_garmin_data->>'startTimeGMT'`. Idempotent + guarded by a
    marker file; force-replay with `PULSECOACH_REBACKFILL_STARTED_AT=1`.
  - 8 new unit tests + 1 upsert wiring test.

### Picked up from app v0.2.13 (askb/ha-garmin-fitness-coach-app#125)
- Widened activity future-row filter to a 26-hour horizon so a future
  TZ regression fails loudly (visibly-future row) instead of silently
  hiding data.

## [0.16.21] — 2026-05-17

CI follow-up + picks up app v0.2.12.

### Fixed
- **SBOM release-asset upload** (#131). The `SBOM & Security Scan` job
  in `release.yaml` was failing on tag pushes with "Resource not
  accessible by integration" because the job had `contents: read` but
  `anchore/sbom-action@v0` auto-attaches the generated SBOM to the
  GitHub Release. Grant `contents: write` so the SBOM lands on the
  release page.

### Picked up from app v0.2.12 (askb/ha-garmin-fitness-coach-app#123)
- **Home action card no longer contradicts the HRV tile.** The
  suggestion would unconditionally assert "your HRV of Xms is below
  baseline" whenever readiness was low, even when the HRV component
  was actually in the optimal range (real cause was sleep debt /
  training load). Gated on the engine's HRV component score (<40
  threshold, same as `generateExplanation()`).
- **Training Status tile no longer shows "— · as of <date>".** When
  `garmin_training_status` is NULL the sublabel now reads
  `unavailable` without an unrelated readiness-level timestamp.

## [0.16.20] — 2026-05-16

Diagnostic logging + activity-sync resilience.

### Fixed
- **Manual sync errors no longer disappear.** `/auth/sync` previously
  routed both stdout and stderr to `/dev/null`, so any failure
  (network, schema, garminconnect list-wrap regression, single
  malformed activity row) silently aborted the whole sync with no
  trace. Output now streams to `/data/garmin-sync.log` (rotated to
  `.log.1` on each run). New `GET /auth/sync-log` endpoint returns
  the tail of the log for in-app diagnostics.
- **Activity sync is now resilient to bad data.** `sync_activities`
  used to abort the entire batch on the first exception (e.g. an
  activity with a missing `activityType` dict or a Garmin response
  shaped as `[[{...}]]` instead of `[{...}]`). The loop now:
    - Defensively unwraps `[[...]]` list-of-list responses (same
      pattern that bit Firstbeat in v0.16.18).
    - Skips non-dict / id-less entries with a logged warning instead
      of crashing.
    - Wraps each row in its own try/except so a single malformed
      activity rolls back only itself; the rest of the batch still
      commits.
    - Logs the full exception type+message for every fetch failure.

### Tests
- `tests/test_garmin_sync.py`: 3 new regression tests for
  `sync_activities` covering the list-of-list unwrapping, non-dict
  entries, and per-row failure isolation.

## [0.16.19] — 2026-05-16

Second pass on the Garmin Native (Firstbeat) card. After v0.16.18
restored the `training_readiness` sync, live inspection on HAOS
revealed two remaining issues:

1. Recovery time (hours) was still NULL because `get_training_status`
   returns `mostRecentTrainingStatus: null` for users whose watch
   hasn't yet computed Firstbeat status (typically requires ~7 days
   of structured activity). However the value we actually want for
   the card — `recoveryTime` in minutes — is already inside the
   `get_training_readiness` payload.
2. When `get_training_status` does populate, the meaningful fields
   live under `mostRecentTrainingStatus.latestTrainingStatusData.
   <deviceId>.{trainingStatus, recoveryTime, ...}` — a nested DTO
   shape the previous code never inspected. So even users with a
   computed status would have seen empty columns.

### Fixed
- **`sync_training_readiness` now also writes `garmin_recovery_hours`**
  by converting `recoveryTime` (minutes) from the readiness payload.
  Uses `COALESCE` so a later run that hits an emptier payload can't
  blank out a recovery value previously stored for the same day.
- **`sync_training_status` parses the nested DTO shape**
  (`mostRecentTrainingStatus.latestTrainingStatusData.<deviceId>`)
  for status / load focus / recovery time, with fallbacks to the
  flat shapes used by older library versions. Recovery time lookup
  now uses an explicit `is not None` check so a fully-recovered
  `recoveryTime == 0` isn't discarded as "missing". Updates use
  `COALESCE` so a partial response can't blank out columns the
  readiness sync populated earlier in the run.

After this release, the Firstbeat card should show Recovery hours
even for users without computed Firstbeat training status.

## [0.16.18] — 2026-05-16

Hot-fix for the Garmin Native (Firstbeat) card showing only em-dashes
on every field except HRV, even though the watch had clearly synced.

### Fixed
- **Training readiness and training status no longer sync** because the
  upstream `garminconnect` Python library changed its response shape
  from `dict` to `list[dict]` (single-element list wrapping the same
  payload). Our sync code called `.get("score")` directly on the
  response and raised `AttributeError: 'list' object has no attribute
  'get'`, which was caught by the broad `except Exception` and logged
  as "Training readiness unavailable for &lt;date&gt;", leaving
  `garmin_training_readiness`, `garmin_training_status`,
  `garmin_recovery_hours`, and `garmin_training_load` columns NULL on
  every `daily_metric` row.

  Added a `_first_dict()` normaliser in `garmin-sync.py` that accepts
  either a dict (legacy) or a non-empty `list[dict]` (current) and
  returns the first usable dict, or `None` otherwise. Wrapped both
  `client.get_training_readiness(...)` and
  `client.get_training_status(...)` call sites.

  After this release the Firstbeat card will populate on the next
  scheduled sync (no manual backfill required — the orchestrator
  re-reads the last 7 days every cycle).

### Tests
- 8 new unit tests in `tests/test_garmin_sync.py::TestFirstDict`
  pinning the dict-passthrough / list-unwrap / empty / scalar /
  None-fallback behaviour.

## [0.16.17] — 2026-05-16

Picks up app `v0.2.10` with three correlated fixes for the next-morning
Garmin publish lag, where today's `daily_metric` row exists (activity
counts + steps land hours after a workout) but HRV / readiness / RHR
remain `null` until the watch syncs the health snapshot the following
morning.

### Fixed
- **Activity times rendered in UTC instead of the profile timezone**
  inside the HAOS addon container. `Date.toLocaleString()` without an
  explicit `timeZone` resolves to the container's TZ (UTC). The
  activities list, activity detail, and dashboard "Good morning" date
  now thread the profile's IANA timezone through every
  `Intl.DateTimeFormat` call via a new `useUserTimezone()` hook +
  `formatDateInTz` / `formatTimeInTz` helpers.
- **Garmin Native (Firstbeat) card showed em-dashes for every field**
  on the morning of a long workout — today's row was populated from
  the activity feed (steps, intensity minutes) but the Firstbeat
  fields (VO2max, training status, etc.) hadn't been written yet.
  `garmin.getTrainingSummary` now computes `latestNonNull` per field
  across the most recent rows, mirroring how the HRV trend already
  worked.
- **Readiness card contradicted itself** — engine explanation said
  *"HRV 0.9 SD above baseline"* while the action below it said
  *"HRV data is unavailable"*. Root cause: the engine's
  `generateExplanation` already walked back to find the most recent
  non-null HRV, but the router's `computeDataQuality` strictly checked
  today's row. Both `computeDataQuality` and `buildActionSuggestion`
  now accept an 8-day metric window — "good" if value is ≤ 3 days old,
  "stale" 4–7 days, "missing" only beyond 7 days. Six regression tests
  pin the new behaviour.

## [0.16.16] — 2026-05-15

### Fixed
- **Training & Fitness pages still crashing with `RangeError: Invalid
  time value` after v0.16.15** — root cause was deeper than the
  Date-serialization defense added in `0.2.8`. The Alpine `nodejs=~22`
  package in the HA base image ships a **minimal-ICU** build without
  the en-CA CLDR locale data, so
  `Intl.DateTimeFormat('en-CA', { year, month, day }).format(date)`
  silently returns en-US `MM/DD/YYYY` instead of `YYYY-MM-DD`. That
  malformed string broke `shiftIsoDay`, which is called for every
  `aggregateDailyLoads` invocation (Training Loads + Training Status).
  `dayInTimezone` now uses `formatToParts()` (locale-independent
  because each field is named) and assembles `YYYY-MM-DD` by hand.
  Picks up app `v0.2.9`.

## [0.16.15] — 2026-05-15

### Fixed
- **Training & Fitness pages were returning 500s for ACWR / Training
  Status cards** — `analytics.getTrainingLoads` and
  `analytics.getTrainingStatus` crashed in production with
  `RangeError: Invalid time value` from superjson's Date serializer.
  Both endpoints now emit primitives only (ISO strings, numbers,
  strings) and filter Activity rows with malformed `startedAt`
  defensively at the router boundary. Picks up app `v0.2.8`.

## [0.16.14] — 2026-05-15

### Fixed
- **Settings > "Last sync" was showing the wrong timestamp** —
  previously sourced from the Garmin token directory's mtime, which
  only changes on (re)login and never reflects actual data sync. The
  endpoint now reads a dedicated `.last_sync` file written by
  `garmin-sync.py` at the end of every successful sync run; the
  legacy mtime path is retained as a fallback for fresh installs
  where the first sync hasn't completed yet.

## [0.16.13] — 2026-05-15

### Added
- **WHOOP-style Daily Outlook card** (app v0.2.7) — the home page now
  features a Target Strain band directly under your Readiness ring.
  Given today's readiness, PulseCoach recommends a 0-21 day-strain
  band (e.g. `14–18` when you're Primed, `0–6` when recovery is
  poor), with a zone-tinted scale viz, midpoint marker, label
  (All-out / Vigorous / Moderate / Light / Recovery) and a
  plain-language rationale. Personalises ±2 toward your median
  chronic strain when ≥7 sessions are available. New engine helper
  `computeTargetStrain` with sport-science citations
  (Foster 2001, Halson 2014, Soligard 2016, Hulin 2016) and 7 new
  unit tests.

### Fixed
- **Sleep Debt Last 7 Days chart** — was rendering all dots at zero
  despite a visible cumulative debt badge. The chart now computes
  per-day debt on the fly from `sleepNeed − actualSleep` using the
  coach's recommended nightly need as the baseline, instead of
  reading a `DailyMetric.sleepDebtMinutes` column that was never
  written by the ETL.
- **Coach AI sport codes** — recent activity sent to the LLM is now
  prettified (`Tennis_v2` → `Tennis`, `trail_running` →
  `Trail Running`) so the AI no longer parrots raw Garmin sport
  identifiers back at you.
- **Trends Multi-Metric Trend chart** — Stress can now be toggled
  alongside Readiness / Sleep / HRV. The backend already exposed it;
  only the chart was missing the overlay.

## [0.16.12] — 2026-05-15

### Fixed
- **UI data-consistency pass 5** (app v0.2.6) — two issues spotted in
  v0.16.11 screenshots:
  - **Zones Y-axis '3000001%' artefact** — Training Polarization and
    Monthly Zone Distribution charts now use explicit
    `ticks=[0, 25, 50, 75, 100]` plus `allowDataOverflow`. Pass-3's
    rotated-label removal cleared one source of garbage, but the
    auto-tick generator still produced a colliding extra tick at the
    chart edge. Explicit ticks guarantee 5 clean labels.
  - **Insights '44.8' rendering as '4 4.8'** — the metric chip on
    the Overreaching insight had adjacent identical digits kerning
    apart at 10pt. Added `tabular-nums` className for monospaced
    digit widths.

## [0.16.11] — 2026-05-14

### Fixed
- **UI data-consistency pass 4** (app v0.2.5) — two Fitness page fixes:
  - **Garmin VO2 Max chart — window-empty fallback**: Garmin
    Firstbeat only emits VO2max readings after qualifying outdoor
    runs (12+ min with HR + GPS), which in practice means one
    reading every 1-2 weeks. Selecting a 7d or 14d window often
    returned zero rows and showed an unhelpful empty-state. The
    chart now falls back to your most recent readings (last 60,
    no window filter) and displays a friendly note explaining
    the situation. Title switches to "Garmin VO2 Max — last N
    reading(s)" in fallback mode.
  - **VO2max Y-axis decimal rendering**: previous `toFixed(1)`
    tick formatter produced visually dropped decimal points at
    10pt SVG font (e.g. `297` instead of `29.7`). Replaced with
    `allowDecimals={false}` + integer-rounded domain on both the
    Garmin chart and the UTH chart so ticks render crisply.

## [0.16.10] — 2026-05-14

### Fixed
- **UI data-consistency pass 3** (app v0.2.4) — 4 remaining issues
  caught by the v0.16.9 screenshot review:
  - **Hamburger overlap on desktop**: page-title left padding is
    now unconditional (`pl-12`) instead of `pl-12 sm:pl-0`. The
    fixed-position hamburger button is present at every
    breakpoint, so Activities / Coach / etc. titles were still
    being clipped at ≥640px.
  - **Zones \"00000001\" Y-axis artefact**: replaced the rotated
    `%` axis label with a per-tick `tickFormatter` suffix on both
    the Training Polarization and Monthly Zone Distribution
    charts. The rotated label was overlapping the `100` tick and
    rendering as garbage.
  - **Coach AI VO2max mismatch**: the Sport Scientist agent now
    picks its VO2max by the same source priority as the dashboard
    hero card (Garmin Firstbeat > Pace+HR > Cooper > UTH), so the
    chat narrative no longer quotes `28.7 ml/kg/min` while the
    Fitness page reads `32.5`.
  - **Correlation insight snake_case leak**: the engine now maps
    raw field-name keys (`sleep_duration`, `next_day_hrv`,
    `resting_hr`, …) through a label table before they're
    interpolated into the insight sentence, so Trends →
    Correlation Insights cards read \"sleep duration and readiness
    are strongly positively correlated…\" instead of
    \"sleep_duration and readiness …\".

## [0.16.9] — 2026-05-14

### Fixed
- **UI data-consistency pass 2** (app v0.2.3) — 13 issues from screenshot review:
  - **Hamburger overlap**: `pl-12 sm:pl-0` on page headers so the
    top-left menu button stops clipping page titles on mobile
    (Activities, Coach, Insights, Sleep, Trends, Zones, etc).
  - **YAxis "100" clipped**: bumped width on sleep/trends/zones charts
    so the top tick label is fully visible.
  - **Training Strain ticks**: explicit `[0,5,10,15,20]` ticks, no more
    auto-generated `82.5` fractional values on a 0-21 domain.
  - **Vitals baseline labels**: moved to `insideTopRight` so they no
    longer sit on top of the dashed reference line.
  - **Future-dated activities**: server-side filter `startedAt <= now`
    so a "Walking — Fri May 15" never appears at the top of the list
    for users in positive-UTC timezones.
  - **Sleep charts direction**: Stages / Score / Actual-vs-Need / Debt
    / Timing now render chronologically (oldest left → newest right).
    Also fixed Sleep Debt stat reading the oldest entry instead of
    the newest.
  - **Activities sport-code leakage**: pure-numeric `subType` strings
    (Garmin internal enum codes like `163`) are no longer rendered as
    tiny chips next to "Yoga" / "Walking".
  - **Trends correlation labels**: snake_case keys (`sleep_duration`,
    `next_day_hrv`, `resting_hr`) now mapped to friendly names with
    a `prettyMetric()` Title-Case fallback.
  - **Trends Avg Stress**: computed from `DailyMetric.stressScore`
    instead of hard-coded `—`.
  - **VO2max consistency**: hero card now selects by source priority
    (Garmin Firstbeat > Pace+HR > Cooper > UTH), matching the Race
    Predictions card. Adds a "via …" provenance badge.
  - **Insights debug dump**: replaced monospace `HRV: 18 | TSB: -14 |
    ACWR: 1.41 …` line with friendly chip pills.
  - **Insights stuck loading**: skeleton now gated on _every_ query
    being pending instead of _any_ query, so a single lagging child
    query no longer blocks the entire page.
  - **Readiness debug text**: stale `Buchheit composite: N/100
    (hrv=…)` strings stored in the DB are now sanitized at read-time
    into clean zone-keyed explanations; cached rows self-heal on
    next recompute.

## [0.16.8] — 2026-05-14

### Fixed
- **UI data-consistency pass 1** (app v0.2.2):
  - PMC chart x-axis: adaptive ~8-tick step so 180-day windows no longer
    render labels mashed together (`02-1302-2002-27...`).
  - ACWR gauge: falls back to the last point on the PMC chart series when
    the analytics endpoint returns null. The gauge and the chart can no
    longer disagree.
  - Daily Strain y-axis: integer `tickFormatter` so the [0,21] domain
    stops rendering as `444`.
  - All three VO2max charts on the Fitness page now use an explicit
    `toFixed(1)` y-axis formatter and a wider tick column, so values
    like `29.5` no longer drop their decimal point (`297, 317, 337`).
  - Performance Comparison no longer claims "top 90%" in green for
    below-median VO2max; it now reads "bottom X%" in amber when below
    the population median.
- **Garmin Training Summary card** — renamed to "Garmin Native
  (Firstbeat)" with a one-line caption explaining the fields require a
  Forerunner 245+ / Fenix 6+. This clarifies why the card may show
  em-dashes while the home-page Readiness score (our computed Buchheit
  composite) shows real numbers for the same day.
- **`/validation` page** — was the only screen rendering in light mode
  against a dark app shell. Converted all raw light-mode utilities to
  dark-aware semantic Tailwind tokens.

## [0.16.7] — 2026-05-14

### Fixed
- **Analytics 500 on malformed activity dates** — `analytics.getTrainingLoads`
  and `analytics.getTrainingStatus` no longer return HTTP 500 when any
  Activity row in the 42-day window has a NaN `startedAt`. The
  `dayInTimezone` helper now short-circuits to a sentinel date, and the
  daily-load aggregator skips bad rows so they don't pollute ACWR / CTL /
  ATL math. (app PR #103)

### Docs
- **Screenshot tooling for HAOS** — `tools/screenshots/` now leads with
  the HAOS port-exposure workflow (Settings → Add-ons → PulseCoach →
  Network → enable `3000/tcp`) instead of the previous `pnpm dev`
  instructions, which didn't apply to users running only the addon.
  Fixes wrong port (`3001` → `3000`) in `.env.example`. (#114)

## [0.16.6] — 2026-05-13

### Added
- **HA sensor surface** — expose Garmin recovery hours, HRV, and load focus
  as Home Assistant sensors via the ha-notify bridge (#110).
- **HACS install docs** — README now documents adding the repo as a HACS
  custom repository (#105). Earlier incorrect instructions removed (#106).
- **Download tracking + release badges** — README badges show GHCR pulls
  and release counts (#104).

### Tests
- Phase 3 coverage for `sync_training_*` jobs and ha-notify sensor
  helpers (#111).
- Metrics-compute readiness scoring + load fetching covered (#109).

### Maintenance
- Bump `github/gh-aw` 0.67.4 → 0.73.0 (#79, #102, #107).
- Bump `node` 22-alpine → 26-alpine (#81, #108).
- Bump `softprops/action-gh-release` 2 → 3 (#80).

## [0.16.5] — 2026-04-19

### Fixed
- Hotfix following 0.16.4 release plumbing; container build pipeline
  hardening.

## [0.16.4] — 2026-04-17

### Fixed
- **Insights upsert failing** — `ai_insight` table was missing the unique
  constraint on `(user_id, date, insight_type)` needed for ON CONFLICT upsert.
  Startup now explicitly creates the index and deduplicates existing rows.

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
