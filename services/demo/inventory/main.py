"""Inventory Service — Redis-backed with failure injection."""
from __future__ import annotations

import os
import time

import redis.asyncio as aioredis
import uvicorn
from fastapi import FastAPI, HTTPException
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from prometheus_client import Counter, Histogram, make_asgi_app
import structlog

otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
tracer_provider = TracerProvider()
tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp_endpoint)))
trace.set_tracer_provider(tracer_provider)
tracer = trace.get_tracer("inventory-service")

structlog.configure(processors=[
    structlog.processors.TimeStamper(fmt="iso"),
    structlog.processors.add_log_level,
    structlog.processors.JSONRenderer(),
])
logger = structlog.get_logger()

REQUEST_COUNT = Counter("http_requests_total", "HTTP requests", ["method", "endpoint", "status"])
REQUEST_LATENCY = Histogram("http_request_duration_seconds", "Latency", ["method", "endpoint"])

PORT = int(os.getenv("PORT", "3003"))
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6380/0")

app = FastAPI(title="Inventory Service")
FastAPIInstrumentor.instrument_app(app)
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)

redis_client = aioredis.from_url(REDIS_URL, decode_responses=True)


@app.get("/health")
async def health():
    try:
        await redis_client.ping()
        return {"status": "ok", "service": "inventory", "redis": "connected"}
    except Exception:
        return {"status": "degraded", "service": "inventory", "redis": "disconnected"}


@app.get("/api/v1/inventory/{item_id}")
async def get_inventory(item_id: str):
    start = time.monotonic()
    with tracer.start_as_current_span("get-inventory"):
        try:
            cached = await redis_client.get(f"inventory:{item_id}")
            if not cached:
                # Simulate DB lookup + cache
                quantity = 100 - hash(item_id) % 50
                await redis_client.setex(f"inventory:{item_id}", 300, str(quantity))
                cached = str(quantity)

            duration = time.monotonic() - start
            REQUEST_COUNT.labels("GET", "/api/v1/inventory/{item_id}", "200").inc()
            REQUEST_LATENCY.labels("GET", "/api/v1/inventory/{item_id}").observe(duration)
            return {"item_id": item_id, "quantity": int(cached)}

        except Exception as exc:
            duration = time.monotonic() - start
            REQUEST_COUNT.labels("GET", "/api/v1/inventory/{item_id}", "500").inc()
            REQUEST_LATENCY.labels("GET", "/api/v1/inventory/{item_id}").observe(duration)
            logger.error("Inventory error", item_id=item_id, error=str(exc))
            raise HTTPException(status_code=500, detail=str(exc))


if __name__ == "__main__":
    uvicorn.run("services.demo.inventory.main:app", host="0.0.0.0", port=PORT, reload=False)
