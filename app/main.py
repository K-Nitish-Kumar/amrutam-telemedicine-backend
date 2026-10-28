import hmac
import json
import logging
import time
import uuid

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from sqlalchemy import text

from app.api import router
from app.config import get_settings
from app.db import engine
from app.rate_limit import RateLimitMiddleware

settings = get_settings()
logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO),
                    format='%(message)s')
logger = logging.getLogger("amrutam")
requests = Counter("amrutam_http_requests_total", "HTTP requests", ["method", "route", "status"])
latencies = Histogram("amrutam_http_duration_seconds", "Request latency", ["method", "route"])

app = FastAPI(title="Amrutam Telemedicine API", version="1.0.0",
              description="PostgreSQL-first REST API with MFA, RBAC, idempotent booking and audit trails")
app.add_middleware(CORSMiddleware, allow_origins=settings.allowed_origins, allow_credentials=False,
                   allow_methods=["GET", "POST", "PUT", "PATCH"], allow_headers=["Authorization", "Content-Type", "Idempotency-Key"])
app.add_middleware(RateLimitMiddleware)
app.include_router(router)


@app.middleware("http")
async def request_observability(request, call_next):
    began = time.perf_counter()
    request_id = str(uuid.uuid4())
    code = 500
    try:
        response = await call_next(request)
        code = response.status_code
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response
    finally:
        elapsed = time.perf_counter() - began
        route = getattr(request.scope.get("route"), "path", None) or "unknown"
        requests.labels(request.method, route, str(code)).inc()
        latencies.labels(request.method, route).observe(elapsed)
        # No query params, request bodies, auth headers, patient name, or drug details.
        logger.info(json.dumps({"event": "http_request", "request_id": request_id,
                                "method": request.method, "route": route,
                                "status": code, "duration_ms": round(elapsed * 1000, 2)}))


@app.get("/health/live", tags=["Operations"], include_in_schema=False)
def live():
    return {"status": "alive"}


@app.get("/health/ready", tags=["Operations"], include_in_schema=False)
def ready():
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        if settings.rate_limit_backend == "redis":
            import redis
            redis.Redis.from_url(settings.redis_url, socket_timeout=1).ping()
    except Exception:
        raise HTTPException(status_code=503, detail="Not ready") from None
    return {"status": "ready"}


@app.get("/metrics", include_in_schema=False)
def metrics(authorization: str | None = Header(default=None)):
    expected = f"Bearer {settings.metrics_token}"
    if not settings.metrics_token or not authorization or not hmac.compare_digest(authorization, expected):
        raise HTTPException(status_code=403, detail="Metrics token required")
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


if settings.tracing_enabled:
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    provider = TracerProvider(resource=Resource.create({"service.name": "amrutam-api"}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint)))
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app, tracer_provider=provider,
        excluded_urls="/health/live,/health/ready,/metrics")
