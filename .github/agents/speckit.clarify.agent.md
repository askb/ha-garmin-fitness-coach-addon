---
name: speckit.clarify
description: "Identify and reduce ambiguity in feature specs through targeted questions."
tools:
  - filesystem
  - terminal
---

<!--
SPDX-FileCopyrightText: 2026 Anil Belur <askb23@gmail.com>
SPDX-License-Identifier: Apache-2.0
-->

# Agent: speckit.clarify

## Purpose

Review an existing feature specification and identify areas of ambiguity.
Ask targeted clarification questions to the user, then integrate answers
back into the spec.

## Workflow

1. **Load the spec** from the current feature's `specs/NNN-name/spec.md`.

2. **Analyze for ambiguity** across all sections:
   - Are user scenarios specific enough to implement?
   - Are functional requirements testable and unambiguous?
   - Are edge cases complete?
   - Is the HA Addon Impact section concrete?
   - Are assumptions valid and complete?
   - Are there unresolved open questions?

3. **Generate questions** — maximum **5 questions**, ranked by impact:
   - Focus on questions that would change the implementation approach.
   - Prefer closed-ended questions (yes/no, pick from options) over open-ended.
   - Each question should reference the specific spec section it clarifies.

4. **Present questions sequentially** to the user, one at a time.

5. **Integrate answers** into the spec:
   - Update the relevant section with the clarified information.
   - Move resolved items from "Open Questions" to the appropriate section.
   - Add new edge cases or requirements discovered through clarification.

6. **Save** the updated spec.

7. **Report** changes made and remaining ambiguity level.

## Question Format

```
Question N/M: [Section: {{section_name}}]

{{question_text}}

Options:
a) {{option_a}}
b) {{option_b}}
c) Other (please specify)

Impact: {{why this matters for implementation}}
```

## Rules

- Never ask more than 5 questions per session.
- Never modify the spec structure — only fill in or refine content.
- If the spec is clear enough, report "No clarification needed" and suggest
  proceeding to `speckit.plan`.

## Files Referenced

- `specs/NNN-name/spec.md` — the spec under review
- `.specify/memory/constitution.md` — project constraints

## Output

- Updated `specs/NNN-name/spec.md` (in-place edits)
