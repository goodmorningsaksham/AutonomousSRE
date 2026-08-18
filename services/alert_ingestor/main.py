"""
Aegis Alert Ingestor Service

Receives Alertmanager webhook payloads, validates them,
and immediately publishes raw alert events to Kafka (alerts.raw).

Design principle: This endpoint does NO expensive work.
It validates, normalises to a common schema, publishes to Kafka, and returns.
All correlation / investigation happens downstream.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
from datetime import datetime
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from prometheus_client import Counter, make_asgi_app

from common.config.settings import get_settings
from common.events.schemas import (
    AlertSeverity,
    AlertStatus,
    KafkaTopic,
    RawAlertPayload,
    make_alert_raw_event,
)
from common.kafka.admin import ensure_topics_exist
from common.kafka.producer import AegisProducer
from common.logging.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()

# ── Prometheus Metrics ────────────────────────────────────────────────────────
from prometheus_client import CollectorRegistry
REGISTRY = CollectorRegistry(auto_describe=True)
ALERTS_RECEIVED = Counter(
    "aegis_alerts_received_total",
    "Total Alertmanager webhooks received",
    ["severity"],
    registry=REGISTRY,
)
ALERTS_PUBLISHED = Counter(
    "aegis_alerts_published_total",
    "Total alert events published to Kafka",
    registry=REGISTRY,
)
ALERTS_REJECTED = Counter(
    "aegis_alerts_rejected_total",
    "Total alert payloads rejected due to validation errors",
    registry=REGISTRY,
)

producer = AegisProducer()


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    await ensure_topics_exist()
    await producer.start()
    logger.info("Alert ingestor started", port=settings.aegis_ingestor_port)
    yield
    await producer.stop()
    logger.info("Alert ingestor stopped")


app = FastAPI(
    title="Aegis Alert Ingestor",
    description="Receives Alertmanager webhooks and publishes to Kafka",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# Mount Prometheus metrics endpoint
metrics_app = make_asgi_app(registry=REGISTRY)
app.mount("/metrics", metrics_app)


# ── Alertmanager Webhook Schema ───────────────────────────────────────────────
class AlertmanagerAlert(BaseModel):
    status: str = "firing"
    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)
    startsAt: str | None = None
    endsAt: str | None = None
    generatorURL: str | None = None
    fingerprint: str | None = None


class AlertmanagerPayload(BaseModel):
    version: str = "4"
    groupKey: str | None = None
    truncatedAlerts: int = 0
    status: str = "firing"
    receiver: str = "aegis-webhook"
    groupLabels: dict[str, str] = Field(default_factory=dict)
    commonLabels: dict[str, str] = Field(default_factory=dict)
    commonAnnotations: dict[str, str] = Field(default_factory=dict)
    externalURL: str | None = None
    alerts: list[AlertmanagerAlert] = Field(default_factory=list)


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def _fingerprint(labels: dict[str, str]) -> str:
    """Deterministic fingerprint from alert labels for deduplication."""
    canonical = json.dumps(sorted(labels.items()), sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()[:32]


def _normalize_severity(labels: dict) -> AlertSeverity:
    severity = labels.get("severity", "warning").lower()
    mapping = {
        "critical": AlertSeverity.CRITICAL,
        "error": AlertSeverity.HIGH,
        "warning": AlertSeverity.WARNING,
        "info": AlertSeverity.INFO,
    }
    return mapping.get(severity, AlertSeverity.WARNING)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "alert-ingestor"}


@app.post("/webhooks/alertmanager", status_code=status.HTTP_202_ACCEPTED)
async def alertmanager_webhook(
    payload: AlertmanagerPayload,
    request: Request,
) -> dict[str, Any]:
    """
    Receives Alertmanager webhook, validates, and publishes to Kafka.
    Returns immediately — all processing is asynchronous.
    """
    published_count = 0
    failed_count = 0

    for alert in payload.alerts:
        try:
            labels = {**payload.commonLabels, **alert.labels}
            annotations = {**payload.commonAnnotations, **alert.annotations}

            service = labels.get("service") or labels.get("job") or labels.get("container") or "unknown"
            namespace = labels.get("namespace") or "default"
            alert_name = labels.get("alertname") or "UnknownAlert"
            severity = _normalize_severity(labels)
            status_val = AlertStatus.FIRING if alert.status == "firing" else AlertStatus.RESOLVED

            raw_payload = RawAlertPayload(
                alert_name=alert_name,
                service=service,
                namespace=namespace,
                severity=severity,
                status=status_val,
                labels=labels,
                annotations=annotations,
                starts_at=_parse_dt(alert.startsAt),
                ends_at=_parse_dt(alert.endsAt),
                generator_url=alert.generatorURL,
                raw_payload=alert.model_dump(),
            )

            event = make_alert_raw_event(raw_payload)

            await producer.send(KafkaTopic.ALERTS_RAW.value, event)
            await _ship_log_to_loki(
                service=service,
                alert_name=alert_name,
                message=f"Alert firing: {annotations.get('summary', '')} — {annotations.get('description', '')}",
                severity=severity.value,
            )

            ALERTS_RECEIVED.labels(severity=severity.value).inc()
            ALERTS_PUBLISHED.inc()
            published_count += 1

            logger.info(
                "Alert published to Kafka",
                alert_name=alert_name,
                service=service,
                severity=severity.value,
                status=status_val.value,
                event_id=event.event_id,
            )

        except Exception as exc:
            ALERTS_REJECTED.inc()
            failed_count += 1
            logger.error("Failed to process alert", error=str(exc), exc_info=True)

    return {
        "status": "accepted",
        "published": published_count,
        "failed": failed_count,
    }


async def _ship_log_to_loki(service: str, alert_name: str, message: str, severity: str = "error"):
    try:
        import httpx, time
        now_ns = str(int(time.time() * 1e9))
        payload = {
            "streams": [
                {
                    "stream": {
                        "service": service,
                        "job": service,
                        "level": "error" if severity in ["critical", "high", "error"] else "warning",
                        "app": service,
                        "env": "production",
                    },
                    "values": [
                        [now_ns, f"[{severity.upper()}] [ALERT_FIRING] {alert_name}: {message}"]
                    ]
                }
            ]
        }
        async with httpx.AsyncClient(timeout=0.8) as client:
            for host in ["aegis-loki", "loki", "localhost", "127.0.0.1"]:
                try:
                    await client.post(f"http://{host}:3100/loki/api/v1/push", json=payload)
                    break
                except Exception:
                    pass
    except Exception:
        pass


@app.post("/api/v1/alerts", status_code=status.HTTP_202_ACCEPTED)
async def manual_alert(payload: RawAlertPayload) -> dict[str, Any]:
    """Manual alert injection endpoint for testing."""
    event = make_alert_raw_event(payload)
    await producer.send(KafkaTopic.ALERTS_RAW.value, event)
    await _ship_log_to_loki(
        service=payload.service,
        alert_name=payload.alert_name,
        message=f"{payload.annotations.get('summary', '')} — {payload.annotations.get('description', '')}",
        severity=payload.severity.value,
    )
    ALERTS_RECEIVED.labels(severity=payload.severity.value).inc()
    ALERTS_PUBLISHED.inc()
    return {"status": "accepted", "event_id": event.event_id}


if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=settings.aegis_ingestor_port,
    )
