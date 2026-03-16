<!--
SPDX-FileCopyrightText: 2025 Anil Belur <askb23@gmail.com>
SPDX-License-Identifier: Apache-2.0
-->

# Tests

Unit and integration tests for the **ha-garmin-fitness-coach-addon**.

## Quick start

```bash
# Install test dependencies
pip install pytest garminconnect

# Run all tests
pytest tests/ -v

# Run only unit tests
pytest tests/ -v -m unit
```

## Structure

```
tests/
├── conftest.py                # Shared fixtures (mock Garmin client, DB, env vars)
├── unit/
│   └── test_garmin_sync.py    # Tests for the Python Garmin sync script
└── README.md
```

## Writing tests

- Use `unittest.mock` to mock external APIs (Garmin Connect, Home Assistant).
- Tests must run **without** real credentials or network access.
- Mark tests with `@pytest.mark.unit` for unit tests.
