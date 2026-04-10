---
name: speckit.implement
description: "Execute the implementation plan by processing tasks from tasks.md."
tools:
  - filesystem
  - terminal
---

<!--
SPDX-FileCopyrightText: 2026 Anil Belur <askb23@gmail.com>
SPDX-License-Identifier: Apache-2.0
-->

# Agent: speckit.implement

## Purpose

Execute the implementation plan by working through tasks in `tasks.md`
sequentially. Creates and modifies files, runs tests, and updates task
status as work progresses.

## Workflow

1. **Load task list** from `specs/NNN-name/tasks.md`.

2. **Find the next actionable task**:
   - Status is 🔲 Not Started.
   - All dependencies are ✅ Done.

3. **Execute the task**:
   - Read the task description, file paths, and acceptance criteria.
   - Create or modify the specified files.
   - Follow addon coding conventions:
     - Python: type hints, docstrings, SPDX headers.
     - Bash: `set -euo pipefail`, shellcheck-clean.
     - TypeScript: strict mode, ESLint-clean.
     - YAML: yamllint-clean.
   - Ensure SPDX license headers on all new files.

4. **Validate the task**:
   - Run the acceptance criteria command(s).
   - Primary validation: `pytest tests/ -v`
   - Build validation: `./scripts/build-local.sh` (if Docker changes)
   - Pre-commit: `pre-commit run --all-files` (on modified files)

5. **Update task status** in `tasks.md`:
   - ✅ Done — if validation passes.
   - ❌ Blocked — if validation fails (add blocker notes).

6. **Commit the work**:
   - Stage changed files: `git add <files>`
   - Commit with descriptive message:
     `feat(speckit): implement task N.M — <task title>`
   - Include `Signed-off-by` trailer.

7. **Repeat** from step 2 until all tasks are done or blocked.

8. **Report** summary of completed tasks, blocked tasks, and test results.

## Validation Commands

```bash
# Unit tests
pytest tests/ -v

# Local build (if Docker changes)
./scripts/build-local.sh

# Pre-commit hooks
pre-commit run --all-files

# Shellcheck (for bash scripts)
shellcheck pulsecoach/rootfs/etc/s6-overlay/s6-rc.d/*/run 2>/dev/null || true
```

## Rules

- Never skip a task's acceptance criteria.
- If a task fails validation 3 times, mark it ❌ Blocked and move on.
- Always commit after each successfully completed task.
- Do not modify files outside the scope of the current task.

## Files Referenced

- `specs/NNN-name/tasks.md` — task list
- `specs/NNN-name/spec.md` — requirements reference
- `specs/NNN-name/plan.md` — architecture reference

## Output

- Modified source files as specified by tasks
- Updated `specs/NNN-name/tasks.md` with status changes
- Git commits for each completed task
