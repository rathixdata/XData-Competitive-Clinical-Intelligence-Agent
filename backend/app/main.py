"""FastAPI application factory."""

from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text

from app.api.v1 import (
    admin,
    alerts,
    ask,
    assets_trials,
    auth,
    entities,
    events,
    feedback,
    landscapes,
    portfolio,
    reports,
)
from app.core.config import get_settings
from app.core.errors import DomainError
from app.core.logging import configure_logging, get_logger
from app.core.metrics import HTTP_LATENCY, HTTP_REQUESTS
from app.core.request_context import set_request_meta
from app.db.session import get_engine

log = get_logger(__name__)


def _setup_tracing(app: FastAPI) -> None:
    s = get_settings()
    if not s.otel_exporter_otlp_endpoint:
        return
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        provider = TracerProvider(resource=Resource.create({"service.name": s.service_name, "deployment.environment": s.env}))
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=s.otel_exporter_otlp_endpoint)))
        trace.set_tracer_provider(provider)
        FastAPIInstrumentor.instrument_app(app, excluded_urls="healthz,readyz,metrics")
        SQLAlchemyInstrumentor().instrument(engine=get_engine())
    except ImportError:
        log.warning("otel_not_installed")


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
    configure_logging()
    log.info("startup", env=get_settings().env)
    yield
    get_engine().dispose()


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(
        title="XData Competitive & Clinical Intelligence Agent API",
        version="1.0.0",
        description=("Evidence-grounded, continuously updated life-sciences competitive intelligence. Decision support "
                     "only: facts are evidence-linked; interpretations are labelled AI hypotheses."),
        lifespan=lifespan,
        docs_url=f"{s.api_prefix}/docs",
        openapi_url=f"{s.api_prefix}/openapi.json",
        redoc_url=None,
    )
    app.add_middleware(CORSMiddleware, allow_origins=s.cors_origins, allow_credentials=True,
                       allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
                       allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Request-ID"])

    @app.middleware("http")
    async def request_context(request: Request, call_next):  # type: ignore[no-untyped-def]
        rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        set_request_meta({"request_id": rid, "ip": request.client.host if request.client else None,
                          "user_agent": request.headers.get("user-agent", "")[:300]})
        start = time.perf_counter()
        response = await call_next(request)
        route = request.scope.get("route")
        path = getattr(route, "path", "unmatched")
        elapsed = time.perf_counter() - start
        HTTP_REQUESTS.labels(request.method, path, str(response.status_code)).inc()
        HTTP_LATENCY.labels(request.method, path).observe(elapsed)
        response.headers["X-Request-ID"] = rid
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = response.headers.get("Cache-Control", "no-store")
        if s.env == "production":
            response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        if path not in ("/healthz", "/readyz", "/metrics"):
            log.info("http_request", method=request.method, path=path, status=response.status_code,
                     ms=round(elapsed * 1000, 1), request_id=rid)
        return response

    @app.exception_handler(DomainError)
    async def domain_error(_req: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code,
                            content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}})

    @app.exception_handler(RequestValidationError)
    async def validation_error(_req: Request, exc: RequestValidationError) -> JSONResponse:
        errs: list[dict[str, Any]] = [{"loc": e.get("loc"), "msg": e.get("msg"), "type": e.get("type")} for e in exc.errors()]
        return JSONResponse(status_code=422, content={"error": {"code": "validation_failed", "message": "invalid request",
                                                                "details": errs}})

    @app.exception_handler(Exception)
    async def unhandled(req: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled_error", path=req.url.path, error=str(exc))
        return JSONResponse(status_code=500, content={"error": {"code": "internal_error",
                                                                "message": "internal server error"}})

    for r in (auth, landscapes, entities, assets_trials, events, feedback, ask, alerts, reports, portfolio, admin):
        app.include_router(r.router, prefix=s.api_prefix)

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict:
        return {"status": "ok"}

    @app.get("/readyz", include_in_schema=False)
    def readyz() -> JSONResponse:
        checks = {}
        try:
            with get_engine().connect() as c:
                c.execute(text("SELECT 1"))
            checks["database"] = "ok"
        except Exception as e:  # noqa: BLE001
            checks["database"] = f"error: {type(e).__name__}"
        try:
            import redis

            redis.Redis.from_url(s.redis_url, socket_timeout=0.5).ping()
            checks["redis"] = "ok"
        except Exception as e:  # noqa: BLE001
            checks["redis"] = f"error: {type(e).__name__}"
        ok = all(v == "ok" for v in checks.values())
        return JSONResponse(status_code=200 if ok else 503, content={"status": "ok" if ok else "degraded", "checks": checks})

    @app.get("/metrics", include_in_schema=False)
    def metrics() -> PlainTextResponse:
        return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    _setup_tracing(app)
    return app


app = create_app()
