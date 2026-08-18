"""
Payment Service — Demo Production Service

Realistic FastAPI service with:
- PostgreSQL connection pool (configurable)
- Prometheus metrics (error rate, latency, DB connections)
- OpenTelemetry traces
- Structured JSON logs
- Health endpoint
- Failure injection endpoints (for demo)
"""
from __future__ import annotations

import asyncio
import os
import random
import time
from contextlib import asynccontextmanager

import asyncpg
import uvicorn
from fastapi import FastAPI, HTTPException, Response
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from prometheus_client import Counter, Gauge, Histogram, make_asgi_app
import structlog

# ── OpenTelemetry setup ───────────────────────────────────────────────────────
otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
tracer_provider = TracerProvider()
tracer_provider.add_span_processor(
    BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp_endpoint))
)
trace.set_tracer_provider(tracer_provider)
tracer = trace.get_tracer("payment-service")

# ── Logging ───────────────────────────────────────────────────────────────────
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.JSONRenderer(),
    ],
)
logger = structlog.get_logger()

# ── Prometheus Metrics ────────────────────────────────────────────────────────
REQUEST_COUNT = Counter("http_requests_total", "Total HTTP requests", ["method", "endpoint", "status"])
REQUEST_LATENCY = Histogram("http_request_duration_seconds", "Request latency", ["method", "endpoint"])
DB_POOL_USED = Gauge("db_pool_connections_used", "DB pool connections in use")
DB_POOL_MAX = Gauge("db_pool_connections_max", "DB pool max connections")

PORT = int(os.getenv("PORT", "3002"))
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://demo:demo_secret@localhost:5433/demo")
MAX_POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "10"))

# ── Failure injection state ───────────────────────────────────────────────────
_failure_state = {
    "exhaust_pool": False,
    "add_latency_ms": 0,
    "error_rate": 0.0,
}

pool: asyncpg.Pool | None = None
_held_connections: list = []


@asynccontextmanager
async def lifespan(app: FastAPI):
    global pool
    try:
        pool = await asyncpg.create_pool(
            DATABASE_URL,
            min_size=1,
            max_size=MAX_POOL_SIZE,
        )
        # Create demo table
        async with pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS payments (
                    id SERIAL PRIMARY KEY,
                    amount DECIMAL(10,2),
                    status VARCHAR(20),
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)
        DB_POOL_MAX.set(MAX_POOL_SIZE)
        logger.info("Payment service started", port=PORT, pool_size=MAX_POOL_SIZE)
    except Exception as exc:
        logger.warning("Could not connect to DB", error=str(exc))
    yield
    if pool:
        await pool.close()


app = FastAPI(title="Payment Service", lifespan=lifespan)
FastAPIInstrumentor.instrument_app(app)
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)


def _track(method: str, endpoint: str, status: int, duration: float):
    REQUEST_COUNT.labels(method=method, endpoint=endpoint, status=str(status)).inc()
    REQUEST_LATENCY.labels(method=method, endpoint=endpoint).observe(duration)


@app.get("/health")
async def health():
    pool_size = pool.get_size() if pool else 0
    idle = pool.get_idle_size() if pool else 0
    DB_POOL_USED.set(pool_size - idle if pool else 0)
    return {"status": "ok", "service": "payment", "pool_size": pool_size, "idle": idle}


@app.post("/api/v1/payments")
async def create_payment(amount: float = 100.0):
    start = time.monotonic()
    with tracer.start_as_current_span("create-payment"):
        # Simulate failure injection
        if _failure_state["error_rate"] > 0 and random.random() < _failure_state["error_rate"]:
            _track("POST", "/api/v1/payments", 500, time.monotonic() - start)
            raise HTTPException(status_code=500, detail="Injected error")

        if _failure_state["add_latency_ms"] > 0:
            await asyncio.sleep(_failure_state["add_latency_ms"] / 1000)

        if pool is None:
            _track("POST", "/api/v1/payments", 503, time.monotonic() - start)
            raise HTTPException(status_code=503, detail="Database unavailable")

        try:
            if pool:
                in_use = pool.get_size() - pool.get_idle_size()
                DB_POOL_USED.set(in_use)

            async with pool.acquire(timeout=5.0) as conn:
                row = await conn.fetchrow(
                    "INSERT INTO payments (amount, status) VALUES ($1, $2) RETURNING id",
                    amount, "completed"
                )
                payment_id = row["id"]

            duration = time.monotonic() - start
            _track("POST", "/api/v1/payments", 200, duration)
            logger.info("Payment created", payment_id=payment_id, amount=amount)
            return {"payment_id": payment_id, "amount": amount, "status": "completed"}

        except asyncio.TimeoutError:
            duration = time.monotonic() - start
            _track("POST", "/api/v1/payments", 500, duration)
            logger.error("DB connection timeout — pool exhausted")
            raise HTTPException(status_code=500, detail="Database connection pool exhausted")

        except Exception as exc:
            duration = time.monotonic() - start
            _track("POST", "/api/v1/payments", 500, duration)
            logger.error("Payment error", error=str(exc))
            raise HTTPException(status_code=500, detail=str(exc))


