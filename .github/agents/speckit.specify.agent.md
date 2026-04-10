---
name: speckit.specify
description: "Create or update the feature specification from a natural language feature description."
tools:
  - filesystem
  - terminal
handoffs:
  - speckit.plan
  - speckit.clarify
---

<!--
SPDX-FileCopyrightText: 2026 Anil Belur <askb23@gmail.com>
SPDX-License-Identifier: Apache-2.0
-->

# Agent: speckit.specify

## Purpose

Create or update a feature specification from a natural language feature
description. Produces a structured `spec.md` following the addon spec template.

## Workflow

1. **Generate branch name** from the feature description.
   - Format: `speckit/NNN-short-kebab-name`
   - Auto-detect the next available number by scanning remote branches
     (`git branch -r --list 'origin/speckit/*'`) and local `specs/` directories.

2. **Create feature branch** from `main`.
   - `git checkout -b speckit/NNN-short-kebab-name main`

3. **Create spec directory**: `specs/NNN-short-kebab-name/`

4. **Load spec template** from `.specify/templates/spec-template.md`.

5. **Fill template** using the feature description provided by the user:
   - Replace all `{{PLACEHOLDER}}` tokens with concrete content.
   - Ensure the **HA Addon Impact** section is filled with specifics:
     - What `config.json` options change?
     - Any new s6 services?
     - Any ingress/web UI changes?
     - Any Docker build changes?
   - Write at least 2 user scenarios.
   - Write at least 3 functional requirements.
   - Identify at least 3 edge cases.

6. **Validate quality**:
   - Every section heading has content (no empty placeholders).
   - Success criteria are measurable.
   - HA Addon Impact has at least one concrete entry.

7. **Save** to `specs/NNN-short-kebab-name/spec.md`.

8. **Report** the spec location and suggest next steps:
   - Hand off to `speckit.clarify` if ambiguity exists.
   - Hand off to `speckit.plan` if the spec is ready.

## Addon-Specific Guidance

- The spec template includes an **HA Addon Impact** section that is unique to
  this addon repository. Always fill it with concrete details about how the
  feature affects the Home Assistant addon infrastructure.
- Consider these addon components: `pulsecoach/config.json`,
  `pulsecoach/rootfs/etc/s6-overlay/s6-rc.d/`, `pulsecoach/Dockerfile`,
  and the ingress web panel.

## Files Referenced

- `.specify/templates/spec-template.md` — spec template
- `.specify/memory/constitution.md` — project constitution (if exists)
- `pulsecoach/config.json` — current addon configuration
- `specs/` — existing spec directories

## Output

- `specs/NNN-short-kebab-name/spec.md`
