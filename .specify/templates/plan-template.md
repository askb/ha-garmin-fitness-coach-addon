---
type: template
name: plan-template
description: Implementation plan template for HA Garmin Fitness Coach Addon
version: 1.0.0
---

<!--
SPDX-FileCopyrightText: 2026 Anil Belur <askb23@gmail.com>
SPDX-License-Identifier: Apache-2.0
-->

# Implementation Plan: {{FEATURE_NAME}}

**Spec:** `specs/{{SPEC_ID}}/spec.md`
**Author:** {{AUTHOR}}
**Created:** {{DATE}}
**Status:** Draft | In Review | Approved

---

## Technical Context

### Runtime Environment

- **Platform:** Home Assistant OS / Supervised / Container
- **Base image:** `ghcr.io/home-assistant/amd64-base-python:3.11`
- **Languages:** Python 3.11+, TypeScript (optional)
- **Process supervisor:** s6-overlay v3
- **Database:** PostgreSQL (external) or SQLite (local)
- **Web framework:** aiohttp (ingress panel)

### Relevant Stack Components

| Component | Location | Purpose |
| --------- | -------- | ------- |
| Python scripts | `garmincoach/rootfs/app/scripts/` | Core business logic |
| TypeScript lib | `garmincoach/rootfs/app/lib/` | AI/coaching engine (optional) |
| s6 services | `garmincoach/rootfs/etc/s6-overlay/s6-rc.d/` | Process management |
| Dockerfile | `garmincoach/Dockerfile` | Container build |
| Addon config | `garmincoach/config.json` | HA addon metadata + options |
| Tests | `tests/` | pytest test suite |

---

## Constitution Check

Before proceeding, verify alignment with `.specify/memory/constitution.md`:

- [ ] Follows addon architecture patterns
- [ ] Respects data storage conventions (options vs persistent files)
- [ ] Compatible with multi-arch builds (amd64, aarch64, armv7)
- [ ] Maintains backward compatibility with existing config.json options
- [ ] Does not introduce new external service dependencies without approval

---

## Project Structure

### Option A: Python-only (Recommended for data/API features)

```
garmincoach/rootfs/app/scripts/
├── {{feature_module}}.py          # Core logic
├── {{feature_module}}_utils.py    # Helpers
tests/
├── test_{{feature_module}}.py     # Unit tests
```

### Option B: TypeScript-only (For AI/coaching features)

```
garmincoach/rootfs/app/lib/
├── {{feature_module}}.ts          # Core logic
├── {{feature_module}}.test.ts     # Unit tests
```

### Option C: Full-stack addon (Complex features)

```
garmincoach/rootfs/app/scripts/
├── {{feature_module}}.py          # Backend logic
garmincoach/rootfs/app/lib/
├── {{feature_module}}.ts          # Frontend/AI logic
garmincoach/rootfs/etc/s6-overlay/s6-rc.d/
├── {{service_name}}/
│   ├── type                       # "longrun" or "oneshot"
│   ├── run                        # Service start script
│   └── finish                     # Cleanup script (optional)
garmincoach/config.json            # Updated options/schema
garmincoach/Dockerfile             # Updated build
tests/
├── test_{{feature_module}}.py     # Integration tests
```

**Selected option:** {{A | B | C}}

---

## Documentation Structure

All feature documentation lives under:

```
specs/{{SPEC_ID}}/
├── spec.md          # Feature specification (from spec-template)
├── plan.md          # This file
├── tasks.md         # Task breakdown (from tasks-template)
├── checklist.md     # Quality checklist (from checklist-template)
├── data-model.md    # Data model design (if applicable)
├── research.md      # Technical research notes (if applicable)
└── contracts.md     # API/interface contracts (if applicable)
```

---

## Architecture Decisions

### Decision 1: {{TITLE}}

- **Context:** {{why this decision is needed}}
- **Options considered:**
  1. {{option A}} — {{pros/cons}}
  2. {{option B}} — {{pros/cons}}
- **Decision:** {{chosen option}}
- **Rationale:** {{why}}

---

## Implementation Approach

### Phase 1: Foundation

- {{description of initial setup work}}

### Phase 2: Core Logic

- {{description of main implementation}}

### Phase 3: Integration

- {{description of wiring into addon infrastructure}}

### Phase 4: Testing & Polish

- {{description of test coverage and cleanup}}

---

## Risk Assessment

| Risk | Impact | Likelihood | Mitigation |
| ---- | ------ | ---------- | ---------- |
| {{risk}} | High/Med/Low | High/Med/Low | {{mitigation}} |

---

## Dependencies

- [ ] {{external dependency or prerequisite}}
- [ ] {{internal dependency on other features}}
