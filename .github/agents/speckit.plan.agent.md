---
name: speckit.plan
description: "Execute the implementation planning workflow."
tools:
  - filesystem
  - terminal
handoffs:
  - speckit.tasks
  - speckit.checklist
---

<!--
SPDX-FileCopyrightText: 2026 Anil Belur <askb23@gmail.com>
SPDX-License-Identifier: Apache-2.0
-->

# Agent: speckit.plan

## Purpose

Create an implementation plan from an approved feature specification.
Produces a structured `plan.md` that maps the spec requirements to the
addon's technical architecture.

## Workflow

1. **Locate the spec**: Find `specs/NNN-name/spec.md` for the current
   feature branch.

2. **Load plan template** from `.specify/templates/plan-template.md`.

3. **Analyze the spec** to determine:
   - Which addon components are affected (Python, TypeScript, s6, Docker,
     config.json, ingress).
   - What project structure option to use (A: Python-only, B: TypeScript-only,
     C: Full-stack).
   - What architecture decisions need to be made.

4. **Fill the plan template**:
   - **Technical Context**: Docker, Python 3.11+, TypeScript, s6-overlay,
     PostgreSQL/SQLite — update with feature-specific details.
   - **Constitution Check**: Verify against `.specify/memory/constitution.md`.
   - **Project Structure**: Select and justify the option.
   - **Package Mapping**:
     - Python scripts → `garmincoach/rootfs/app/scripts/`
     - TypeScript lib → `garmincoach/rootfs/app/lib/`
     - s6 services → `garmincoach/rootfs/etc/s6-overlay/s6-rc.d/`
     - Docker → `garmincoach/Dockerfile`
     - Config → `garmincoach/config.json`
   - **Architecture Decisions**: Document each decision with context, options,
     and rationale.
   - **Implementation Phases**: Break into 3-4 phases.
   - **Risk Assessment**: Identify at least 2 risks.

5. **Validate plan**:
   - Every spec requirement maps to at least one plan section.
   - Architecture decisions are justified.
   - Risk mitigations are actionable.

6. **Save** to `specs/NNN-name/plan.md`.

7. **Suggest next steps**:
   - Hand off to `speckit.tasks` for task breakdown.
   - Hand off to `speckit.checklist` for quality validation.

## Files Referenced

- `specs/NNN-name/spec.md` — feature specification
- `.specify/templates/plan-template.md` — plan template
- `.specify/memory/constitution.md` — project constitution
- `garmincoach/config.json` — current addon config
- `garmincoach/Dockerfile` — current Dockerfile
- `garmincoach/rootfs/etc/s6-overlay/s6-rc.d/` — existing s6 services

## Output

- `specs/NNN-name/plan.md`
