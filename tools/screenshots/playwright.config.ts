// SPDX-FileCopyrightText: 2026 Anil Belur <askb23@gmail.com>
// SPDX-License-Identifier: Apache-2.0

import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright config for PulseCoach screenshot capture.
 *
 * BASE_URL defaults to the dev Next.js port (`http://localhost:3000`).
 * For a locally-running addon container, point it at the exposed port:
 *
 *   BASE_URL=http://localhost:3001 pnpm screenshot
 *
 * The runner is single-threaded so the produced PNGs land in a stable
 * filename pattern (no shard suffixes), which is important for AI diffing
 * and human review.
 */
export default defineConfig({
  testDir: "./tests",
  timeout: 90_000,
  retries: 1,
  workers: 1,
  reporter: [["list"], ["html", { open: "never", outputFolder: "report" }]],

  use: {
    baseURL: process.env.BASE_URL ?? "http://localhost:3000",
    trace: "retain-on-failure",
    // We capture our own screenshots in the spec; don't let Playwright
    // also write "test-failed-1.png" alongside them.
    screenshot: "off",
    video: "off",
    colorScheme:
      (process.env.PULSECOACH_THEME as "light" | "dark" | undefined) ?? "dark",
  },

  outputDir: "./artifacts",

  projects: [
    {
      name: "desktop",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1440, height: 900 },
        deviceScaleFactor: 2,
      },
    },
    {
      name: "mobile",
      use: {
        ...devices["iPhone 14 Pro"],
      },
    },
  ],
});
