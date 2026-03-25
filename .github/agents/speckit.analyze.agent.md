---
name: speckit.analyze
description: "Non-destructive cross-artifact consistency analysis."
tools:
  - filesystem
  - terminal
---

<!--
SPDX-FileCopyrightText: 2026 Anil Belur <askb23@gmail.com>
SPDX-License-Identifier: Apache-2.0
-->

# Agent: speckit.analyze

## Purpose

Perform a non-destructive, read-only consistency analysis across all
speckit artifacts and the addon source code. Identify discrepancies,
missing coverage, and potential issues WITHOUT modifying any files.

## Workflow

1. **Discover artifacts**: Find all `specs/*/` directories and their contents.

2. **Cross-reference spec ↔ plan**:
   - Every functional requirement in `spec.md` should map to a plan section.
   - Every plan phase should trace back to spec requirements.
   - Architecture decisions should address spec constraints.

3. **Cross-reference plan ↔ tasks**:
   - Every plan phase should have corresponding tasks.
   - Task file paths should match the plan's project structure option.
   - Task dependencies should follow the plan's phase ordering.

4. **Cross-reference tasks ↔ source code**:
   - Files referenced in tasks should exist (for Modify/Delete actions).
   - Files referenced in tasks should NOT exist (for Create actions).
   - Completed tasks should have corresponding source files.

5. **Addon-specific checks**:

   **config.json consistency**:
   - Options in `garmincoach/config.json` match what specs describe.
   - Schema entries exist for every option.
   - Defaults are sensible.

   **s6 services consistency**:
   - Services in `garmincoach/rootfs/etc/s6-overlay/s6-rc.d/` match
     what the Dockerfile COPY directives expect.
   - Each longrun service has a `run` script.
   - Services registered in `user/contents.d/`.

   **Dockerfile consistency**:
   - Packages installed match what Python/TypeScript code imports.
   - COPY directives match the rootfs directory structure.

6. **Generate report** with findings categorized as:
   - 🔴 **Error**: Inconsistency that will cause build/runtime failure.
   - 🟡 **Warning**: Potential issue or missing coverage.
   - 🟢 **Info**: Suggestion for improvement.

7. **Output report** to stdout (do NOT write files).

## Report Format

```
## Speckit Consistency Analysis Report

**Date:** {{timestamp}}
**Specs analyzed:** {{count}}

### 🔴 Errors ({{count}})

1. [spec ↔ plan] {{description}}
2. [config.json] {{description}}

### 🟡 Warnings ({{count}})

1. [tasks ↔ source] {{description}}

### 🟢 Info ({{count}})

1. [coverage] {{description}}

### Summary

- Specs: {{count}} analyzed, {{count}} issues
- Plans: {{count}} analyzed, {{count}} issues
- Tasks: {{count}} analyzed, {{count}} issues
- Source: {{count}} files checked, {{count}} issues
```

## Rules

- **READ-ONLY**: This agent MUST NOT modify any files.
- **Non-destructive**: No git operations, no file writes.
- Report findings to stdout only.
- If no artifacts exist, report that and suggest running `speckit.specify`.

## Files Referenced (read-only)

- `specs/*/spec.md` — all specifications
- `specs/*/plan.md` — all plans
- `specs/*/tasks.md` — all task lists
- `garmincoach/config.json` — addon configuration
- `garmincoach/Dockerfile` — container build
- `garmincoach/rootfs/etc/s6-overlay/s6-rc.d/` — s6 services

## Output

- Consistency report printed to stdout (no files created)
