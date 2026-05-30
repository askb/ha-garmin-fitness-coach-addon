// SPDX-FileCopyrightText: 2026 Anil Belur <askb23@gmail.com>
// SPDX-License-Identifier: Apache-2.0
//
// Single source of truth for the screenshot route manifest, consumed by
// both the Playwright capture spec (tests/dashboard.spec.ts) and the
// structural validator (scripts/validate-screens.mjs) so the two cannot
// silently drift when a route is added or removed.
//
// `wait` tunes the post-load delay per route (charts render slower than
// the landing page). `timeframes`, when set, captures one PNG per
// DateRangeSelector tab label (e.g. fitness-7d-desktop.png) instead of a
// single default-state capture.

export const ROUTES = [
  { name: "home", path: "/", wait: 4000 },
  { name: "training", path: "/training", wait: 8000 },
  {
    name: "fitness",
    path: "/fitness",
    wait: 8000,
    timeframes: ["7d", "14d", "28d", "90d", "180d", "1y"],
  },
  { name: "activities", path: "/activities", wait: 6000 },
  { name: "sleep", path: "/sleep", wait: 5000 },
  { name: "trends", path: "/trends", wait: 8000 },
  { name: "zones", path: "/zones", wait: 6000 },
  { name: "hrv", path: "/hrv", wait: 5000 },
  { name: "vitals", path: "/vitals", wait: 5000 },
  { name: "insights", path: "/insights", wait: 4000 },
  { name: "coach", path: "/coach", wait: 4000 },
  { name: "validation", path: "/validation", wait: 6000 },
];
