ARG BUILD_FROM
ARG BUILD_ARCH

# ──────────────────────────────────────────────
# Stage 1: Build the Next.js application
# ──────────────────────────────────────────────
FROM node:22-alpine AS builder

RUN apk add --no-cache git
RUN corepack enable && corepack prepare pnpm@latest --activate

WORKDIR /build

# Clone the app source from GitHub
# ADD fetches latest commit ref — Docker busts cache when it changes
ARG APP_REPO=askb/ha-garmin-fitness-coach-app
ARG APP_REF=main
ADD "https://api.github.com/repos/${APP_REPO}/git/refs/heads/${APP_REF}" /tmp/cachebust.json
RUN git clone --depth=1 --branch="${APP_REF}" \
      "https://github.com/${APP_REPO}.git" .

# Create minimal .env for build (real values injected at runtime by s6 run script)
RUN echo 'DATABASE_URL="postgresql://build:build@localhost:5432/build"' > .env && \
    echo 'POSTGRES_URL="postgresql://build:build@localhost:5432/build"' >> .env && \
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

# ──────────────────────────────────────────────
# Stage 2: Production runtime on HA base image
# ──────────────────────────────────────────────
FROM ${BUILD_FROM}

# Install Node.js, Python (for Garmin sync), PostgreSQL
RUN apk add --no-cache \
    nodejs=~22 \
    npm \
    python3 \
    py3-pip \
    postgresql16 \
    postgresql16-client \
    curl \
    tzdata

# Create PostgreSQL data directory
RUN mkdir -p /data/postgresql && chown -R postgres:postgres /data/postgresql

# Install garminconnect Python package for direct Garmin API sync
RUN pip3 install --break-system-packages garminconnect flask psycopg2-binary

WORKDIR /app

# Copy built Next.js standalone app (includes all bundled dependencies)
COPY --from=builder /build/apps/nextjs/.next/standalone ./
COPY --from=builder /build/apps/nextjs/.next/static ./apps/nextjs/.next/static
COPY --from=builder /build/apps/nextjs/public ./apps/nextjs/public

# Copy DB schema files for drizzle-kit push at runtime (skip pnpm catalog package.json)
COPY --from=builder /build/packages/db/src /app/packages/db/src
COPY --from=builder /build/packages/db/drizzle.config.ts /app/packages/db/drizzle.config.ts
COPY --from=builder /build/packages/db/tsconfig.json /app/packages/db/tsconfig.json
RUN cd /app/packages/db && \
    echo '{"name":"db-push","private":true}' > package.json && \
    npm install drizzle-kit drizzle-orm drizzle-zod pg zod typescript @types/pg

# Copy addon rootfs (s6 service, sync script, AI backend lib)
COPY rootfs /

# Ensure s6-overlay init and run scripts are executable
RUN chmod +x /init 2>/dev/null || true \
    && find /etc/s6-overlay -name "run" -exec chmod +x {} \;

# Data directory (persisted via HA addon config mapping)
RUN mkdir -p /data /data/garmin-tokens /app/logs

# Labels for HA addon
ARG BUILD_ARCH
LABEL \
    io.hass.name="GarminCoach" \
    io.hass.description="AI-powered sport scientist for Garmin athletes" \
    io.hass.arch="${BUILD_ARCH}" \
    io.hass.type="addon" \
    io.hass.version="0.2.0"
