// SPDX-FileCopyrightText: 2026 Anil Belur <askb23@gmail.com>
// SPDX-License-Identifier: Apache-2.0

import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright config for PulseCoach screenshot capture.
 *
 * `BASE_URL` is the addon's Next.js port. To make it reachable from
 * outside HA, enable the host-port mapping for `3000/tcp` in the
 * addon's Network settings (Settings → Add-ons → PulseCoach → Network)
 * and restart the addon. The URL is then `http://<haos-host>:3000`,
 * e.g. `http://homeassistant.local:3000`.
 *
 * For a locally-running container:
 *   docker run -p 3000:3000 ghcr.io/askb/pulsecoach-addon-amd64:latest
 *   BASE_URL=http://localhost:3000 npm run screenshot
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
