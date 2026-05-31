// SPDX-FileCopyrightText: 2026 Anil Belur <askb23@gmail.com>
// SPDX-License-Identifier: Apache-2.0
//
// Content gate for the PulseCoach dashboard. This is the automated
// counterpart to the screenshot capture: instead of writing a PNG and
// trusting a human to notice an empty chart or an impossible number, it
// asserts on the live, seeded DOM so those regressions fail CI.
//
// Covers two classes of bug found by manual screenshot review and which
// the size-only validator (scripts/validate-screens.mjs) could not catch:
//
//   #257  Stacked Bar/Area charts rendered empty (geometry never painted)
//         while the surrounding card, axes and legend still produced a
//         large PNG. We assert the animation-gated geometry exists and has
//         a non-zero box.
//
//   #258  Garmin readiness/VO2max values outside the 0–100 scale (e.g.
//         130, 530) were reported as "Match" in the validation table. We
//         assert every rendered value is in range, or else flagged
//         "Out of range".
//
// Runs against the same container the capture job seeds (BASE_URL), so it
// needs no extra fixtures. Desktop project only — these are data
// assertions, not viewport-specific, so there is no value in running them
// twice.

import { expect, test } from "@playwright/test";
import {
  CHART_CONTENT_CHECKS,
  GEOMETRY_SELECTORS,
  VALIDATION_CHECK,
} from "../content-checks.mjs";

test.describe.configure({ mode: "serial" });

// These are content assertions, not viewport assertions. The
// `validate:content` npm script pins `--project=desktop`; this in-test
// guard is a belt-and-braces no-op there but prevents accidental
// double-execution if the spec is ever run without a project filter.
function desktopOnly(testInfo) {
  test.skip(
    testInfo.project.name !== "desktop",
    "content assertions run on desktop only",
  );
}

// Called after the test body has already navigated to the route. Waits for
// Recharts to mount and paint before assertions fire — never navigates.
async function settleCharts(page, waitMs) {
  await page.waitForLoadState("networkidle").catch(() => undefined);
  // At least one chart surface should mount on these routes; give it a
  // generous budget before the fixed settle so slow tRPC prefetches land.
  await page
    .waitForSelector(".recharts-surface", { timeout: 20_000 })
    .catch(() => undefined);
  // Scroll the full page so any below-the-fold chart card that defers
  // mounting until it scrolls into view gets a chance to render.
  await page
    .evaluate(async () => {
      const step = 600;
      for (let y = 0; y <= document.body.scrollHeight; y += step) {
        window.scrollTo(0, y);
        await new Promise((r) => setTimeout(r, 200));
      }
      window.scrollTo(0, 0);
    })
    .catch(() => undefined);
  await page.waitForTimeout(waitMs);
}

for (const check of CHART_CONTENT_CHECKS) {
  test(`content: ${check.name} charts render geometry`, async ({ page }, testInfo) => {
    desktopOnly(testInfo);
    await page.goto(check.path, { waitUntil: "networkidle" });
    await settleCharts(page, check.wait ?? 5000);

    for (const [kind, min] of Object.entries(check.require)) {
      const selector = GEOMETRY_SELECTORS[kind];
      expect(
        selector,
        `unknown geometry kind "${kind}" in content-checks.mjs`,
      ).toBeTruthy();

      const locator = page.locator(selector);
      const count = await locator.count();

      // #257: the animation-gated geometry must actually exist. An empty
      // chart produces 0 here while still yielding a >5KB screenshot.
      expect(
        count,
        `${check.name}: expected ≥${min} <${kind}> element(s) ` +
          `("${selector}") but found ${count} — chart likely rendered empty (#257)`,
      ).toBeGreaterThanOrEqual(min);

      // Belt-and-braces: at least one element must have a non-zero
      // bounding box, catching a "present in DOM but collapsed to zero
      // height" degenerate render. We scan all elements rather than just
      // the first because a stacked series can legitimately start with a
      // zero-value segment (e.g. a HR zone with no time) whose box is flat.
      let painted = false;
      for (let i = 0; i < count; i++) {
        const box = await locator.nth(i).boundingBox();
        if (box && box.width > 0 && box.height > 0) {
          painted = true;
          break;
        }
      }
      expect(
        painted,
        `${check.name}: every <${kind}> element has a zero-area box — ` +
          `chart geometry is present but not painted`,
      ).toBeTruthy();
    }
  });
}

test("content: validation table values are within physiological range (#258)", async ({
  page,
}, testInfo) => {
  desktopOnly(testInfo);
  const { path: route, wait, range, invalidLabel } = VALIDATION_CHECK;
  await page.goto(route, { waitUntil: "networkidle" });
  await page.waitForLoadState("networkidle").catch(() => undefined);
  await page.waitForTimeout(wait ?? 5000);

  // Each reconciliation row: [Date, Garmin, Engine, Δ, Status]. Read every
  // row across both tables (VO2max + Readiness) on the page.
  const rows = page.locator("table tbody tr");
  const rowCount = await rows.count();

  // Seeded personas always have reconciliation data; zero rows would mean
  // the validation query silently returned nothing — surface that rather
  // than passing vacuously.
  expect(
    rowCount,
    "validation page rendered no reconciliation rows — seeded data missing or query broken",
  ).toBeGreaterThan(0);

  const parseNum = (text) => {
    const m = (text ?? "").replace(/[^0-9.+-]/g, "");
    if (m === "" || m === "+" || m === "-" || m === ".") return null;
    const n = Number(m);
    return Number.isFinite(n) ? n : null;
  };

  let outOfRangeSeen = 0;

  for (let i = 0; i < rowCount; i++) {
    const cells = rows.nth(i).locator("td");
    if ((await cells.count()) < 5) continue;

    const garmin = parseNum(await cells.nth(1).innerText());
    const engine = parseNum(await cells.nth(2).innerText());
    const status = (await cells.nth(4).innerText()).trim();

    for (const [label, value] of [
      ["Garmin", garmin],
      ["Engine", engine],
    ]) {
      if (value === null) continue;
      const inRange = value >= range.min && value <= range.max;
      if (!inRange) {
        outOfRangeSeen++;
        // #258 core invariant: an impossible value must be flagged
        // "Out of range", never counted as agreement.
        expect(
          status,
          `validation row ${i + 1}: ${label} value ${value} is outside ` +
            `[${range.min}, ${range.max}] but status is "${status}" — ` +
            `out-of-range data must be flagged "${invalidLabel}" (#258)`,
        ).toContain(invalidLabel);
      }
    }
  }

  // Informational: with healthy seed data we expect everything in range,
  // so this is normally 0. It is not an assertion (a future seed could
  // intentionally include a malformed value to exercise the invalid path),
  // but logging it makes the gate's behaviour visible in CI output.
  console.log(
    `validation: checked ${rowCount} row(s); ${outOfRangeSeen} out-of-range ` +
      `value(s), all correctly flagged "${invalidLabel}".`,
  );
});
