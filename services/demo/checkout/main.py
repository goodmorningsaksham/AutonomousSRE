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
from prometheus_client import Counter, Histogram, make_asgi_app
import structlog

otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
tracer_provider = TracerProvider()
tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp_endpoint)))
trace.set_tracer_provider(tracer_provider)
tracer = trace.get_tracer("checkout-service")

structlog.configure(processors=[
    structlog.processors.TimeStamper(fmt="iso"),
    structlog.processors.add_log_level,
    structlog.processors.JSONRenderer(),
])
logger = structlog.get_logger()

REQUEST_COUNT = Counter("http_requests_total", "HTTP requests", ["method", "endpoint", "status"])
REQUEST_LATENCY = Histogram("http_request_duration_seconds", "Latency", ["method", "endpoint"])

PORT = int(os.getenv("PORT", "3001"))
PAYMENT_URL = os.getenv("PAYMENT_URL", "http://localhost:3002")
INVENTORY_URL = os.getenv("INVENTORY_URL", "http://localhost:3003")

app = FastAPI(title="Checkout Service")
FastAPIInstrumentor.instrument_app(app)
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "checkout"}


@app.post("/api/v1/checkout")
async def checkout(item_id: str = "item-1", quantity: int = 1, amount: float = 99.99):
    start = time.monotonic()
    with tracer.start_as_current_span("checkout"):
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
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


if __name__ == "__main__":
    uvicorn.run("services.demo.checkout.main:app", host="0.0.0.0", port=PORT, reload=False)
