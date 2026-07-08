// SPDX-FileCopyrightText: 2026 Anil Belur <askb23@gmail.com>
// SPDX-License-Identifier: Apache-2.0
//
// Stress Board capture + masking regression.
//
// Unlike dashboard.spec.ts (which drives real seeded data), the Stress
// Board is fed here by mocking the `/api/garmin/meeting-stress` endpoint
// with synthetic, deterministic data. That keeps the capture reproducible
// in CI without a linked calendar or real heart-rate history, and — more
// importantly — lets us assert the name-mask toggle actually hides real
// names before the PNG is shared publicly (the whole point of the 🙈
// button). The synthetic people are obviously fictional.

import path from "node:path";
import { expect, test } from "@playwright/test";

const OUT_DIR = process.env.SCREENSHOT_DIR ?? "screenshots";

// Fictional attendees — invented, whimsical full names with NO connection to
// any real person (initials deliberately don't map to real colleagues). Full
// names collapse to initials (WN, BT …); single tokens take 2 chars.
//
// Labels mirror the backend `_label(ridge, n)` thresholds in
// meeting-stress.py (n<3 → "thin data"; ridge≥5 → "prime suspect";
// ridge≥2 → "mild stressor"; ridge≥0.5 → "slightly raises HR";
// -0.5<ridge<0.5 → "neutral"; else "calming") so the demo data stays
// self-consistent with real output.
const MOCK_STATUS = {
  calendar_linked: true,
  events_file: false,
  running: false,
  results: {
    generated: "2026-07-08T07:51:38.000Z",
    people: [
      { attendee: "Waffle Nimbus", n: 2, naive: 3.37, ridge: 0.79, reliability: "low", label: "thin data" },
      { attendee: "Biscuit Thorne", n: 4, naive: 0.71, ridge: 0.62, reliability: "med", label: "slightly raises HR" },
      { attendee: "Pixel Ravenna", n: 3, naive: 1.32, ridge: -0.37, reliability: "med", label: "neutral" },
      { attendee: "Juniper Blaze", n: 3, naive: 1.32, ridge: -0.37, reliability: "med", label: "neutral" },
      { attendee: "Cosmo Flint", n: 5, naive: 0.37, ridge: -0.42, reliability: "high", label: "neutral" },
      { attendee: "Tofu Marlowe", n: 5, naive: 0.37, ridge: -0.42, reliability: "high", label: "neutral" },
      { attendee: "Zephyr Quill", n: 5, naive: 0.37, ridge: -0.42, reliability: "high", label: "neutral" },
      { attendee: "Mango Dupont", n: 4, naive: -0.05, ridge: -1.07, reliability: "med", label: "calming" },
    ],
    meetings: [
      { title: "1:1 sync", attendees: ["Waffle Nimbus"], dbpm: 11.2, z: 1.23, elev: 0.92 },
      { title: "Docs review", attendees: ["Pixel Ravenna", "Juniper Blaze"], dbpm: 3.2, z: 1.15, elev: 1.0 },
      { title: "Weekly standup", attendees: ["Cosmo Flint", "Zephyr Quill", "Tofu Marlowe", "Biscuit Thorne"], dbpm: 2.0, z: 0.37, elev: 1.0 },
      { title: "Weekly standup", attendees: ["Cosmo Flint", "Zephyr Quill", "Tofu Marlowe", "Biscuit Thorne", "Mango Dupont"], dbpm: 2.0, z: 0.35, elev: 0.78 },
      { title: "Docs review", attendees: ["Pixel Ravenna", "Juniper Blaze"], dbpm: 1.9, z: 0.34, elev: 0.87 },
      { title: "Weekly standup", attendees: ["Cosmo Flint", "Zephyr Quill", "Tofu Marlowe", "Biscuit Thorne", "Mango Dupont"], dbpm: -0.6, z: -0.18, elev: 0.43 },
      { title: "Weekly standup", attendees: ["Cosmo Flint", "Zephyr Quill", "Tofu Marlowe", "Biscuit Thorne", "Mango Dupont"], dbpm: -0.6, z: -0.09, elev: 0.48 },
      { title: "Migration collab", attendees: ["Cosmo Flint", "Zephyr Quill", "Tofu Marlowe", "Mango Dupont"], dbpm: -1.0, z: -0.09, elev: 0.4 },
      { title: "Docs review", attendees: ["Pixel Ravenna", "Juniper Blaze"], dbpm: -1.1, z: -0.31, elev: 0.13 },
      { title: "1:1 sync", attendees: ["Waffle Nimbus"], dbpm: -4.4, z: -0.39, elev: 0.29 },
    ],
  },
};

test.describe.configure({ mode: "serial" });

