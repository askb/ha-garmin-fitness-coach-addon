---
applyTo: "garmincoach/**"
---

<!--
SPDX-FileCopyrightText: 2026 Anil Belur <askb23@gmail.com>
SPDX-License-Identifier: Apache-2.0
-->

# HA Addon Instructions

## Addon Structure (NON-NEGOTIABLE)
- `garmincoach/` is the addon slug — do NOT rename
- `config.json` is the single source of truth for addon options
- `rootfs/` is overlaid onto the container at runtime

## config.json Schema
- All user-configurable options MUST be in config.json `options` field
- Schema validation in `schema` field must match options
- Version follows semver, updated in config.json AND CHANGELOG.md

## Dockerfile Conventions
- Multi-stage: Node.js builder → HA base image
- Copy only necessary artifacts (no dev dependencies, no source maps)
- Support amd64 and aarch64 via build.json

## AI Backend (`rootfs/app/lib/ai-backend.ts`)
- Abstracts 3 backends: ha_conversation, ollama, none
- ha_conversation uses HA Supervisor API (POST /core/api/conversation/process)
- SUPERVISOR_TOKEN auto-injected (homeassistant_api: true in config.json)
- HA Conversation takes single text input, not message arrays
