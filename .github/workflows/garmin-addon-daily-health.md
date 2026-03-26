---
on:
  schedule: daily on weekdays

permissions:
  contents: read
  issues: read
  pull-requests: read

network: defaults

safe-outputs:
  create-issue:
    title-prefix: "[daily-health] "
    labels: [report, daily-health]
    close-older-issues: true
    max: 1
---

# Daily GarminCoach Addon Health Report

Generate a daily health report for the GarminCoach Home Assistant addon repository.

## Context

This is a Home Assistant addon that syncs Garmin fitness data into PostgreSQL
and serves an AI coaching dashboard. Key components:
- **Dockerfile** — Multi-stage build: clones app repo, builds Next.js standalone, installs Python deps
- **s6-overlay services** — postgresql, garmin-auth, garmincoach (main orchestrator)
- **Python scripts** — garmin-sync.py (data sync), metrics-compute.py (EWMA/CTL/ATL/TSB), ha-notify.py (HA sensors)
- **ingress-proxy.js** — Node.js proxy rewriting paths for HA ingress compatibility
- **Next.js standalone** — Bundled app served on port 3001, proxied via ingress on port 3000

The addon pushes 7 HA sensors: CTL, ATL, TSB, ACWR, resting HR, HRV, sleep score.

## Instructions

Create a concise daily health report as a GitHub issue covering:

### 1. Repository Activity (last 24h)
- Recent commits and what changed
- Open pull requests needing review
- Any CI/CD failures in recent workflow runs

### 2. Addon Structure Health
- Verify Dockerfile builds correctly (check for deprecated instructions)
- Check s6-overlay service definitions in `garmincoach/rootfs/etc/s6-overlay/`
- Verify `garmincoach/config.json` version matches latest git tag (if any)
- Count Python scripts in `garmincoach/rootfs/app/scripts/`
- Count test files in `garmincoach/rootfs/app/tests/`

### 3. Python Code Quality
- Check all Python scripts for `set -euo pipefail` equivalent (proper error handling)
- Look for bare `except:` clauses (should catch specific exceptions)
- Check for hardcoded credentials or connection strings (should use env vars)
- Verify `psycopg2.extras.RealDictCursor` is used (not tuple indexing)
- Check for TODO/FIXME/HACK comments

### 4. Security Review
- Check Dockerfile for `latest` tags (should pin versions)
- Verify no secrets in source code
- Check `config.json` for proper permission scoping
- Verify ingress-proxy.js doesn't expose internal paths
- **Scan for hardcoded IP addresses** (e.g., 192.168.x.x) — should use env vars or `!secret`
- **Scan for personal email addresses** (not maintainer SPDX headers)
- **Scan for RTSP/HTTP URLs containing embedded credentials** (user:pass@host)
- **Check for personal names or identifiable health data** in code or comments
- Flag any `.env` or `.env.local` files committed (should be in .gitignore)

### 5. HA Integration Health
- Verify all 7 sensors are defined in ha-notify.py
- Check sensor naming convention (should be `sensor.garmincoach_*`)
- Verify cleanup traps exist in s6 run scripts
- Check process monitoring loop is active in main run script

### 6. Recommendations
- Suggest improvements based on what you find
- Flag any Python scripts missing type hints
- Note any s6 services missing proper shutdown handling

### 7. Spec Kit Health
- List all active specs in `specs/` directory (skip `.gitkeep`)
- For each spec directory, check completeness:
  - ✅ Has `spec.md` (requirements defined)
  - ✅ Has `plan.md` (implementation planned)
  - ✅ Has `tasks.md` (work breakdown exists)
  - ⚠️ Missing any of the above
- Check `tasks.md` files for unchecked items (`- [ ]`) — report count of pending vs done
- Flag specs not modified in the last 14 days as potentially stale
- If `specs/` is empty (only `.gitkeep`), note "No active feature specs — consider creating specs for planned work"

### Format
Use clear headings, bullet points, and emoji status indicators:
- ✅ Healthy
- ⚠️ Needs attention
- ❌ Action required

Keep the report under 600 words. Focus on actionable items only.
