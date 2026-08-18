"""
Alert Correlator Worker

Consumes alerts.raw events from Kafka, normalizes them,
and applies deterministic correlation rules to group related alerts
into incidents. Uses PostgreSQL as the incident state store
and the transactional outbox for Kafka publishing.

Correlation strategy:
1. Parse and fingerprint incoming alert
2. Check deduplication (same fingerprint within time window)
3. Find existing open incidents for the same service+namespace
4. Check dependency graph for upstream failures
5. Group into existing incident or create new one
6. Write incident + outbox event in one transaction
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from common.config.settings import get_settings
from common.events.schemas import (
    AlertSeverity,
    AlertStatus,
    IncidentCreatedPayload,
    IncidentSeverity,
    IncidentStatus,
    IncidentUpdatedPayload,
    KafkaTopic,
    NormalizedAlertPayload,
    RawAlertPayload,
    make_alert_normalized_event,
    make_incident_created_event,
    make_incident_updated_event,
    new_event_id,
    utcnow,
)
from common.kafka.admin import ensure_topics_exist
from common.kafka.consumer import AegisConsumer
from common.logging.logger import get_logger
from database.models.models import Alert, Incident, IncidentEvent, OutboxEvent, ProcessedEvent
from database.session import AsyncSessionLocal

logger = get_logger(__name__)
settings = get_settings()

CONSUMER_GROUP = settings.kafka_group_id_correlator

# ── Service dependency graph ──────────────────────────────────────────────────
# This determines how alerts from dependent services get correlated.
# checkout → payment → postgres
# checkout → inventory → redis
SERVICE_DEPENDENCY_GRAPH: dict[str, list[str]] = {
    "checkout": ["payment", "inventory"],
    "payment": ["postgres", "demo-postgres"],
    "inventory": ["redis", "demo-redis"],
}


def _get_root_services(service: str) -> set[str]:
    """Walk dependency graph upstream to find all services that might be affected."""
    dependents: set[str] = {service}
    for svc, deps in SERVICE_DEPENDENCY_GRAPH.items():
        if service in deps:
            dependents.add(svc)
    return dependents


def _severity_rank(s: str) -> int:
    return {"critical": 4, "high": 3, "medium": 2, "low": 1, "warning": 2, "info": 0}.get(s.lower(), 0)


def _incident_severity(alert_severity: str) -> IncidentSeverity:
    mapping = {
        "critical": IncidentSeverity.CRITICAL,
        "high": IncidentSeverity.HIGH,
        "warning": IncidentSeverity.MEDIUM,
        "info": IncidentSeverity.LOW,
    }
    return mapping.get(alert_severity.lower(), IncidentSeverity.MEDIUM)


def _fingerprint_alert(alert_name: str, service: str, namespace: str, labels: dict) -> str:
    key = f"{alert_name}:{service}:{namespace}"
    return hashlib.sha256(key.encode()).hexdigest()[:32]


def _normalize_alert(raw: dict) -> NormalizedAlertPayload:
    """Convert a raw alert event payload dict to a NormalizedAlertPayload."""
    p = raw.get("payload", raw)
    labels = p.get("labels", {})
    fp = _fingerprint_alert(
        p.get("alert_name", ""),
        p.get("service", "unknown"),
        p.get("namespace", "default"),
        labels,
    )
    return NormalizedAlertPayload(
        alert_id=new_event_id(),
        alert_name=p.get("alert_name", "UnknownAlert"),
        service=p.get("service", "unknown"),
        namespace=p.get("namespace", "default"),
        severity=AlertSeverity(p.get("severity", "warning")),
        status=AlertStatus(p.get("status", "firing")),
        labels=labels,
        summary=p.get("annotations", {}).get("summary", p.get("alert_name", "")),
        description=p.get("annotations", {}).get("description", ""),
        starts_at=None,
        fingerprint=fp,
    )


async def _is_duplicate_alert(session: AsyncSession, fingerprint: str, window_seconds: int) -> bool:
    """Check if we already have a recent alert with this fingerprint."""
    cutoff = datetime.now(tz=timezone.utc) - timedelta(seconds=window_seconds)
    result = await session.execute(
        select(Alert).where(
            and_(
                Alert.fingerprint == fingerprint,
                Alert.created_at >= cutoff,
                Alert.status == "firing",
            )
        ).limit(1)
    )
    return result.scalar_one_or_none() is not None


async def _find_open_incident(session: AsyncSession, service: str, namespace: str) -> Optional[Incident]:
    """Find an existing non-resolved incident for this service or its dependents."""
    # Include upstream services that might be the root cause
    related_services = _get_root_services(service) | {service}

    terminal_statuses = [IncidentStatus.RESOLVED.value, IncidentStatus.FAILED.value]
    cutoff = datetime.now(tz=timezone.utc) - timedelta(seconds=settings.correlation_time_window_seconds)

    result = await session.execute(
        select(Incident).where(
            and_(
                Incident.service.in_(related_services),
                Incident.namespace == namespace,
                Incident.status.notin_(terminal_statuses),
                Incident.created_at >= cutoff,
            )
        ).order_by(Incident.created_at.desc()).limit(1)
    )
    return result.scalar_one_or_none()


async def _record_outbox(session: AsyncSession, topic: str, event: dict) -> None:
    outbox = OutboxEvent(
        id=new_event_id(),
        topic=topic,
        event_type=event.get("event_type", ""),
        payload=event,
    )
    session.add(outbox)


async def _mark_processed(session: AsyncSession, event_id: str) -> None:
    proc = ProcessedEvent(
        event_id=event_id,
        consumer_group=CONSUMER_GROUP,
    )
    session.add(proc)


async def _is_already_processed(event_id: str) -> bool:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(ProcessedEvent).where(
                and_(
                    ProcessedEvent.event_id == event_id,
                    ProcessedEvent.consumer_group == CONSUMER_GROUP,
                )
            )
        )
        return result.scalar_one_or_none() is not None


async def handle_raw_alert(event: dict) -> None:
    """
    Main handler for each alerts.raw event.
    Runs in a single DB transaction:
      1. Save alert
      2. Find or create incident
      3. Write outbox event
      4. Commit
    """
    event_id = event.get("event_id", "")
    correlation_id = event.get("correlation_id", new_event_id())

    normalized = _normalize_alert(event)

    # Ignore RESOLVED alerts for correlation — they don't create new incidents
    if normalized.status == AlertStatus.RESOLVED:
        logger.info("Skipping resolved alert", alert_name=normalized.alert_name)
        return

    async with AsyncSessionLocal() as session:
        async with session.begin():
            # ── Idempotency ─────────────────────────────────────────────────
            existing_proc = await session.execute(
                select(ProcessedEvent).where(
                    and_(
                        ProcessedEvent.event_id == event_id,
                        ProcessedEvent.consumer_group == CONSUMER_GROUP,
                    )
                )
            )
            if existing_proc.scalar_one_or_none():
                logger.info("Duplicate event, skipping", event_id=event_id)
                return

            # ── Deduplication check ─────────────────────────────────────────
            if await _is_duplicate_alert(session, normalized.fingerprint, 60):
                logger.info(
                    "Duplicate alert fingerprint, skipping",
                    fingerprint=normalized.fingerprint,
                    alert_name=normalized.alert_name,
                )
                await _mark_processed(session, event_id)
                return

            # ── Save alert record ───────────────────────────────────────────
            alert_record = Alert(
                id=normalized.alert_id,
                alert_name=normalized.alert_name,
                service=normalized.service,
                namespace=normalized.namespace,
                severity=normalized.severity.value,
                status=normalized.status.value,
                fingerprint=normalized.fingerprint,
                labels=normalized.labels,
                annotations={},
                raw_payload=event.get("payload", {}),
                starts_at=normalized.starts_at,
            )

            # ── Find or create incident ─────────────────────────────────────
            existing_incident = await _find_open_incident(session, normalized.service, normalized.namespace)

            if existing_incident:
                # Attach alert to existing incident
                alert_record.incident_id = existing_incident.id
                session.add(alert_record)

                # Update incident alert list
                alert_ids = list(existing_incident.alert_ids or [])
                alert_ids.append(normalized.alert_id)
                existing_incident.alert_ids = alert_ids

                # Escalate severity if needed
                if _severity_rank(normalized.severity.value) > _severity_rank(existing_incident.severity):
                    existing_incident.severity = _incident_severity(normalized.severity.value).value

                # Record timeline event
                session.add(IncidentEvent(
                    incident_id=existing_incident.id,
                    event_type="ALERT_CORRELATED",
                    description=f"Alert {normalized.alert_name} correlated into existing incident",
                    details={"alert_id": normalized.alert_id, "service": normalized.service},
                ))

                # Outbox: incident updated
                update_payload = IncidentUpdatedPayload(
                    incident_id=existing_incident.id,
                    previous_status=IncidentStatus(existing_incident.status),
                    new_status=IncidentStatus(existing_incident.status),
                    reason=f"Alert {normalized.alert_name} correlated",
                    updated_fields={"alert_ids": alert_ids},
                )
                update_event = make_incident_updated_event(update_payload, correlation_id)
                await _record_outbox(session, KafkaTopic.INCIDENTS_UPDATED.value, update_event.model_dump(mode="json"))

                logger.info(
                    "Alert correlated to existing incident",
                    incident_id=existing_incident.id,
                    alert_name=normalized.alert_name,
                )

            else:
                # Create new incident
                incident_id = new_event_id()
                incident_title = (
                    f"{normalized.service.capitalize()} — {normalized.alert_name}"
                )

                incident = Incident(
                    id=incident_id,
                    title=incident_title,
                    service=normalized.service,
                    namespace=normalized.namespace,
                    severity=_incident_severity(normalized.severity.value).value,
                    status=IncidentStatus.DETECTED.value,
                    correlation_id=correlation_id,
                    labels=normalized.labels,
                    alert_ids=[normalized.alert_id],
                )
                session.add(incident)

                alert_record.incident_id = incident_id
                session.add(alert_record)

                # Timeline event
                session.add(IncidentEvent(
                    incident_id=incident_id,
                    event_type="INCIDENT_CREATED",
                    description=f"Incident created from alert {normalized.alert_name}",
                    details={"alert_name": normalized.alert_name, "service": normalized.service},
                ))

                # Outbox: incident created (triggers investigation)
                created_payload = IncidentCreatedPayload(
                    incident_id=incident_id,
                    title=incident_title,
                    service=normalized.service,
                    namespace=normalized.namespace,
                    severity=_incident_severity(normalized.severity.value),
                    status=IncidentStatus.DETECTED,
                    alert_ids=[normalized.alert_id],
                    labels=normalized.labels,
                )
                created_event = make_incident_created_event(created_payload, correlation_id)
                await _record_outbox(session, KafkaTopic.INCIDENTS_CREATED.value, created_event.model_dump(mode="json"))

                logger.info(
                    "New incident created",
                    incident_id=incident_id,
                    service=normalized.service,
                    severity=_incident_severity(normalized.severity.value).value,
                    alert_name=normalized.alert_name,
                )

            # Mark event as processed (idempotency)
            await _mark_processed(session, event_id)

            # Commit everything atomically
            # (outbox event + alert + incident in one transaction)


async def main() -> None:
    await ensure_topics_exist()
    logger.info("Correlator worker starting")

    consumer = AegisConsumer(
        topics=[KafkaTopic.ALERTS_RAW.value],
        group_id=CONSUMER_GROUP,
        handler=handle_raw_alert,
        idempotency_checker=_is_already_processed,
    )

    await consumer.start()
    try:
        await consumer.run()
    finally:
        await consumer.stop()


if __name__ == "__main__":
    asyncio.run(main())
