---
type: template
name: tasks-template
description: Task list template for HA Garmin Fitness Coach Addon
version: 1.0.0
---

<!--
SPDX-FileCopyrightText: 2026 Anil Belur <askb23@gmail.com>
SPDX-License-Identifier: Apache-2.0
-->

# Tasks: {{FEATURE_NAME}}

**Spec:** `specs/{{SPEC_ID}}/spec.md`
**Plan:** `specs/{{SPEC_ID}}/plan.md`
**Created:** {{DATE}}

---

## Path Conventions

| Component | Path | Notes |
| --------- | ---- | ----- |
| Python scripts | `pulsecoach/rootfs/app/scripts/` | Core business logic |
| TypeScript lib | `pulsecoach/rootfs/app/lib/` | AI/coaching engine |
| s6 services | `pulsecoach/rootfs/etc/s6-overlay/s6-rc.d/` | Process management |
| Dockerfile | `pulsecoach/Dockerfile` | Container build |
| Addon config | `pulsecoach/config.json` | HA addon metadata |
| Tests | `tests/` | pytest suite |

---

## Phase 1: Setup

### Task 1.1: {{TASK_TITLE}}

- **File(s):** {{path(s)}}
- **Action:** Create | Modify | Delete
- **Description:** {{what to do}}
- **Depends on:** None
- **Acceptance:** {{how to verify}}
- **Status:** 🔲 Not Started | 🔨 In Progress | ✅ Done | ❌ Blocked

---

## Phase 2: Python Logic

### Task 2.1: {{TASK_TITLE}}

- **File(s):** `pulsecoach/rootfs/app/scripts/{{module}}.py`
- **Action:** Create
- **Description:** {{what to do}}
- **Depends on:** Task 1.x
- **Acceptance:** `pytest tests/test_{{module}}.py -v` passes
- **Status:** 🔲 Not Started

### Task 2.2: {{TASK_TITLE}}

- **File(s):** `tests/test_{{module}}.py`
- **Action:** Create
- **Description:** {{write unit tests}}
- **Depends on:** Task 2.1
- **Acceptance:** All tests pass with `pytest tests/ -v`
- **Status:** 🔲 Not Started

---

## Phase 3: TypeScript / AI (if applicable)

### Task 3.1: {{TASK_TITLE}}

- **File(s):** `pulsecoach/rootfs/app/lib/{{module}}.ts`
- **Action:** Create
- **Description:** {{what to do}}
- **Depends on:** Task 2.x
- **Acceptance:** {{how to verify}}
- **Status:** 🔲 Not Started

---

## Phase 4: Docker

### Task 4.1: Update Dockerfile

- **File(s):** `pulsecoach/Dockerfile`
- **Action:** Modify
- **Description:** {{add new packages, build steps, or COPY directives}}
- **Depends on:** Phase 2, Phase 3
- **Acceptance:** `docker build pulsecoach/` succeeds on amd64
- **Status:** 🔲 Not Started

---

## Phase 5: s6 Services

### Task 5.1: {{SERVICE_NAME}} service

- **File(s):** `pulsecoach/rootfs/etc/s6-overlay/s6-rc.d/{{service}}/`
- **Action:** Create
- **Description:** {{define service type, run script, dependencies}}
- **Depends on:** Task 4.1
- **Acceptance:** Service starts and stays healthy in container
- **Status:** 🔲 Not Started

---

## Phase 6: Integration

### Task 6.1: Update config.json

- **File(s):** `pulsecoach/config.json`
- **Action:** Modify
- **Description:** {{add new options, update schema}}
- **Depends on:** Phase 2–5
- **Acceptance:** HA addon loader accepts updated config
- **Status:** 🔲 Not Started

### Task 6.2: Integration tests

- **File(s):** `tests/test_integration_{{feature}}.py`
- **Action:** Create
- **Description:** {{end-to-end test scenarios}}
- **Depends on:** Task 6.1
- **Acceptance:** `pytest tests/ -v` passes, `./scripts/build-local.sh` succeeds
- **Status:** 🔲 Not Started

---

## Summary

| Phase | Tasks | Done | Blocked |
| ----- | ----- | ---- | ------- |
| 1. Setup | {{n}} | 0 | 0 |
| 2. Python | {{n}} | 0 | 0 |
| 3. TypeScript/AI | {{n}} | 0 | 0 |
| 4. Docker | {{n}} | 0 | 0 |
| 5. s6 Services | {{n}} | 0 | 0 |
| 6. Integration | {{n}} | 0 | 0 |
| **Total** | **{{N}}** | **0** | **0** |
