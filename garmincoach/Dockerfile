ARG BUILD_FROM
ARG BUILD_ARCH

# ──────────────────────────────────────────────
# Stage 1: Build the Next.js application
# ──────────────────────────────────────────────
FROM node:22-alpine AS builder

RUN corepack enable && corepack prepare pnpm@latest --activate

WORKDIR /build

# Copy the app source (CI clones it into garmin-coach/, local dev symlinks it)
COPY garmin-coach/ ./

# Create minimal .env for build (real values injected at runtime by s6 run script)
RUN echo 'DATABASE_URL="file:/data/garmincoach.db"' > .env && \
    echo 'AUTH_SECRET="build-placeholder"' >> .env && \
    echo 'AUTH_DISCORD_ID="build-placeholder"' >> .env && \
    echo 'AUTH_DISCORD_SECRET="build-placeholder"' >> .env && \
    echo 'DEV_BYPASS_AUTH="true"' >> .env && \
    echo 'OLLAMA_URL=""' >> .env && \
    echo 'OLLAMA_MODEL=""' >> .env

RUN pnpm install --frozen-lockfile

# Enable standalone output for minimal container
ENV NEXT_TELEMETRY_DISABLED=1
RUN pnpm --filter @acme/nextjs build

# Build the engine package (needed at runtime for computations)
RUN pnpm --filter @acme/engine build

# ──────────────────────────────────────────────
# Stage 2: Production runtime on HA base image
# ──────────────────────────────────────────────
FROM ${BUILD_FROM}

# Install Node.js, Python (for Garmin sync), SQLite
RUN apk add --no-cache \
    nodejs=~22 \
    npm \
    python3 \
    py3-pip \
    sqlite \
    sqlite-dev \
    curl \
    tzdata

# Install garminconnect Python package for direct Garmin API sync
RUN pip3 install --break-system-packages garminconnect

WORKDIR /app

# Copy built Next.js standalone app
COPY --from=builder /build/apps/nextjs/.next/standalone ./
COPY --from=builder /build/apps/nextjs/.next/static ./apps/nextjs/.next/static
COPY --from=builder /build/apps/nextjs/public ./apps/nextjs/public

# Copy engine package (for sport science computations in tRPC routes)
COPY --from=builder /build/packages/engine/dist ./packages/engine/dist
COPY --from=builder /build/packages/engine/package.json ./packages/engine/

# Copy addon rootfs (s6 service, sync script, AI backend lib)
COPY rootfs/ /

# Data directory (persisted via HA addon config mapping)
RUN mkdir -p /data /data/garmin-tokens /app/logs

# Labels for HA addon
ARG BUILD_ARCH
LABEL \
    io.hass.name="GarminCoach" \
    io.hass.description="AI-powered sport scientist for Garmin athletes" \
    io.hass.arch="${BUILD_ARCH}" \
    io.hass.type="addon" \
    io.hass.version="0.1.0"
