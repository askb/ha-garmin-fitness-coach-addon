<!--
SPDX-FileCopyrightText: 2026 Anil Belur <askb23@gmail.com>
SPDX-License-Identifier: Apache-2.0
-->

# PulseCoach Screenshot Tooling

Playwright-based capture of the PulseCoach dashboard for **AI-assisted UX
review** and side-by-side iteration.

It does **not** test the HA ingress path — it hits the underlying Next.js
app directly, which is far simpler and avoids HA's session-scoped ingress
tokens.

## Quick start

```bash
# 1. Start the Next.js app in another terminal (from the *app* repo):
#    cd ../ha-garmin-fitness-coach-app && pnpm dev
#    (serves at http://localhost:3000)
#
# Or run the addon container locally with the port exposed:
#    docker run -p 3001:3001 ghcr.io/askb/pulsecoach-addon-amd64:latest
#    (in which case set BASE_URL=http://localhost:3001 below)

cd tools/screenshots
npm install
npx playwright install chromium    # one-time
npm run screenshot
```

PNGs land in `screenshots/<YYYY-MM-DD>/<route>-<desktop|mobile>.png`.
An HTML report is written to `report/index.html` for browsing.

## What gets captured

One full-page screenshot per route per device profile (desktop 1440×900
@2x, mobile = iPhone 14 Pro). Routes covered:

| Route          | Notes                                              |
| -------------- | -------------------------------------------------- |
| `/`            | Landing / Today's Coach                            |
| `/training`    | PMC (CTL/ATL/TSB), ACWR gauge                      |
| `/fitness`     | VO2max, race predictions, training status          |
| `/activities`  | Activity list + HR zones                           |
| `/sleep`       | Sleep coach + debt                                 |
| `/trends`      | Long-term trends                                   |
| `/zones`       | HR zone analytics                                  |
| `/hrv`         | HRV history                                        |
| `/vitals`      | Resting HR, SpO2, body battery                     |
| `/insights`    | AI insight cards                                   |
| `/coach`       | AI chat surface                                    |
| `/validation`  | Data quality validation page                       |

Add or remove routes in `tests/dashboard.spec.ts` (the `ROUTES` array).

## Configuration

Copy `.env.example` to `.env`:

```bash
BASE_URL=http://localhost:3000   # where the app is served
SCREENSHOT_DIR=screenshots       # output dir
PULSECOACH_THEME=dark            # dark | light
```

Or pass on the command line:

```bash
BASE_URL=http://localhost:3001 PULSECOACH_THEME=light npm run screenshot
```

Single device profile:

```bash
npm run screenshot:desktop
npm run screenshot:mobile
```

## AI review workflow

1. Run `npm run screenshot` after each material UI change.
2. Drop the day's folder into your model of choice with a prompt like:

   > Review these PulseCoach dashboard screenshots for visual hierarchy,
   > information density, chart legibility, and dark-mode contrast.
   > Flag any cards where the value, axis, or threshold annotation is
   > ambiguous. Suggest concrete CSS / layout changes.

3. Commit the diff. Re-run. Compare with the previous day's folder.

The date-stamped subdirectories make before/after diffs trivial — open
two folders side-by-side in your file manager, or run a structural diff
like `magick compare`.

## Why not via HA ingress?

HA's ingress URL embeds a **session-scoped token** that rotates per HA
session. Long-lived access tokens authorise the WebSocket API but **not**
ingress. Running Playwright from outside HA against ingress is not
practical. Hitting the Next.js app directly bypasses this entirely and
gives identical pixels (ingress only rewrites paths; it does not transform
the rendered DOM).

## Out of scope (for now)

- Visual-regression assertions (pixel diff thresholds). The current setup
  only captures — assertions would belong in the *app* repo's test suite
  with stable seed data.
- Authenticated screenshots. The app honors `DEV_BYPASS_AUTH=true` (the
  standard dev setting), which is sufficient for screenshot capture.
- Triggering screenshots from inside HA via a service call. Addon
  isolation makes this awkward; trigger from your dev machine or a CI
  runner instead.
