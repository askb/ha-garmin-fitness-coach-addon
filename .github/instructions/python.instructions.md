---
applyTo: "**/*.py"
---

<!--
SPDX-FileCopyrightText: 2026 Anil Belur <askb23@gmail.com>
SPDX-License-Identifier: Apache-2.0
-->

# Python Instructions

## Standards
- Python 3.11+
- Type hints required for all functions
- SPDX headers on all files

## Garmin Sync (`pulsecoach/rootfs/app/scripts/garmin-sync.py`)
- Uses `garminconnect` Python package
- Tokens cached in `/data/garmin-tokens/`
- Rate limiting: respect Garmin API limits
- Syncs: daily metrics, activities, sleep, VO2max, stress

## Testing
- Framework: pytest
- Location: `tests/` directory
- Run: `pytest tests/ -v`
- Markers: `@pytest.mark.unit`
- 19 tests covering: auth flow, sync, TRIMP, ingress, sleep, stress

## Token Handling
- `scripts/generate-garmin-tokens.py` for initial token generation
- Tokens persist across container restarts in /data/garmin-tokens/
- Auto-refresh on expiry
