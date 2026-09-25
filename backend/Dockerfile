# syntax=docker/dockerfile:1.7
# -----------------------------------------------------------------------------
# XData CI Agent - backend image (API, Celery worker, Celery beat, migrations).
# One image, several entrypoints: the default CMD serves the API; compose / k8s
# override the command for worker, beat, migrate and CLI jobs.
# -----------------------------------------------------------------------------

ARG PYTHON_VERSION=3.11

# ---- builder: compile wheels into an isolated venv --------------------------
FROM python:${PYTHON_VERSION}-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential \
 && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /build
# Install dependencies first (better layer caching), then the package itself.
COPY pyproject.toml ./
COPY app ./app
RUN pip install --upgrade pip setuptools wheel \
 && pip install ".[otel]"

# ---- runtime: slim, no compilers, non-root ----------------------------------
FROM python:${PYTHON_VERSION}-slim AS runtime

LABEL org.opencontainers.image.title="xdata-ci-backend" \
      org.opencontainers.image.description="XData Competitive & Clinical Intelligence Agent - API / worker" \
      org.opencontainers.image.source="https://github.com/xdata/XData-Competitive-Clinical-Intelligence-Agent"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1 \
    PATH="/opt/venv/bin:$PATH" \
    WEB_CONCURRENCY=2 \
    PORT=8000 \
    XDATA_OBJECT_STORE_LOCAL_PATH=/tmp/xdata-objects

# Only the runtime shared lib psycopg/libpq may need; psycopg[binary] bundles libpq,
# so nothing extra is required. Apply security updates to the base.
RUN apt-get update \
 && apt-get upgrade -y --no-install-recommends \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --system --gid 10001 xdata \
 && useradd --system --uid 10001 --gid 10001 --home-dir /app --shell /usr/sbin/nologin xdata

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY --chown=10001:10001 alembic.ini ./alembic.ini
COPY --chown=10001:10001 alembic ./alembic
COPY --chown=10001:10001 app ./app

USER 10001:10001
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import os,urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:%s/healthz' % os.environ.get('PORT','8000'), timeout=4).status == 200 else 1)"

# sh -c so WEB_CONCURRENCY / PORT are expanded at runtime. exec keeps uvicorn as PID 1
# so SIGTERM triggers a graceful shutdown.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers ${WEB_CONCURRENCY:-2} --proxy-headers --forwarded-allow-ips='*' --no-server-header"]
