<!--
SPDX-FileCopyrightText: 2026 Anil Belur <askb23@gmail.com>
SPDX-License-Identifier: Apache-2.0
-->

<!-- Sync Impact Report
Previous version: 0.0.0
Current version:  1.0.0
Impact level:     MAJOR — initial ratification
Summary:          First constitution for the PulseCoach HA addon repository.
                  Establishes all foundational principles, development standards,
                  and governance procedures.
-->

# PulseCoach HA Addon — Repository Constitution

**Version:** 1.0.0
**Ratified:** 2026-03-25
**Maintainer:** Anil Belur <askb23@gmail.com>

---

## Principles

### Principle I: HA Addon Conventions (NON-NEGOTIABLE)

- `pulsecoach/` is the addon slug — NEVER rename.
- `config.json` defines all options, schema, and metadata. It is the single
  source of truth for addon configuration.
- `rootfs/` overlays the container filesystem at runtime.
- s6-overlay manages the service lifecycle (type: `longrun`).
- `SUPERVISOR_TOKEN` is auto-injected when `homeassistant_api: true` is set
  in `config.json`.
- Ingress is proxied through Home Assistant (port 3000 → 3001).

### Principle II: Atomic Commit Discipline (NON-NEGOTIABLE)

- Use **Conventional Commits** with Capitalized types:
  `Feat`, `Fix`, `Chore`, `Docs`, `Style`, `Refactor`, `Perf`, `Test`,
  `Revert`, `CI`, `Build`.
- Title: maximum 72 characters.
- Body: maximum 72 characters per line.
- Each commit represents exactly one logical change.
- Task list updates are committed separately from code changes.

### Principle III: Licensing & Attribution Standards (NON-NEGOTIABLE)

- Every source file MUST carry an SPDX header:
  ```
  SPDX-License-Identifier: Apache-2.0
  SPDX-FileCopyrightText: YYYY Anil Belur <askb23@gmail.com>
  ```
- REUSE compliance is enforced by the `reuse-tool` pre-commit hook.
- Third-party dependencies must have compatible licenses documented in
  `.reuse/dep5` or individual file headers.

### Principle IV: Pre-Commit Integrity (NON-NEGOTIABLE)

- Active hooks: `gitlint`, `yamllint`, `shellcheck`, `REUSE`, `actionlint`.
- **Never** use `--no-verify` to bypass hooks.
- If hooks fail: fix the issue and re-commit. Never use `git reset` to
  discard hook-triggered changes.
- Run `pre-commit run --all-files` before every push.

### Principle V: Agent Co-Authorship & DCO (NON-NEGOTIABLE)

- All agent-assisted commits MUST include:
  ```
  Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>
  ```
- All commits MUST include a DCO sign-off:
  ```
  Signed-off-by: Anil Belur <askb23@gmail.com>
  ```
- Use `git commit -s` to automatically add the sign-off line.

### Principle VI: Multi-Architecture Support (NON-NEGOTIABLE)

- Docker images MUST build for **amd64** AND **aarch64**.
- Use multi-stage builds (Node.js builder → HA base image).
- Test on both architectures before release.
- `build.json` defines supported architectures.

### Principle VII: Data Persistence & Privacy

- All user data stays local — never sent to external services.
- PostgreSQL/SQLite is backed up to `/share/pulsecoach/` after every sync.
- Garmin tokens are cached in `/data/garmin-tokens/` (persistent across
  container restarts).
- AI backends: `ha_conversation`, `ollama`, or `none` — all local-first.

### Principle VIII: Service Reliability

- s6-overlay process monitor must restart dead services automatically.
- Startup order:
  1. PostgreSQL
  2. Auth
  3. Sync
  4. Compute
  5. Notify
  6. Web
  7. Monitor
- All services must have health checks.
- Timeout-based cleanup on failure.

---

## Development Standards

### Git Workflow

1. Create a feature branch from `main`.
2. Make changes following Principle II (atomic commits).
3. Run `pre-commit run --all-files` before pushing.
4. Open a pull request with a clear description.
5. Ensure CI passes on all checks.
6. Squash-merge after approval.

### Testing

- Run the full test suite before every push:
  ```bash
  pytest tests/ -v
  ```
- All new features must include corresponding tests.
- Test markers: `@pytest.mark.unit` for unit tests.
- Maintain or improve code coverage with every change.

### Code Review

- Every change requires at least one approving review.
- Reviewers verify: correctness, style compliance, test coverage, and
  adherence to this constitution.
- Address all review comments before merge.

---

## Governance

### Amendment Process

1. Propose an amendment by opening an issue titled
   `Constitution Amendment: <summary>`.
2. Include the specific text to add, modify, or remove.
3. Discuss in the issue thread.
4. Apply the amendment via a pull request that updates this file.

### Versioning

This constitution follows [Semantic Versioning](https://semver.org/):

- **MAJOR**: New NON-NEGOTIABLE principles or removal of existing ones.
- **MINOR**: New negotiable principles, standards, or governance changes.
- **PATCH**: Clarifications, typo fixes, or formatting improvements.

Every amendment MUST include a Sync Impact Report comment at the top of
this file documenting the version change and impact level.
