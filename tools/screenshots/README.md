<!--
SPDX-FileCopyrightText: 2026 Anil Belur <askb23@gmail.com>
SPDX-License-Identifier: Apache-2.0
-->

# PulseCoach Screenshot Tooling

Playwright-based capture of the PulseCoach dashboard for **AI-assisted UX
review** and side-by-side iteration.

The tool talks **directly to the addon container's HTTP port**. It does
not try to use HA ingress — ingress URLs embed a session-scoped token
that rotates per HA login, which is impractical to script around.

## Setup (one-time, ~2 min)

### 1. Expose the addon's port on your HAOS host

PulseCoach's `config.json` already declares `3000/tcp`. By default it's
**disabled** (only reachable via HA ingress). Enable host networking once:

1. In Home Assistant: **Settings → Add-ons → PulseCoach → Network**
2. Under `Web UI (3000)`, set the host port to `3000`
   (or any free port — adjust `BASE_URL` below to match)
3. Click **Save**
4. **Restart** the addon

PulseCoach is now reachable from your LAN at
`http://<your-haos-host>:3000` (e.g. `http://homeassistant.local:3000`).

> Security note: the addon honors `DEV_BYPASS_AUTH=true` for local dev,
> which is what makes screenshot capture work without a login flow. Do
> not expose this port to the public internet — it's a LAN-only feature.

### 2. Install the tool

On any machine on your LAN (your laptop, a CI runner, a dev VM):

```bash
git clone https://github.com/askb/ha-garmin-fitness-coach-addon.git
cd ha-garmin-fitness-coach-addon/tools/screenshots
npm install
npx playwright install chromium      # one-time, ~150 MB
```

## Capture

```bash
BASE_URL=http://homeassistant.local:3000 npm run screenshot
```

PNGs land in `screenshots/<YYYY-MM-DD>/<route>-<desktop|mobile>.png`.
An HTML report is written to `report/index.html` for browsing.

Single device:

```bash
BASE_URL=http://homeassistant.local:3000 npm run screenshot:desktop
BASE_URL=http://homeassistant.local:3000 npm run screenshot:mobile
```

Light mode:

```bash
BASE_URL=http://homeassistant.local:3000 PULSECOACH_THEME=light npm run screenshot
```

Or put the env into `.env` once:

```bash
cp .env.example .env
$EDITOR .env       # set BASE_URL
npm run screenshot # picks it up automatically? no — see below
```

Note: Playwright doesn't auto-load `.env`. Either prefix each command, or
export from your shell rc, or use [`dotenv-cli`](https://www.npmjs.com/package/dotenv-cli):

```bash
npx dotenv-cli -- npm run screenshot
```

## What gets captured

One full-page screenshot per route per device profile. Routes:

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

Device profiles:

- **desktop**: 1440×900 viewport @2x scale (4 MP-ish PNGs)
- **mobile**: iPhone 14 Pro

## AI review workflow

1. Run `npm run screenshot` after each material UI change in the addon.
2. Drop the day's folder into your model of choice with a prompt like:

   > Review these PulseCoach dashboard screenshots for visual hierarchy,
   > information density, chart legibility, and dark-mode contrast.
   > Flag any cards where the value, axis, or threshold annotation is
   > ambiguous. Suggest concrete CSS / layout changes.

3. Open an issue / branch with the suggested fixes. Re-run after the
   addon rebuild. Diff against the previous day's folder.

Because PNGs are date-stamped, before/after comparison is trivial — open
two folders in your file manager, or run `magick compare`.

## Alternatives

### Don't want to expose the port?

Use Playwright's [`storageState`](https://playwright.dev/docs/auth) with
HA cookies:

1. `npx playwright codegen --save-storage=auth.json http://homeassistant.local:8123`
2. Log in once interactively; close the recorder.
3. Reference `auth.json` in `playwright.config.ts` and target the
   ingress URL.

This works but the saved auth expires when your HA session ends, so it's
fiddlier than just enabling the port.

### CI screenshots

Handled by two workflows:

1. **`e2e-screenshots.yml`** — runs on every PR touching `pulsecoach/` or
   `tools/screenshots/`. Captures per-persona screenshots and validates
   rendered content. Artifacts retained 14 days.

2. **`sync-screenshots.yml`** — runs on every GitHub Release (and
   `workflow_dispatch`). Pulls the production image, seeds athlete data,
   captures desktop screenshots, and opens PRs to update
   `docs/screenshots/` in **both** the addon and app repos automatically.

### Sync to docs/ (manual)

After a local capture run:

```bash
npm run screenshot:sync
# or with explicit paths:
bash scripts/sync-to-docs.sh --date 2026-07-17 --app-repo ~/git/ha-garmin-fitness-coach-app
```

This copies the latest desktop screenshots into `docs/screenshots/` in both
repos. Commit and push from each repo separately.
