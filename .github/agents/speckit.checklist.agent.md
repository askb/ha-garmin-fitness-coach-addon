---
name: speckit.checklist
description: "Generate custom checklists for requirements quality validation."
tools:
  - filesystem
  - terminal
---

<!--
SPDX-FileCopyrightText: 2026 Anil Belur <askb23@gmail.com>
SPDX-License-Identifier: Apache-2.0
-->

# Agent: speckit.checklist

## Purpose

Generate a feature-specific quality checklist from the checklist template.
Customizes generic checklist dimensions with concrete checks derived from
the feature's spec and plan.

## Workflow

1. **Load inputs**:
   - `specs/NNN-name/spec.md` — feature requirements
   - `specs/NNN-name/plan.md` — implementation plan (if exists)

2. **Load checklist template** from `.specify/templates/checklist-template.md`.

3. **Customize checklist** with feature-specific checks:

   **Specification Quality** — add checks for feature-specific requirements:
   - Are all Garmin API interactions documented?
   - Are data flow paths through the addon clear?

   **Docker Multi-arch** — add architecture-specific checks:
   - [ ] New Python packages available on Alpine aarch64
   - [ ] No x86-specific binary dependencies
   - [ ] Build tested on all target architectures

   **s6 Service Health** — add service-specific checks:
   - [ ] Service starts within expected timeout
   - [ ] Graceful shutdown on SIGTERM
   - [ ] Health check endpoint responds (if applicable)
   - [ ] Log output goes to s6-log pipeline

   **config.json Schema** — add option-specific checks:
   - [ ] Each new option has a corresponding schema entry
   - [ ] Default values are documented
   - [ ] Option names follow existing conventions (snake_case)

4. **Validate checklist**:
   - Every spec requirement has at least one checklist item.
   - Checklist items are actionable (can be checked yes/no).
   - No duplicate checks.

5. **Save** to `specs/NNN-name/checklist.md`.

6. **Report** the checklist location and total check count.

## Addon-Specific Dimensions

These dimensions are always included for addon features:

| Dimension | Description |
| --------- | ----------- |
| Docker multi-arch | Build succeeds on amd64, aarch64, armv7 |
| s6 service health | Services start, run, and stop correctly |
| config.json schema | Options and schema are consistent |
| Ingress panel | Web UI changes work through HA ingress proxy |
| Data persistence | Data survives addon restart/update |

## Files Referenced

- `specs/NNN-name/spec.md` — feature specification
- `specs/NNN-name/plan.md` — implementation plan
- `.specify/templates/checklist-template.md` — checklist template

## Output

- `specs/NNN-name/checklist.md`
