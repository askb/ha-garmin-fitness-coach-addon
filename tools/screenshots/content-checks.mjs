// SPDX-FileCopyrightText: 2026 Anil Belur <askb23@gmail.com>
// SPDX-License-Identifier: Apache-2.0
//
// Single source of truth for the *content* gate consumed by
// tests/content.spec.ts. Where routes.mjs + validate-screens.mjs only
// assert that a screenshot file exists and is non-trivial in size, this
// manifest encodes what must actually be *rendered* on each screen, so
// regressions that still produce a large PNG — empty charts (#257) and
// physiologically-impossible values (#258) — fail CI instead of slipping
// through to a human eyeballing screenshots.
//
// Recharts geometry class names are stable across 2.x/3.x:
//   bar   → g.recharts-bar-rectangle  (one per datum per stacked series)
//   area  → path.recharts-area-area
//   pie   → path.recharts-pie-sector
//   radar → path.recharts-radar-polygon
//   line  → path.recharts-line-curve
//   dot   → path.recharts-scatter-symbol / circle.recharts-dot
//
// The #257 bug was that Bar/Area/Pie/Radar geometry is created only after
// Recharts' entry-animation frame fires; under React 19 concurrent
// rendering that frame could be dropped on chart-heavy pages, so the
// geometry never materialised even though axes, legends and the
// surrounding card all painted. Asserting that the *animation-gated*
// geometry exists (count > 0, non-zero box) is therefore the precise
// regression test, and the fix (`isAnimationActive={false}`) is what
// makes it pass deterministically.

export const GEOMETRY_SELECTORS = {
  bar: ".recharts-bar-rectangle",
  area: ".recharts-area-area",
  pie: ".recharts-pie-sector",
  radar: ".recharts-radar-polygon",
  line: ".recharts-line-curve",
};

// Each entry: the route to visit, how long to let charts settle, and the
// minimum count of each animation-gated geometry kind that MUST be
// present.
//
// Scope rationale — these three routes are the ones that (a) were the
// concrete #257 victims or share its exact rendering path AND (b) carry
// Bar/Area geometry that the seed reliably populates for *all four*
// personas (athlete, recreational, beginner, detrained) from 90 days of
// data, so the gate is deterministic rather than coupled to data volume:
//
//   zones    — "Weekly Time in Zones" + "Weekly Training Volume by Sport"
//              stacked bars (the original empty-chart report).
//   sleep    — "Sleep Stages · Last 14 Nights" stacked bars (also blank in
//              the QA capture; 90 nights of sleep guarantee bars).
//   training — Performance Management Chart area + "Daily Strain/Stress —
//              Last 14 Days" bars (14 days always present).
//
// Routes deliberately NOT gated here: fitness/hrv/vitals/trends render
// Line/Scatter/dot geometry (not the animation-gated Bar/Area the #257 fix
// touched) and/or depend on sparse single-metric data, so a geometry-count
// assertion there would be flaky without testing the actual regression.
//
// `require` counts are intentionally the conservative floor (>=1): the bug
// produced exactly zero painted bars/areas, so any positive count proves
// the animation-gated geometry materialised. `isAnimationActive={false}`
// makes that deterministic.
export const CHART_CONTENT_CHECKS = [
  { name: "zones", path: "/zones", wait: 6000, require: { bar: 1 } },
  { name: "sleep", path: "/sleep", wait: 5000, require: { bar: 1 } },
  { name: "training", path: "/training", wait: 8000, require: { bar: 1, area: 1 } },
];

// /validation renders the Engine-vs-Garmin reconciliation tables. Readiness
// and VO2max both live on a 0–100 scale (READINESS_RANGE / VO2MAX_RANGE in
// packages/api/src/router/data-quality.ts). #258 was that Garmin sometimes
// emits values outside that range (e.g. 130, 530) and the table reported
// them as "Match", inflating the agreement %. The invariant we gate on:
// any Garmin/Engine value outside [0, 100] MUST be flagged "Out of range"
// (status ⚪ invalid) — never Match / Minor / Diverged.
export const VALIDATION_CHECK = {
  name: "validation",
  path: "/validation",
  wait: 6000,
  range: { min: 0, max: 100 },
  // Status label that an out-of-range row must carry (from
  // RVC_STATUS_LABEL in validation/page.tsx).
  invalidLabel: "Out of range",
};
