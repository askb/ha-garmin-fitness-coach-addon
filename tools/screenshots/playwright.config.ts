// SPDX-FileCopyrightText: 2026 Anil Belur <askb23@gmail.com>
// SPDX-License-Identifier: Apache-2.0

import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

import { defineConfig, devices } from "@playwright/test";

// Use a freshly-created throwaway user-data-dir for every run so the
// browser profile cannot carry over any user-installed extension UI
// from a developer's everyday Chromium profile (#142). The directory
// is left behind in the OS tmp tree; the host's tmpfile reaper handles
// cleanup.
const ISOLATED_PROFILE = mkdtempSync(
  path.join(tmpdir(), "pulsecoach-screenshot-profile-"),
);

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
    // Launch Chromium with extensions disabled and an isolated, empty
    // user-data-dir so user-installed browser extensions don't bake
    // overlay icons / toolbars into the captured PNGs (#138, #142).
    launchOptions: {
      args: [
        "--disable-extensions",
        "--disable-component-extensions-with-background-pages",
        `--user-data-dir=${ISOLATED_PROFILE}`,
        "--no-first-run",
        "--no-default-browser-check",
      ],
    },
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
        // iPhone 14 Pro viewport on Chromium instead of WebKit. The
        // `devices['iPhone 14 Pro']` preset defaults to WebKit, which
        // pulls in `libjpeg-turbo` + `gstreamer1.0-libav` system deps
        // that Fedora and other non-Ubuntu hosts don't ship by default
        // (Playwright is officially supported only on Ubuntu). Chromium
        // produces visually equivalent mobile screenshots and is the
        // browser we already validate desktop in.
        ...devices["Pixel 7"],
        viewport: { width: 393, height: 852 },
        deviceScaleFactor: 3,
        isMobile: true,
        hasTouch: true,
        userAgent:
          "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) " +
          "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 " +
          "Mobile/15E148 Safari/604.1",
      },
    },
  ],
});
