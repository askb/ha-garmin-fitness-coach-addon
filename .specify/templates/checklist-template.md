---
type: template
name: checklist-template
description: Quality validation checklist template
version: 1.0.0
---

<!--
SPDX-FileCopyrightText: 2026 Anil Belur <askb23@gmail.com>
SPDX-License-Identifier: Apache-2.0
-->

# Checklist: {{FEATURE_NAME}}

**Spec:** `specs/{{SPEC_ID}}/spec.md`
**Created:** {{DATE}}
**Reviewer:** {{REVIEWER}}

---

## Specification Quality

- [ ] All user scenarios have clear steps and expected outcomes
- [ ] Functional requirements have measurable acceptance criteria
- [ ] Edge cases are identified and documented
- [ ] HA Addon Impact section is complete (config.json, s6, ingress, Docker)
- [ ] Assumptions are stated explicitly
- [ ] Open questions are resolved or tracked

---

## Plan Quality

- [ ] Technical context matches current addon architecture
- [ ] Constitution check completed
- [ ] Project structure option is justified
- [ ] Architecture decisions are documented with rationale
- [ ] Risks are identified with mitigations
- [ ] Dependencies are listed

---

## Task Quality

- [ ] Tasks follow dependency order: Python → TypeScript → s6 → Docker → config → tests
- [ ] Each task has clear file paths and acceptance criteria
- [ ] No circular dependencies between tasks
- [ ] All spec requirements are covered by at least one task
- [ ] Test tasks exist for each implementation task

---

## Implementation Quality

### Code Standards

- [ ] Python code has type hints and docstrings
- [ ] Bash scripts use `set -euo pipefail`
- [ ] SPDX license headers on all new files
- [ ] No hardcoded credentials or secrets

### Docker & Multi-arch

- [ ] Dockerfile changes build on amd64
- [ ] Dockerfile changes build on aarch64
- [ ] Dockerfile changes build on armv7
- [ ] No architecture-specific assumptions in code
- [ ] New packages available on all target architectures

### s6 Service Health

- [ ] Service type file exists (`longrun` or `oneshot`)
- [ ] Run script is executable and uses `#!/usr/bin/with-contenv bashio`
- [ ] Finish script handles cleanup (if longrun)
- [ ] Service dependencies declared in `dependencies.d/`
- [ ] Service registered in `user/contents.d/`

### config.json Schema

- [ ] New options have sensible defaults
- [ ] Schema types match option value types
- [ ] Options are documented in README.md
- [ ] Backward compatible with previous config versions
- [ ] Translations updated (if applicable)

---

## Testing

- [ ] Unit tests written and passing (`pytest tests/ -v`)
- [ ] Integration tests cover key scenarios
- [ ] Edge cases from spec are tested
- [ ] Local build succeeds (`./scripts/build-local.sh`)
- [ ] Pre-commit hooks pass (`pre-commit run --all-files`)

---

## Documentation

- [ ] README.md updated with new features/options
- [ ] CHANGELOG.md entry added
- [ ] Spec documents are complete and consistent
- [ ] In-code comments where non-obvious logic exists

---

## Final Sign-off

| Dimension | Status | Notes |
| --------- | ------ | ----- |
| Specification | ⬜ Pass / ⬜ Fail | |
| Plan | ⬜ Pass / ⬜ Fail | |
| Tasks | ⬜ Pass / ⬜ Fail | |
| Code | ⬜ Pass / ⬜ Fail | |
| Docker | ⬜ Pass / ⬜ Fail | |
| s6 Services | ⬜ Pass / ⬜ Fail | |
| config.json | ⬜ Pass / ⬜ Fail | |
| Tests | ⬜ Pass / ⬜ Fail | |
| Documentation | ⬜ Pass / ⬜ Fail | |

**Overall:** ⬜ Approved | ⬜ Changes Requested
