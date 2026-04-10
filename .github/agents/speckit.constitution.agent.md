---
name: speckit.constitution
description: "Create or update project constitution with version tracking."
tools:
  - filesystem
  - terminal
---

<!--
SPDX-FileCopyrightText: 2026 Anil Belur <askb23@gmail.com>
SPDX-License-Identifier: Apache-2.0
-->

# Agent: speckit.constitution

## Purpose

Create or update the project constitution — a living document that captures
architectural decisions, coding standards, and project constraints. The
constitution serves as the authoritative reference for all speckit agents.

## Workflow

1. **Check for existing constitution** at `.specify/memory/constitution.md`.

2. **If creating new**:
   - Analyze the repository structure to discover:
     - Languages and frameworks in use
     - Directory layout conventions
     - Testing patterns
     - CI/CD configuration
     - Addon-specific patterns (config.json schema, s6 services, Dockerfile)
   - Generate a constitution covering all sections below.
   - Set version to `1.0.0`.

3. **If updating existing**:
   - Load the current constitution.
   - Identify what has changed (new patterns, deprecated practices,
     architecture decisions from recent specs).
   - Apply changes while preserving the document structure.
   - Increment the version (minor for additions, major for breaking changes).
   - Add a changelog entry.

4. **Constitution sections**:

   ```markdown
   # Project Constitution

   **Version:** X.Y.Z
   **Last Updated:** YYYY-MM-DD

   ## Project Identity
   - Name, purpose, target platform

   ## Architecture
   - Component diagram
   - Data flow
   - Key design decisions

   ## Technology Stack
   - Languages, frameworks, versions
   - Build tools and CI/CD

   ## Coding Standards
   - Style guides per language
   - File naming conventions
   - SPDX header requirements

   ## Addon Conventions
   - config.json patterns
   - s6-overlay service structure
   - Dockerfile conventions
   - Multi-arch build requirements

   ## Testing Requirements
   - Required test types
   - Coverage expectations
   - Validation commands

   ## Constraints
   - Performance requirements
   - Compatibility requirements
   - Security requirements

   ## Changelog
   - Version history with dates and descriptions
   ```

5. **Validate constitution**:
   - All sections have content.
   - Technology versions match actual project files.
   - Coding standards are consistent with `.pre-commit-config.yaml`.

6. **Save** to `.specify/memory/constitution.md`.

7. **Report** version number and changes made.

## Files Referenced

- `.specify/memory/constitution.md` — the constitution (read/write)
- `pulsecoach/config.json` — addon configuration
- `pulsecoach/Dockerfile` — build configuration
- `.pre-commit-config.yaml` — code quality rules
- `pyproject.toml` — Python project configuration
- `pulsecoach/rootfs/etc/s6-overlay/` — service structure

## Output

- `.specify/memory/constitution.md` (created or updated)
