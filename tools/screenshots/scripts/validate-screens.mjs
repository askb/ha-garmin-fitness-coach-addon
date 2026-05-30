// SPDX-FileCopyrightText: 2026 Anil Belur <askb23@gmail.com>
// SPDX-License-Identifier: Apache-2.0
//
// Structural validator for the screenshot suite. Confirms that every
// expected route was captured for every project (desktop + mobile) and
// that each PNG is non-trivial in size — a cheap, low-flake gate that
// catches blank pages, error boundaries, and missing routes without
// pixel-diff baselines.
//
// Usage:
//   node scripts/validate-screens.mjs <screenshots-base-dir>
//
// Env:
//   MIN_BYTES   minimum acceptable PNG size (default 5000)
//   PROJECTS    comma-separated projects to require (default "desktop,mobile")

import { readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { ROUTES as ROUTES_MANIFEST } from "../routes.mjs";

const baseDir = process.argv[2] ?? "screenshots";
const minBytes = Number(process.env.MIN_BYTES ?? "5000");
const projects = (process.env.PROJECTS ?? "desktop,mobile")
  .split(",")
  .map((p) => p.trim())
  .filter(Boolean);

// Routes the dashboard spec captures, from the shared manifest that the
// spec (tests/dashboard.spec.ts) also imports — single source of truth, so
// the validator and the capture spec cannot silently drift.
const ROUTES = ROUTES_MANIFEST.map((r) => r.name);
const WINDOWED = new Set(
  ROUTES_MANIFEST.filter(
    (r) => Array.isArray(r.timeframes) && r.timeframes.length > 0,
  ).map((r) => r.name),
);

function fail(msg) {
  console.error(`❌ ${msg}`);
  process.exitCode = 1;
}

// The spec writes to <baseDir>/<YYYY-MM-DD>/<route>-<project>.png. Pick the
// most recent dated subdirectory.
let datedDir;
try {
  const dirs = readdirSync(baseDir, { withFileTypes: true })
    .filter((d) => d.isDirectory() && /^\d{4}-\d{2}-\d{2}$/.test(d.name))
    .map((d) => d.name)
    .sort();
  datedDir = dirs.at(-1);
} catch (err) {
  fail(`Cannot read screenshots dir "${baseDir}": ${err.message}`);
  process.exit(1);
}

if (!datedDir) {
  fail(`No dated capture directory found under "${baseDir}".`);
  process.exit(1);
}

const captureDir = join(baseDir, datedDir);
console.log(`🔎 Validating screenshots in ${captureDir}`);

// Enumerate the capture directory once and reuse it for every route×project
// lookup. Let any unexpected filesystem error propagate so the failure mode
// is clear rather than masquerading as a "Missing capture" message.
const captureFiles = readdirSync(captureDir);

let checked = 0;
let ok = 0;
for (const route of ROUTES) {
  for (const project of projects) {
    // Windowed routes (e.g. fitness) emit per-timeframe files
    // (fitness-7d-desktop.png …) instead of a bare fitness-desktop.png, so
    // match by prefix for those.
    const isWindowed = WINDOWED.has(route);
    const matches = captureFiles.filter((f) =>
      isWindowed
        ? f.startsWith(`${route}-`) && f.endsWith(`-${project}.png`)
        : f === `${route}-${project}.png`,
    );

    checked++;
    if (matches.length === 0) {
      fail(`Missing capture: ${route}-${project}.png`);
      continue;
    }

    let allBigEnough = true;
    for (const m of matches) {
      const size = statSync(join(captureDir, m)).size;
      if (size < minBytes) {
        fail(`${m} is only ${size} bytes (< ${minBytes}) — likely blank/error`);
        allBigEnough = false;
      }
    }
    if (allBigEnough) ok++;
  }
}

console.log(
  `\n📊 ${ok}/${checked} route×project captures valid ` +
    `(min ${minBytes} bytes, projects: ${projects.join(", ")}).`,
);

if (process.exitCode === 1) {
  console.error("\n❌ Screenshot validation failed.");
} else {
  console.log("\n✅ Screenshot validation passed.");
}
