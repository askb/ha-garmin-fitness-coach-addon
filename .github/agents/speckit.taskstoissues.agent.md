---
name: speckit.taskstoissues
description: "Convert tasks.md into GitHub Issues."
tools:
  - filesystem
  - terminal
---

<!--
SPDX-FileCopyrightText: 2026 Anil Belur <askb23@gmail.com>
SPDX-License-Identifier: Apache-2.0
-->

# Agent: speckit.taskstoissues

## Purpose

Convert a `tasks.md` file into GitHub Issues, preserving task structure,
dependencies, and metadata. Each task becomes an issue; phases become
labels or milestones.

## Workflow

1. **Verify remote repository**:
   - Run `git remote get-url origin` and confirm it matches
     `github.com/askb/ha-garmin-fitness-coach-addon`.
   - If the remote does not match, **STOP** and report the mismatch.
     Do not create issues on the wrong repository.

2. **Load task list** from `specs/NNN-name/tasks.md`.

3. **Parse tasks** into structured data:
   - Task ID (e.g., `1.1`, `2.1`)
   - Title
   - Description
   - File paths
   - Dependencies (other task IDs)
   - Acceptance criteria
   - Phase name

4. **Create labels** (if they don't exist):
   - `speckit:phase-1-setup`
   - `speckit:phase-2-python`
   - `speckit:phase-3-typescript`
   - `speckit:phase-4-docker`
   - `speckit:phase-5-s6`
   - `speckit:phase-6-integration`
   - `speckit:task` (common label for all speckit tasks)
   - `spec:NNN-name` (feature-specific label)

5. **Create issues** for each task:
   - **Title**: `[Task N.M] {{task_title}}`
   - **Body**:
     ```markdown
     ## Task N.M: {{task_title}}

     **Spec:** `specs/NNN-name/spec.md`
     **Phase:** {{phase_name}}

     ### Description
     {{task_description}}

     ### Files
     {{file_paths}}

     ### Acceptance Criteria
     {{criteria}}

     ### Dependencies
     {{dependency_issue_links}}
     ```
   - **Labels**: `speckit:task`, `speckit:phase-N-name`, `spec:NNN-name`

6. **Link dependencies**:
   - After all issues are created, update each issue body to include
     links to dependency issues using `Depends on #NNN` syntax.

7. **Update tasks.md**:
   - Add issue number references next to each task:
     `- **Issue:** #NNN`

8. **Report** summary:
   - Total issues created
   - Issues per phase
   - Dependency links created

## Rules

- Always verify the remote before creating any issues.
- Use `gh` CLI for issue creation (not the GitHub API directly).
- Create issues in dependency order (earlier phases first).
- If an issue already exists for a task (check by title), skip it.
- Rate-limit: wait 1 second between issue creations to avoid API limits.

## Commands Used

```bash
# Verify remote
git remote get-url origin

# Create label
gh label create "speckit:task" --description "Speckit generated task" --color "0E8A16"

# Create issue
gh issue create \
  --title "[Task N.M] Task title" \
  --body "Issue body..." \
  --label "speckit:task,speckit:phase-N-name,spec:NNN-name"

# List existing issues (to avoid duplicates)
gh issue list --label "spec:NNN-name" --json number,title
```

## Files Referenced

- `specs/NNN-name/tasks.md` — task list (read, then updated with issue numbers)

## Output

- GitHub Issues created on `askb/ha-garmin-fitness-coach-addon`
- Updated `specs/NNN-name/tasks.md` with issue references