# ── Failure Injection Endpoints ───────────────────────────────────────────────
_cpu_burn_tasks: list[asyncio.Task] = []
_memory_hog_buffer: list[bytearray] = []


def _burn_cpu(duration_seconds: int = 30):
    start = time.time()
    while time.time() - start < duration_seconds:
        _ = [x**2 for x in range(10000)]


@app.post("/admin/inject/db-exhaustion")
async def inject_db_exhaustion():
    """Hold all DB connections to simulate pool exhaustion."""
    global _held_connections
    if pool:
        for _ in range(MAX_POOL_SIZE):
            try:
                conn = await pool.acquire(timeout=1.0)
                _held_connections.append(conn)
            except Exception:
                break
    _failure_state["exhaust_pool"] = True
    DB_POOL_USED.set(MAX_POOL_SIZE)
    logger.warning("FAILURE INJECTED: DB pool exhaustion")
    return {"injected": "db_exhaustion", "held_connections": len(_held_connections)}


@app.post("/admin/inject/latency")
async def inject_latency(ms: int = 2000):
    """Add artificial latency to all payment requests."""
    _failure_state["add_latency_ms"] = ms
    logger.warning("FAILURE INJECTED: latency", ms=ms)
    return {"injected": "latency", "ms": ms}


@app.post("/admin/inject/error-rate")
async def inject_error_rate(rate: float = 0.5):
    """Inject artificial error rate."""
    _failure_state["error_rate"] = min(1.0, max(0.0, rate))
    logger.warning("FAILURE INJECTED: error rate", rate=rate)
    return {"injected": "error_rate", "rate": rate}


@app.post("/admin/inject/cpu-saturation")
async def inject_cpu_saturation(duration_seconds: int = 30):
    """Spin CPU intensive worker loops."""
    loop = asyncio.get_running_loop()
    task = loop.run_in_executor(None, _burn_cpu, duration_seconds)
    logger.warning("FAILURE INJECTED: cpu saturation", duration=duration_seconds)
    return {"injected": "cpu_saturation", "duration_seconds": duration_seconds}


@app.post("/admin/inject/memory-pressure")
async def inject_memory_pressure(megabytes: int = 256):
    """Allocate memory buffers to create memory pressure."""
    global _memory_hog_buffer
    # Allocate in 10MB chunks
    for _ in range(megabytes // 10):
        _memory_hog_buffer.append(bytearray(10 * 1024 * 1024))
    logger.warning("FAILURE INJECTED: memory pressure", allocated_mb=len(_memory_hog_buffer) * 10)
    return {"injected": "memory_pressure", "allocated_mb": len(_memory_hog_buffer) * 10}


@app.post("/admin/inject/pod-crash")
async def inject_pod_crash():
    """Trigger process termination to simulate container crash loop."""
    logger.warning("FAILURE INJECTED: pod crash triggered")
    asyncio.get_event_loop().call_later(0.1, lambda: os._exit(1))
    return {"injected": "pod_crash", "action": "terminating"}


@app.post("/admin/recover")
async def recover():
    """Clear all failure injections."""
    global _held_connections, _memory_hog_buffer
    for conn in _held_connections:
        try:
            await pool.release(conn)
        except Exception:
            pass
    _held_connections.clear()
    _memory_hog_buffer.clear()
    _failure_state["exhaust_pool"] = False
    _failure_state["add_latency_ms"] = 0
    _failure_state["error_rate"] = 0.0
    DB_POOL_USED.set(0)
    logger.info("All failure injections cleared")
    return {"recovered": True}


if __name__ == "__main__":
    uvicorn.run("services.demo.payment.main:app", host="0.0.0.0", port=PORT, reload=False)
