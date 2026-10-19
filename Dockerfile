# syntax=docker/dockerfile:1.7
# -----------------------------------------------------------------------------
# XData CI Agent - all-in-one image for single-service hosting (render.yaml).
# One container serves the web app and the API, and runs the connector schedule,
# change processing and alert delivery in-process (no separate worker/beat/broker).
# The multi-service images in backend/ and frontend/ remain the production
# topology for Kubernetes (deploy/k8s) and docker compose.
# -----------------------------------------------------------------------------

# ---- web app build ----------------------------------------------------------
FROM node:22-alpine AS web
WORKDIR /src
ENV CI=true
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- python dependencies ----------------------------------------------------
FROM python:3.11-slim AS builder
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONDONTWRITEBYTECODE=1
RUN apt-get update && apt-get install -y --no-install-recommends build-essential && rm -rf /var/lib/apt/lists/*
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
WORKDIR /build
COPY backend/pyproject.toml ./
COPY backend/app ./app
RUN pip install --upgrade pip setuptools wheel && pip install .

# ---- runtime ----------------------------------------------------------------
FROM python:3.11-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONFAULTHANDLER=1 \
    PATH="/opt/venv/bin:$PATH" PORT=8000 WEB_CONCURRENCY=1 \
    XDATA_STATIC_DIR=/app/web \
    XDATA_INPROCESS_SCHEDULER=true \
    XDATA_CELERY_EAGER=true \
    XDATA_OBJECT_STORE_LOCAL_PATH=/app/data/objects
RUN apt-get update && apt-get upgrade -y --no-install-recommends && rm -rf /var/lib/apt/lists/* \
 && groupadd --system --gid 10001 xdata \
 && useradd --system --uid 10001 --gid 10001 --home-dir /app --shell /usr/sbin/nologin xdata
COPY --from=builder /opt/venv /opt/venv
WORKDIR /app
COPY --chown=10001:10001 backend/alembic.ini ./alembic.ini
COPY --chown=10001:10001 backend/alembic ./alembic
COPY --chown=10001:10001 backend/app ./app
COPY --chown=10001:10001 --from=web /src/dist ./web
COPY --chown=10001:10001 deploy/render/start.sh ./start.sh
RUN mkdir -p /app/data/objects && chown -R 10001:10001 /app/data && chmod 0755 /app/start.sh
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import os,urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:%s/healthz' % os.environ.get('PORT','8000'), timeout=4).status == 200 else 1)"
CMD ["/app/start.sh"]
