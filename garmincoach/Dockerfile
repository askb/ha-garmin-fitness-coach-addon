ARG BUILD_FROM
ARG BUILD_ARCH

# ──────────────────────────────────────────────
# Stage 1: Build the Next.js application
# ──────────────────────────────────────────────
FROM node:22-alpine AS builder

RUN corepack enable && corepack prepare pnpm@latest --activate

WORKDIR /build

# Clone the main app repo (pinned to a release tag in production)
# For development, COPY from local source instead
COPY garmin-coach/ ./

RUN pnpm install --frozen-lockfile

# Build with standalone output for minimal container size
ENV NEXT_TELEMETRY_DISABLED=1
RUN pnpm --filter @acme/nextjs build

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

# Copy built Next.js standalone app
WORKDIR /app
COPY --from=builder /build/apps/nextjs/.next/standalone ./
COPY --from=builder /build/apps/nextjs/.next/static ./apps/nextjs/.next/static
COPY --from=builder /build/apps/nextjs/public ./apps/nextjs/public

# Copy Garmin sync script and engine utilities
COPY rootfs/ /

# Data directory (persisted via HA addon config mapping)
RUN mkdir -p /data /app/logs

# Labels for HA addon
ARG BUILD_ARCH
LABEL \
    io.hass.name="GarminCoach" \
    io.hass.description="AI-powered sport scientist for Garmin athletes" \
    io.hass.arch="${BUILD_ARCH}" \
    io.hass.type="addon" \
    io.hass.version="0.1.0"
