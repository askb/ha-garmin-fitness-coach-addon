<!--
SPDX-FileCopyrightText: 2026 Anil Belur <askb23@gmail.com>
SPDX-License-Identifier: Apache-2.0
-->

# Project Memory — ha-garmin-fitness-coach-addon

Durable facts for Claude Code sessions that are not obvious from the code alone.

## Architecture split

- **This repo (addon)**: Home Assistant addon "PulseCoach" under `pulsecoach/`.
  Ships a Docker image that bundles the companion web app.
- **Companion repo (app)**: `askb/ha-garmin-fitness-coach-app` — pnpm/turbo
  monorepo (Next.js) deployed to Vercel. The addon bundles tagged releases of
  the app (e.g. `chore: bundle app v0.22.0 in the addon image`).
- The path `garmincoach/ha-garmin-fitness-coach-app/` is gitignored — it is a
  local checkout of the app used during development, never committed here.

## Coaching engine

- Deterministic workout recommendation logic lives in
  `pulsecoach/rootfs/app/scripts/ha-notify.py` (`recommend_workout()`).
- It intentionally **replaces** the upstream PulseCoach rest-day suggestion,
  which has a known sync desynchronization bug.
- Decision thresholds are evidence-based (Banister 1975, Hulin 2016,
  Buchheit 2014, Meeusen 2013, Halson 2014, Kellmann 2010) — do not tweak
  thresholds without citing the rationale.
- Tests import the script via `importlib.util.spec_from_file_location` because
  scripts are not an installable package (see `tests/test_coaching_engine.py`).

## Stress Board

- Google Calendar integration: multi-calendar linking is managed in-UI (#263);
  calendar lookback window is configurable (#267).
- `gcal-token.json` at repo root is a **local OAuth token** — gitignored,
  never commit or read it.

## Conventions

- REUSE-compliant: `REUSE.toml` aggregate annotations cover `*.py/md/json/yml`
  and `.github/**`; extension-less files (e.g. `CODEOWNERS`) need inline SPDX
  comments.
- Commits: conventional type prefixes + DCO `Signed-off-by` (git commit -s).
- CI action versions are pinned to exact tags/SHAs (#261).

## Harness

- `evals/` holds standalone smoke evals (run directly, no pytest needed);
  `tests/` holds the pytest suite (7 files, pytest + conftest).
- `.claude/settings.json` has a PreToolUse hook blocking reads/writes of
  `.env*` and `gcal-token.json`.
