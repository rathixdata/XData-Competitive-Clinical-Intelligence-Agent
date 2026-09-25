# syntax=docker/dockerfile:1.7
# -----------------------------------------------------------------------------
# XData CI Agent - web UI. Vite build on node, served by unprivileged nginx.
# -----------------------------------------------------------------------------

# ---- build ------------------------------------------------------------------
FROM node:22-alpine AS build
WORKDIR /src
ENV CI=true
COPY package.json package-lock.json* ./
RUN npm ci --no-audit --no-fund
COPY . .
# Vite only inlines VITE_* vars at build time; the API is reached via same-origin /api.
ARG VITE_API_BASE_URL=/api/v1
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}
RUN npm run build

# ---- runtime ----------------------------------------------------------------
# nginx-unprivileged runs as uid 101 and listens on 8080 (no root, no NET_BIND_SERVICE).
FROM nginxinc/nginx-unprivileged:1.29-alpine AS runtime
LABEL org.opencontainers.image.title="xdata-ci-web" \
      org.opencontainers.image.description="XData Competitive & Clinical Intelligence Agent - web UI"

# Upstream API host:port is templated so k8s / compose can point at the right service.
ENV XDATA_API_UPSTREAM_HOST=api:8000
COPY nginx.conf /etc/nginx/templates/default.conf.template
COPY --from=build --chown=101:101 /src/dist /usr/share/nginx/html

USER 101
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
  CMD wget -q -O /dev/null http://127.0.0.1:8080/nginx-health || exit 1
