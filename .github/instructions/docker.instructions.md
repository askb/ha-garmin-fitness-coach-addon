---
applyTo: "**/Dockerfile"
---

<!--
SPDX-FileCopyrightText: 2026 Anil Belur <askb23@gmail.com>
SPDX-License-Identifier: Apache-2.0
-->

# Dockerfile Instructions

## Multi-Stage Build Pattern
1. **Builder stage**: Node.js 22, install deps, build Next.js standalone
2. **Runtime stage**: HA base image, copy artifacts, install Python deps

## Multi-Architecture
- Must support: amd64, aarch64 (defined in build.json)
- Use QEMU for cross-platform builds in CI
- Test on both architectures before release

## Key Requirements
- No dev dependencies in runtime image
- Minimize image size (no source maps, no test files)
- PostgreSQL client libraries must be installed
- Python dependencies from requirements.txt
- s6-overlay for process management
