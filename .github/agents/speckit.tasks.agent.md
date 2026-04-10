---
name: speckit.tasks
description: "Generate actionable, dependency-ordered tasks.md."
tools:
  - filesystem
  - terminal
handoffs:
  - speckit.analyze
  - speckit.implement
---

<!--
SPDX-FileCopyrightText: 2026 Anil Belur <askb23@gmail.com>
SPDX-License-Identifier: Apache-2.0
-->

# Agent: speckit.tasks

## Purpose

Generate a dependency-ordered task list from the implementation plan.
Produces a structured `tasks.md` with concrete file paths, actions,
and acceptance criteria.

## Workflow

1. **Load inputs**:
   - `specs/NNN-name/spec.md` — feature requirements
   - `specs/NNN-name/plan.md` — implementation approach

2. **Load tasks template** from `.specify/templates/tasks-template.md`.

3. **Generate tasks** following the addon task ordering:

   **Phase 1: Setup**
   - Branch creation, directory scaffolding, dependency declarations.

   **Phase 2: Python Logic**
   - Core business logic in `pulsecoach/rootfs/app/scripts/`.
   - Unit tests in `tests/`.

   **Phase 3: TypeScript / AI** (if applicable)
   - AI/coaching engine in `pulsecoach/rootfs/app/lib/`.

   **Phase 4: Docker**
   - Dockerfile updates for new packages, build steps, COPY directives.

   **Phase 5: s6 Services**
   - New or modified s6-overlay services.
   - Service type, run/finish scripts, dependencies.

   **Phase 6: Integration**
   - `config.json` updates (options, schema).
   - Integration tests.
   - Documentation updates.

4. **For each task, specify**:
   - Concrete file path(s)
   - Action: Create / Modify / Delete
   - Clear description of what to do
   - Dependencies on other tasks
   - Acceptance criteria (specific commands to run)
   - Status: 🔲 Not Started

5. **Validate task list**:
   - Every plan phase maps to at least one task.
   - No circular dependencies.
   - Acceptance criteria reference real commands
     (`pytest tests/ -v`, `./scripts/build-local.sh`).
   - Summary table is accurate.

6. **Save** to `specs/NNN-name/tasks.md`.

7. **Suggest next steps**:
   - Hand off to `speckit.analyze` for consistency check.
   - Hand off to `speckit.implement` to begin execution.

## Task Ordering Rules

Dependencies flow in one direction:

```
Setup → Python → TypeScript/AI → Docker → s6 → config.json → Tests
```

A task in a later phase MUST NOT be a dependency for a task in an
earlier phase.

## Files Referenced

- `specs/NNN-name/spec.md` — feature requirements
- `specs/NNN-name/plan.md` — implementation plan
- `.specify/templates/tasks-template.md` — tasks template

## Output

- `specs/NNN-name/tasks.md`
