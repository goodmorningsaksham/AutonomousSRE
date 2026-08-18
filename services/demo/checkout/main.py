"""Checkout Service — calls Payment and Inventory."""
from __future__ import annotations

import os
import time
import random

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from prometheus_client import CollectorRegistry, Counter, Histogram, make_asgi_app
import structlog

otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
try:
    tracer_provider = TracerProvider()
    tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp_endpoint)))
    trace.set_tracer_provider(tracer_provider)
except Exception:
    pass
tracer = trace.get_tracer("checkout-service")

structlog.configure(processors=[
    structlog.processors.TimeStamper(fmt="iso"),
    structlog.processors.add_log_level,
    structlog.processors.JSONRenderer(),
])
logger = structlog.get_logger()

REGISTRY = CollectorRegistry(auto_describe=True)
REQUEST_COUNT = Counter("http_requests_total", "HTTP requests", ["method", "endpoint", "status"], registry=REGISTRY)
REQUEST_LATENCY = Histogram("http_request_duration_seconds", "Latency", ["method", "endpoint"], registry=REGISTRY)

PORT = int(os.getenv("PORT", "3001"))
PAYMENT_URL = os.getenv("PAYMENT_URL", "http://localhost:3002")
INVENTORY_URL = os.getenv("INVENTORY_URL", "http://localhost:3003")

app = FastAPI(title="Checkout Service")
FastAPIInstrumentor.instrument_app(app)
metrics_app = make_asgi_app(registry=REGISTRY)
app.mount("/metrics", metrics_app)


# ── Failure injection state ───────────────────────────────────────────────────
_failure_state = {
    "inject_timeout": False,
    "add_latency_ms": 0,
}


@app.get("/health")
async def health():
    return {"status": "ok", "service": "checkout"}


@app.post("/api/v1/checkout")
async def checkout(item_id: str = "item-1", quantity: int = 1, amount: float = 99.99):
    start = time.monotonic()
    with tracer.start_as_current_span("checkout"):
        if _failure_state["add_latency_ms"] > 0:
            import asyncio
            await asyncio.sleep(_failure_state["add_latency_ms"] / 1000)

        call_timeout = 0.5 if _failure_state["inject_timeout"] else 10.0

        try:
            async with httpx.AsyncClient(timeout=call_timeout) as client:
                # Check inventory
                inv_resp = await client.get(f"{INVENTORY_URL}/api/v1/inventory/{item_id}")
                if inv_resp.status_code != 200:
                    REQUEST_COUNT.labels("POST", "/api/v1/checkout", "503").inc()
                    raise HTTPException(status_code=503, detail="Inventory service unavailable")

                # Process payment
                pay_resp = await client.post(f"{PAYMENT_URL}/api/v1/payments", params={"amount": amount})
                if pay_resp.status_code != 200:
                    REQUEST_COUNT.labels("POST", "/api/v1/checkout", str(pay_resp.status_code)).inc()
                    raise HTTPException(status_code=502, detail="Payment failed")

            duration = time.monotonic() - start
            REQUEST_COUNT.labels("POST", "/api/v1/checkout", "200").inc()
            REQUEST_LATENCY.labels("POST", "/api/v1/checkout").observe(duration)
            logger.info("Checkout completed", item_id=item_id, amount=amount)
            return {"status": "completed", "item_id": item_id, "amount": amount}

        except HTTPException:
            raise
        except Exception as exc:
            duration = time.monotonic() - start
            REQUEST_COUNT.labels("POST", "/api/v1/checkout", "500").inc()
            REQUEST_LATENCY.labels("POST", "/api/v1/checkout").observe(duration)
            logger.error("Checkout error", error=str(exc))
            raise HTTPException(status_code=500, detail=str(exc))


# ── Failure Injection Endpoints ───────────────────────────────────────────────
@app.post("/admin/inject/dependency-timeout")
async def inject_dependency_timeout():
    """Artificially shorten client timeout to simulate upstream dependency timeouts."""
    _failure_state["inject_timeout"] = True
    logger.warning("FAILURE INJECTED: dependency timeout")
    return {"injected": "dependency_timeout"}


@app.post("/admin/inject/latency")
async def inject_latency(ms: int = 2000):
    """Add artificial latency to checkout service."""
    _failure_state["add_latency_ms"] = ms
    logger.warning("FAILURE INJECTED: latency", ms=ms)
    return {"injected": "latency", "ms": ms}


@app.post("/admin/recover")
async def recover():
    """Clear failure injections on checkout service."""
    _failure_state["inject_timeout"] = False
    _failure_state["add_latency_ms"] = 0
    logger.info("Checkout failure injections cleared")
    return {"recovered": True}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)