test("stress-board masked capture", async ({ page }, testInfo) => {
  const project = testInfo.project.name; // "desktop" | "mobile"
  // Compute the date at test time, matching dashboard.spec.ts. (Each
  // Playwright project runs in its own worker, so a run spanning midnight can
  // still split desktop/mobile across two dirs — this only keeps the pattern
  // consistent with dashboard.spec.ts, it isn't a hard guarantee.)
  const day = new Date().toISOString().slice(0, 10);

  // Intercept the status poll (GET) and any run trigger (POST). The Stress
  // Board page fetches the app's proxy route `/api/garmin/meeting-stress`
  // (Next.js side), which forwards to the addon backend's `/auth/meeting-stress`
  // (POST) / `/auth/meeting-stress-status` (GET). The glob matches the proxy
  // route (and any `-status` variant) so the capture can never fall through to
  // a real backend. GET returns the leaderboard payload; POST mirrors the
  // backend's {success,message} run-acknowledgement so a stray "run" click
  // can't make the capture flaky.
  await page.route("**/*meeting-stress*", async (route) => {
    const body =
      route.request().method() === "POST"
        ? {
            success: true,
            message: "Meeting stress run started",
            results: "/share/pulsecoach/meeting_stress.json",
          }
        : MOCK_STATUS;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(body),
    });
  });

  await page.goto("/stress-board", { waitUntil: "networkidle" });

  // Unmasked baseline: every fictional attendee AND a known meeting title
  // must actually render first, so the post-mask "count == 0" assertions
  // below can't pass vacuously against rows that never loaded.
  for (const name of MOCK_STATUS.results.people.map((p) => p.attendee)) {
    await expect(page.getByText(name).first()).toBeVisible();
  }
  await expect(page.getByText("1:1 sync").first()).toBeVisible();

  // Toggle to masked mode for a shareable screenshot.
  await page.getByRole("button", { name: /names/ }).click();
  await expect(page.getByRole("button", { name: /masked/ })).toBeVisible();

  // Masking regression: NO fictional name may survive the toggle, and the
  // initials/placeholder must take their place. Checking every attendee (not
  // just a sample) stops a partial-mask regression where only some rows swap.
  for (const name of MOCK_STATUS.results.people.map((p) => p.attendee)) {
    await expect(page.getByText(name)).toHaveCount(0);
  }
  await expect(page.getByText("WN", { exact: true }).first()).toBeVisible();
  // Meeting titles also leak names, so they collapse to "meeting #N".
  await expect(page.getByText("1:1 sync")).toHaveCount(0);
  await expect(page.getByText("meeting #1", { exact: true })).toBeVisible();

  // Freeze animations and strip Next.js dev chrome that would otherwise bake
  // into the PNG (dev indicators/portals). The bottom nav and ThemeToggle are
  // hidden below via targeted heuristics rather than a broad `nav` selector,
  // which could also remove real in-app navigation (same hygiene as
  // dashboard.spec.ts, #142/#150).
  await page
    .addStyleTag({
      content: `
      *, *::before, *::after {
        animation-duration: 0s !important;
        animation-delay: 0s !important;
        transition-duration: 0s !important;
        transition-delay: 0s !important;
        caret-color: transparent !important;
      }
      nextjs-portal,
      [id="__next-build-watcher"],
      [data-next-mark],
      [data-nextjs-toast],
      [data-nextjs-toast-wrapper],
      [class*="dev-indicator" i],
      [id*="dev-indicator" i] { display: none !important; }
    `,
    })
    .catch(() => undefined);
  // Hide the bottom-anchored fixed/sticky nav on the mobile project only
  // (BottomNav is `md:hidden`, so it never renders on desktop). Matching on
  // bottom-anchoring alone — rather than a broad `<nav>`/role heuristic —
  // guarantees only the bottom bar is removed and real header/in-page nav is
  // never touched. Gated to mobile, mirroring dashboard.spec.ts.
  if (project === "mobile") {
    await page
      .evaluate(() => {
        const viewportH = window.innerHeight;
        document.querySelectorAll<HTMLElement>("body *").forEach((el) => {
          const cs = window.getComputedStyle(el);
          if (cs.position !== "fixed" && cs.position !== "sticky") return;
          const rect = el.getBoundingClientRect();
          const anchoredBottom =
            rect.bottom >= viewportH - 8 && rect.bottom <= viewportH + 8;
          if (anchoredBottom) {
            el.style.setProperty("display", "none", "important");
          }
        });
      })
      .catch(() => undefined);
  }
  // The ThemeToggle launcher is position:absolute (the fixed-element walker
  // in dashboard.spec.ts misses it), so target it via its sr-only label.
  await page
    .evaluate(() => {
      document
        .querySelectorAll<HTMLElement>("button .sr-only")
        .forEach((srOnly) => {
          if (srOnly.textContent?.trim() !== "Toggle theme") return;
          const button = srOnly.closest("button");
          const wrapper = button?.parentElement;
          button?.style.setProperty("display", "none", "important");
          wrapper?.style.setProperty("display", "none", "important");
        });
    })
    .catch(() => undefined);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(200);

  const outPath = path.join(OUT_DIR, day, `stress-board-${project}.png`);
  await page.screenshot({
    path: outPath,
    fullPage: true,
    animations: "disabled",
  });
  // Attach to the Playwright report too, matching dashboard.spec.ts. Attach by
  // path (not an in-memory Buffer) so the full PNG isn't held in memory.
  await testInfo.attach(`stress-board-${project}`, {
    path: outPath,
    contentType: "image/png",
  });
});
