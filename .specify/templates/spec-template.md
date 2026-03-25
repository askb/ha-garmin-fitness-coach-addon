---
type: template
name: spec-template
description: Feature specification template for HA Garmin Fitness Coach Addon
version: 1.0.0
---

<!--
SPDX-FileCopyrightText: 2026 Anil Belur <askb23@gmail.com>
SPDX-License-Identifier: Apache-2.0
-->

# Feature: {{FEATURE_NAME}}

> {{ONE_LINE_DESCRIPTION}}

**Spec ID:** {{SPEC_ID}}
**Author:** {{AUTHOR}}
**Created:** {{DATE}}
**Status:** Draft | In Review | Approved | Implemented

---

## User Scenarios

### Scenario 1: {{SCENARIO_NAME}}

**As a** {{user role}},
**I want to** {{action}},
**So that** {{benefit}}.

**Steps:**

1. {{step}}
2. {{step}}
3. {{step}}

**Expected outcome:** {{outcome}}

### Scenario 2: {{SCENARIO_NAME}}

**As a** {{user role}},
**I want to** {{action}},
**So that** {{benefit}}.

**Steps:**

1. {{step}}
2. {{step}}

**Expected outcome:** {{outcome}}

---

## Functional Requirements

### FR-1: {{REQUIREMENT_TITLE}}

- **Description:** {{detailed description}}
- **Priority:** Must Have | Should Have | Nice to Have
- **Acceptance Criteria:**
  - [ ] {{criterion}}
  - [ ] {{criterion}}

### FR-2: {{REQUIREMENT_TITLE}}

- **Description:** {{detailed description}}
- **Priority:** Must Have | Should Have | Nice to Have
- **Acceptance Criteria:**
  - [ ] {{criterion}}
  - [ ] {{criterion}}

---

## Key Entities

| Entity | Description | Storage | Notes |
| ------ | ----------- | ------- | ----- |
| {{name}} | {{description}} | PostgreSQL / SQLite / File | {{notes}} |

---

## Success Criteria

- [ ] {{measurable criterion}}
- [ ] {{measurable criterion}}
- [ ] {{measurable criterion}}
- [ ] All existing tests continue to pass
- [ ] Docker multi-arch build succeeds (amd64, aarch64, armv7)

---

## Edge Cases

| # | Edge Case | Expected Behavior |
| - | --------- | ----------------- |
| 1 | {{case}} | {{behavior}} |
| 2 | {{case}} | {{behavior}} |
| 3 | {{case}} | {{behavior}} |

---

## HA Addon Impact

This section documents how the feature affects the Home Assistant addon
infrastructure.

### config.json Changes

```json
// New or modified options in garmincoach/config.json
{
  "options": {
    "{{OPTION_NAME}}": "{{default_value}}"
  },
  "schema": {
    "{{OPTION_NAME}}": "{{type}}"
  }
}
```

### s6 Services

- **New services:** {{list any new s6-overlay service directories}}
- **Modified services:** {{list changed s6-rc.d entries}}
- **Service dependencies:** {{describe any run/finish/dependencies changes}}

### Ingress / Web UI

- **Ingress changes:** {{describe any changes to web panel / ingress proxy}}
- **New routes:** {{list any new HTTP endpoints}}

### Docker

- **New packages:** {{list any new apk/pip/npm packages}}
- **Build stages:** {{describe any Dockerfile changes}}
- **Volume mounts:** {{describe any new persistent storage needs}}

---

## Assumptions

- {{assumption about the runtime environment}}
- {{assumption about user behavior}}
- {{assumption about external dependencies (Garmin API, HA Core, etc.)}}

---

## Open Questions

- [ ] {{question that needs resolution before implementation}}
