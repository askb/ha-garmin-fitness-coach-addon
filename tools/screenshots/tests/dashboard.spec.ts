// SPDX-FileCopyrightText: 2026 Anil Belur <askb23@gmail.com>
// SPDX-License-Identifier: Apache-2.0

import path from "node:path";
import { test } from "@playwright/test";

/**
 * Routes to capture. Add or remove freely — the spec runs once per route.
 *
 * `wait` lets you tune the post-load delay per route (charts on
 * /training take longer to render than the landing page).
 */
const ROUTES: { name: string; path: string; wait?: number }[] = [
  { name: "home", path: "/", wait: 4000 },
  { name: "training", path: "/training", wait: 8000 },
  { name: "fitness", path: "/fitness", wait: 8000 },
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

const OUT_DIR = process.env.SCREENSHOT_DIR ?? "screenshots";

function timestampedDir(): string {
  return new Date().toISOString().slice(0, 10);
}

test.describe.configure({ mode: "serial" });

for (const route of ROUTES) {
  test(`screenshot ${route.name}`, async ({ page }, testInfo) => {
    const project = testInfo.project.name; // "desktop" | "mobile"
    const isMobile = project === "mobile";
    const day = timestampedDir();
    const fileName = `${route.name}-${project}.png`;
    const outPath = path.join(OUT_DIR, day, fileName);

    await page.goto(route.path, { waitUntil: "networkidle" });

    // Charts (Recharts) animate in over ~300-500ms after data arrives,
    // and several pages prefetch via tRPC then re-render. A fixed delay
    // is the most robust signal without adding test-ids to the app.
    await page.waitForTimeout(route.wait ?? 5000);

    // For the coach page, the assistant streams a response token-by-token
    // and previous capture runs grabbed the page mid-paragraph, leaving
    // half-formed sentences in the README. Wait for any visible streaming
    // indicator (the cursor sentinel or a `[data-streaming]` marker) to
    // disappear before continuing. Best-effort — never fails the run.
    if (route.name === "coach") {
      await page
        .waitForFunction(
          () =>
            !document.querySelector("[data-streaming='true']") &&
            !document.querySelector(".animate-pulse-cursor"),
          undefined,
          { timeout: 10_000 },
        )
        .catch(() => undefined);
      // Extra settle so the markdown renderer commits its final layout.
      await page.waitForTimeout(1500);
    }

    // Scroll back to the top so full-page captures begin at the page
    // header rather than wherever the user (or `waitUntil: networkidle`)
    // left the viewport. Important on long routes like /training and
    // /coach (#138).
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.waitForTimeout(200);

    // Hide any noisy elements that drift run-to-run (date pickers default
    // to "today", which makes diffs noisy) and — on mobile — release the
    // fixed bottom nav so `fullPage` captures don't bake it on top of the
    // content rows for every screen (#138). The selector list is
    // best-effort — missing nodes don't fail the run.
    await page
      .addStyleTag({
        content: `
          [data-noisy="true"] { visibility: hidden !important; }
          /* Kill cursor blinkers and animated spinners for crisp PNGs. */
          *, *::before, *::after {
            animation-duration: 0s !important;
            animation-delay: 0s !important;
            transition-duration: 0s !important;
            caret-color: transparent !important;
          }
          ${
            isMobile
              ? `
          /* Release the sticky bottom nav so it lands once at the end of
             the full-page screenshot instead of being baked in over every
             card. The fixed-position element overlaps any scrolled-past
             content in fullPage screenshots otherwise. */
          nav[data-bottom-nav], .bottom-nav, [class*="BottomNav"] {
            position: relative !important;
            bottom: auto !important;
          }
          `
              : ""
          }
        `,
      })
      .catch(() => undefined);

    // Settle once more after the style injection so the layout reflows
    // before the screenshot fires.
    await page.waitForTimeout(200);

    await page.screenshot({
      path: outPath,
      fullPage: true,
      animations: "disabled",
    });

    // Attach to the HTML report so reviewers can flip through quickly.
    await testInfo.attach(`${route.name}-${project}`, {
      path: outPath,
      contentType: "image/png",
    });
  });
}
