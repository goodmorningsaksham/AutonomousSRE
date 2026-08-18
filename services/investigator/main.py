"""
Investigator Worker

Consumes incidents.created events and triggers the Temporal
IncidentWorkflow for each new incident. Uses idempotency to ensure
each incident only gets one workflow started, even with duplicate events.
"""
from __future__ import annotations

import asyncio

from sqlalchemy import select, and_

from common.config.settings import get_settings
from common.events.schemas import KafkaTopic, IncidentStatus, new_event_id
from common.kafka.admin import ensure_topics_exist
from common.kafka.consumer import AegisConsumer
from common.logging.logger import get_logger
from database.models.models import ProcessedEvent, Incident
from database.session import AsyncSessionLocal

logger = get_logger(__name__)
settings = get_settings()

CONSUMER_GROUP = settings.kafka_group_id_investigator


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


async def handle_incident_created(event: dict) -> None:
    """Start a Temporal workflow for each new incident."""
    event_id = event.get("event_id", "")
    payload = event.get("payload", {})
    incident_id = payload.get("incident_id", "")
    service = payload.get("service", "unknown")
    namespace = payload.get("namespace", "production")
    correlation_id = event.get("correlation_id", new_event_id())

    if not incident_id:
        logger.warning("Incident created event missing incident_id", event_id=event_id)
        return

    if event_id and await _is_processed(event_id):
        logger.info("Event already processed by investigator", event_id=event_id)
        return

    logger.info("Incident created — starting workflow", incident_id=incident_id, service=service)

    try:
        from workflows.incident_workflow import start_incident_workflow

        workflow_id = await start_incident_workflow(
            incident_id=incident_id,
            service=service,
            namespace=namespace,
            correlation_id=correlation_id,
        )
        logger.info("Temporal workflow started", workflow_id=workflow_id, incident_id=incident_id)
    except Exception as exc:
        # If Temporal is unavailable, run investigation directly
        logger.warning(
            "Temporal unavailable — running investigation synchronously",
            error=str(exc),
            incident_id=incident_id,
        )
        await _run_investigation_sync(incident_id, service, namespace)

    # Mark processed safely
    try:
        async with AsyncSessionLocal() as session:
            async with session.begin():
                session.add(ProcessedEvent(
                    event_id=event_id,
                    consumer_group=CONSUMER_GROUP,
                ))
    except Exception:
        pass


async def _run_investigation_sync(incident_id: str, service: str, namespace: str) -> None:
    """
    Fallback: run investigation without Temporal.
    Used when Temporal is unavailable (e.g. local dev without k8s).
    """
    from agents.root_cause_agent import run_rca
    from agents.remediation_agent import plan_remediation
    from policies.remediation_policy import evaluate_policy
    from services.remediation.k8s_executor import execute_remediation
    from database.models.models import Investigation, Incident, IncidentEvent, RemediationPlan as PlanModel, OutboxEvent
    from database.session import AsyncSessionLocal
    from sqlalchemy import select
    import time

    start = time.monotonic()
    logger.info("Running investigation synchronously", incident_id=incident_id)

    try:
        # Update status
        async with AsyncSessionLocal() as session:
            async with session.begin():
                result = await session.execute(select(Incident).where(Incident.id == incident_id))
                incident = result.scalar_one_or_none()
                if incident:
                    incident.status = IncidentStatus.INVESTIGATING.value

        # RCA
        rca, evidence_items, tokens, cost = await run_rca(incident_id, service, namespace)
        duration = time.monotonic() - start

        # Plan
        plan = plan_remediation(incident_id, rca, service, namespace)

        # Persist
        async with AsyncSessionLocal() as session:
            async with session.begin():
                inv = Investigation(
                    id=new_event_id(),
                    incident_id=incident_id,
                    status="COMPLETED",
                    root_cause=rca.root_cause,
                    confidence=rca.confidence,
                    suspected_component=rca.suspected_component,
                    reasoning_steps=rca.reasoning_steps,
                    recommended_actions=rca.recommended_actions,
                    llm_tokens_used=tokens,
                    llm_cost_usd=cost,
                    duration_seconds=duration,
                )
                session.add(inv)

                result = await session.execute(select(Incident).where(Incident.id == incident_id))
                incident = result.scalar_one_or_none()
                if incident:
                    incident.status = IncidentStatus.DIAGNOSED.value
                    incident.root_cause = rca.root_cause
                    incident.confidence = rca.confidence

                session.add(IncidentEvent(
                    incident_id=incident_id,
                    event_type="RCA_COMPLETED",
                    description=f"Root cause: {rca.root_cause[:100]}",
                    details={"confidence": rca.confidence},
                ))

                if plan:
                    # Evaluate policy
                    policy_result = evaluate_policy(plan)
                    if policy_result.allowed and not policy_result.requires_human_approval:
                        # Auto-execute
                        exec_id = new_event_id()
                        exec_result = await execute_remediation(plan, exec_id)
                        if incident:
                            incident.status = IncidentStatus.RESOLVED.value
                        session.add(IncidentEvent(
                            incident_id=incident_id,
                            event_type="AUTO_REMEDIATED",
                            description=f"Auto-remediation: {exec_result.result.value}",
                            details={"action": plan.action.value, "target": plan.target},
                        ))
                    elif policy_result.allowed and policy_result.requires_human_approval:
                        if incident:
                            incident.status = IncidentStatus.AWAITING_APPROVAL.value
                        session.add(IncidentEvent(
                            incident_id=incident_id,
                            event_type="AWAITING_APPROVAL",
                            description=f"Awaiting approval for {plan.action.value}",
                            details={"plan_id": plan.plan_id},
                        ))
                    else:
                        session.add(IncidentEvent(
                            incident_id=incident_id,
                            event_type="POLICY_REJECTED",
                            description=f"Policy rejected: {policy_result.rejection_reason}",
                            details={},
                        ))

    except Exception as exc:
        logger.error("Sync investigation failed", incident_id=incident_id, error=str(exc))
        async with AsyncSessionLocal() as session:
            async with session.begin():
                result = await session.execute(select(Incident).where(Incident.id == incident_id))
                incident = result.scalar_one_or_none()
                if incident:
                    incident.status = IncidentStatus.FAILED.value


async def main() -> None:
    await ensure_topics_exist()
    logger.info("Investigator worker starting")

    import uuid
    instance_group = f"{CONSUMER_GROUP}-{uuid.uuid4().hex[:8]}"

    consumer = AegisConsumer(
        topics=[KafkaTopic.INCIDENTS_CREATED.value],
        group_id=instance_group,
        handler=handle_incident_created,
        idempotency_checker=_is_already_processed,
    )

    await consumer.start()
    try:
        await consumer.run()
    finally:
        await consumer.stop()


if __name__ == "__main__":
    asyncio.run(main())
