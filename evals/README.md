<!--
SPDX-FileCopyrightText: 2026 Anil Belur <askb23@gmail.com>
SPDX-License-Identifier: Apache-2.0
-->

# Evals

Standalone behavioral evaluations for the PulseCoach coaching engine.

Unlike the unit tests in `tests/` (which assert individual trigger
conditions), evals exercise end-to-end scenarios against the real
`recommend_workout()` decision logic and check cross-cutting invariants:

- A rest-day recommendation always carries a rationale.
- No scenario produces a high-intensity workout when readiness signals
  are critically low.
- With all signals missing, the engine still never recommends a
  high-intensity workout (degrades conservatively).

## Running

```bash
python3 evals/smoke_eval.py
```

Exit code `0` means all scenarios passed; non-zero prints the failing
scenario(s). No external services, database, or Home Assistant instance
is required — the module is loaded with a mocked environment like the import
fixture in `tests/test_coaching_engine.py`, plus a stubbed `psycopg2` when it
is not installed (so the eval also runs where the PostgreSQL client is absent).

## Adding scenarios

Add a `Scenario` entry to `SCENARIOS` in `smoke_eval.py` with the input
signals and the invariant(s) it must satisfy. Keep scenarios realistic —
values should be plausible Garmin exports, not synthetic extremes.
