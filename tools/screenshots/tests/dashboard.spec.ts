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
    // to "today", which makes diffs noisy) and strip any third-party
    // accessibility / chat / analytics widgets that may have injected
    // themselves into the host page (#142).
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
          /* Strip common host-injected overlay widgets (a11y bars, chat
             bubbles, feedback launchers) that aren't part of the app
             but slip past --disable-extensions because they're shipped
             as npm packages on the page itself (#142). */
          [id*="accessibility" i][id*="widget" i],
          [class*="accessibility" i][class*="widget" i],
          [id*="ally-toolbar" i],
          [class*="ally-toolbar" i],
          [id*="userway" i],
          [class*="userway" i],
          [id*="acsb" i],
          [class*="acsb" i],
          [aria-label*="accessibility menu" i],
          [aria-label*="open accessibility" i],
          /* Strip Next.js dev/build indicators that can survive even when
             NODE_ENV=production if any portal or status overlay slips in
             (the small monitor/screen icon that surfaced inside cards on
             mobile in the 2026-05-19 capture batch). */
          nextjs-portal,
          [id="__next-build-watcher"],
          [data-next-mark],
          [data-nextjs-toast],
          [data-nextjs-dialog-overlay],
          [data-nextjs-toast-wrapper],
          button[data-nextjs-data-runtime-error-collapsed],
          /* Generic small fixed-position dev/feedback launchers anchored
             to a viewport corner (~64px or smaller, position fixed). The
             CSS-only fallback for anything we missed by name. */
          [class*="dev-indicator" i],
          [class*="DevIndicator" i],
          [id*="dev-indicator" i] {
            display: none !important;
            visibility: hidden !important;
          }
        `,
      })
      .catch(() => undefined);

    // Belt-and-braces: walk for any small fixed/sticky element pinned to
    // a viewport corner that looks like an indicator badge (≤72×72px,
    // not a nav). Catches the Next.js build watcher portal and any other
    // status-indicator overlays we can't enumerate by name (#142).
    await page
      .evaluate(() => {
        const vpW = window.innerWidth;
        const vpH = window.innerHeight;
        document.querySelectorAll<HTMLElement>("body *").forEach((el) => {
          const cs = window.getComputedStyle(el);
          if (cs.position !== "fixed" && cs.position !== "sticky") return;
          const rect = el.getBoundingClientRect();
          // Small badge-sized element pinned within 16px of a viewport
          // corner. Skip if it spans most of the viewport (that's a nav,
          // handled separately) or contains substantial text.
          const isSmall = rect.width <= 72 && rect.height <= 72;
          const nearLeft = rect.left <= 16;
          const nearRight = rect.right >= vpW - 16;
          const nearTop = rect.top <= 16;
          const nearBottom = rect.bottom >= vpH - 16;
          const inCorner =
            (nearLeft || nearRight) && (nearTop || nearBottom);
          const tag = el.tagName.toLowerCase();
          // Don't nuke the app's own header/nav children — the matcher
          // already excludes anything larger than 72×72.
          if (isSmall && inCorner && tag !== "nav") {
            el.style.setProperty("display", "none", "important");
          }
        });
      })
      .catch(() => undefined);

    // Mobile-only: locate any element whose computed position is fixed
    // or sticky AND whose bottom edge is anchored to the viewport, then
    // hide it before fullPage capture. This is far more robust than a
    // hand-maintained selector list — the previous CSS-based fix (#140)
    // missed the actual nav DOM and left the bar baked over every row
    // of every mobile screenshot (#141).
    if (isMobile) {
      await page
        .evaluate(() => {
          const viewportH = window.innerHeight;
          document.querySelectorAll<HTMLElement>("body *").forEach((el) => {
            const cs = window.getComputedStyle(el);
            if (cs.position !== "fixed" && cs.position !== "sticky") return;
            const rect = el.getBoundingClientRect();
            // Element is anchored to (or sits within 8px of) the bottom
            // of the viewport — almost certainly a bottom nav / toast /
            // floating action bar.
            const anchoredBottom =
              rect.bottom >= viewportH - 8 && rect.bottom <= viewportH + 8;
            const looksLikeNav =
              el.tagName === "NAV" ||
              /\b(nav|bottom|tabbar|tab-bar)\b/i.test(el.className) ||
              el.getAttribute("role") === "navigation" ||
              el.hasAttribute("data-bottom-nav");
            if (anchoredBottom || looksLikeNav) {
              el.style.setProperty("display", "none", "important");
            }
          });
        })
        .catch(() => undefined);
    }

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
