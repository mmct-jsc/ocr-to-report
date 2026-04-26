# syntax=docker/dockerfile:1.9
# OCR-to-Report Web Operations Console — Vite/React build → nginx runtime.
#
# Two stages: a `node:20-alpine` builder produces a static bundle, then a
# minimal `nginx:1.27-alpine` runtime serves it. The runtime image is
# read-only-friendly (only /var/cache/nginx, /var/run, /tmp need writes,
# all covered by tmpfs in compose) and runs as a non-root user.

# ─────────────────────────── Stage 1: builder ────────────────
FROM node:20-alpine AS builder

ENV CI=1 \
    NPM_CONFIG_FUND=false \
    NPM_CONFIG_AUDIT=false

WORKDIR /build

# Copy the SDK first so the workspace symlink resolves during install.
# The `web` package consumes `@ocr-to-report/sdk` via `file:../sdk-ts`.
COPY sdk-ts/package.json sdk-ts/package-lock.json sdk-ts/tsconfig.json ./sdk-ts/
COPY sdk-ts/src/                                                       ./sdk-ts/src/

COPY web/package.json web/package-lock.json* ./web/
WORKDIR /build/web
RUN npm ci

# Build the SPA. The Vite alias resolves `@ocr-to-report/sdk` to the SDK
# source so we don't need a separate tsc build step for the SDK.
COPY web/ ./
COPY sdk-ts/ ../sdk-ts/
RUN npm run build

# ─────────────────────────── Stage 2: runtime ────────────────
FROM nginx:1.27-alpine AS runtime

# Drop default site + use ours.
RUN rm /etc/nginx/conf.d/default.conf
COPY docker/web.nginx.conf /etc/nginx/conf.d/web.conf

# Static bundle.
COPY --from=builder /build/web/dist /usr/share/nginx/html

# nginx writes its pid under /var/run; compose mounts a tmpfs there to
# satisfy `read_only: true` without granting filesystem writes.
EXPOSE 80

# nginx:alpine ships a `nginx` user; entrypoint already drops to it for
# workers. Foreground so docker can supervise it.
CMD ["nginx", "-g", "daemon off;"]
