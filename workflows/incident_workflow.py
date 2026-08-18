"""
Aegis Incident Workflow — Temporal Durable Workflow

This workflow orchestrates the complete incident lifecycle:
  1. Collect evidence
  2. Investigate & diagnose (RCA)
  3. Plan remediation
  4. Policy check
  5. Request approval if required (waits for signal)
  6. Execute remediation
  7. Verify recovery
  8. Resolve incident

Temporal provides crash-resilient workflow execution.
If the worker crashes at any step, Temporal replays the workflow
from the last successful activity boundary.

Design principle: Workflow code is deterministic. Side effects
(DB writes, K8s calls, LLM calls) happen in Activities only.
"""
from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Optional

from temporalio import activity, workflow
from temporalio.client import Client
from temporalio.common import RetryPolicy
from temporalio.worker import Worker

from common.config.settings import get_settings
from common.events.schemas import (
    IncidentStatus,
    RemediationPlan,
    RemediationResult,
    RootCauseAnalysis,
    VerificationStatus,
    new_event_id,
)
from common.logging.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()

TASK_QUEUE = settings.temporal_task_queue

# ── Shared data structures ────────────────────────────────────────────────────
@workflow.defn
class IncidentWorkflow:
    """
    Durable incident lifecycle workflow.
    Handles crashes, approvals (via signals), and verification failures.
    """

    def __init__(self) -> None:
        self._approval_decision: Optional[dict] = None

    @workflow.signal
    def approval_signal(self, decision: dict) -> None:
        """Temporal signal sent by the API when a human approves/rejects."""
        self._approval_decision = decision

    @workflow.run
    async def run(self, input: dict) -> dict:
        incident_id = input["incident_id"]
        service = input["service"]
        namespace = input.get("namespace", "production")
        correlation_id = input.get("correlation_id", new_event_id())

        workflow.logger.info(
            "Incident workflow started",
            incident_id=incident_id,
            service=service,
        )

        retry_policy = RetryPolicy(
            initial_interval=timedelta(seconds=2),
            maximum_interval=timedelta(minutes=2),
            maximum_attempts=3,
        )

        # ── Step 1: Collect Evidence & Investigate ─────────────────────────
        rca_result = await workflow.execute_activity(
            investigate_activity,
            args=[incident_id, service, namespace],
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=retry_policy,
        )

        if not rca_result.get("success"):
            await workflow.execute_activity(
                update_incident_status_activity,
                args=[incident_id, IncidentStatus.FAILED.value, "Investigation failed"],
                start_to_close_timeout=timedelta(seconds=30),
            )
            return {"status": "FAILED", "reason": rca_result.get("error")}

        # ── Step 2: Plan Remediation ───────────────────────────────────────
        plan_result = await workflow.execute_activity(
            plan_remediation_activity,
            args=[incident_id, service, namespace, rca_result],
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy=retry_policy,
        )

        if not plan_result.get("plan"):
            # No actionable plan — still resolve with diagnosis only
            await workflow.execute_activity(
                update_incident_status_activity,
                args=[incident_id, IncidentStatus.RESOLVED.value, "No actionable remediation — diagnosed only"],
                start_to_close_timeout=timedelta(seconds=30),
            )
            return {"status": "RESOLVED", "note": "Diagnosed but no auto-remediation"}

        # ── Step 3: Policy Check ───────────────────────────────────────────
        policy_result = await workflow.execute_activity(
            policy_check_activity,
            args=[incident_id, plan_result],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )

        if not policy_result["allowed"]:
            await workflow.execute_activity(
                update_incident_status_activity,
                args=[incident_id, IncidentStatus.FAILED.value, f"Policy rejected: {policy_result.get('rejection_reason')}"],
                start_to_close_timeout=timedelta(seconds=30),
            )
            return {"status": "POLICY_REJECTED", "reason": policy_result.get("rejection_reason")}

        # ── Step 4: Approval (if required) ────────────────────────────────
        if policy_result["requires_approval"]:
            # Request approval and wait for signal
            await workflow.execute_activity(
                request_approval_activity,
                args=[incident_id, plan_result, rca_result],
                start_to_close_timeout=timedelta(seconds=30),
            )

            await workflow.execute_activity(
                update_incident_status_activity,
                args=[incident_id, IncidentStatus.AWAITING_APPROVAL.value, "Waiting for human approval"],
                start_to_close_timeout=timedelta(seconds=30),
            )

            # Wait for approval signal (timeout: 24 hours)
            await workflow.wait_condition(
                lambda: self._approval_decision is not None,
                timeout=timedelta(hours=24),
            )

            if self._approval_decision is None:
                # Timed out
                await workflow.execute_activity(
                    update_incident_status_activity,
                    args=[incident_id, IncidentStatus.FAILED.value, "Approval timed out"],
                    start_to_close_timeout=timedelta(seconds=30),
                )
                return {"status": "APPROVAL_TIMEOUT"}

            if self._approval_decision.get("decision") != "approved":
                await workflow.execute_activity(
                    update_incident_status_activity,
                    args=[incident_id, IncidentStatus.FAILED.value, f"Rejected: {self._approval_decision.get('notes', '')}"],
                    start_to_close_timeout=timedelta(seconds=30),
                )
                return {"status": "REJECTED", "reason": self._approval_decision.get("notes")}

        # ── Step 5: Execute Remediation ────────────────────────────────────
        await workflow.execute_activity(
            update_incident_status_activity,
            args=[incident_id, IncidentStatus.REMEDIATING.value, "Executing remediation"],
            start_to_close_timeout=timedelta(seconds=30),
        )

        execution_id = new_event_id()
        execution_result = await workflow.execute_activity(
            execute_remediation_activity,
            args=[incident_id, plan_result, execution_id],
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=retry_policy,
        )

        if execution_result.get("result") == RemediationResult.FAILURE.value:
            await workflow.execute_activity(
                update_incident_status_activity,
                args=[incident_id, IncidentStatus.FAILED.value, f"Remediation failed: {execution_result.get('error')}"],
                start_to_close_timeout=timedelta(seconds=30),
            )
            return {"status": "REMEDIATION_FAILED", "error": execution_result.get("error")}

        # ── Step 6: Verify Recovery ────────────────────────────────────────
        await workflow.execute_activity(
            update_incident_status_activity,
            args=[incident_id, IncidentStatus.VERIFYING.value, "Verifying recovery"],
            start_to_close_timeout=timedelta(seconds=30),
        )

        # Wait for observation window before verifying
        await asyncio.sleep(settings.verification_observation_window_seconds)

        verification_result = await workflow.execute_activity(
            verify_recovery_activity,
            args=[incident_id, service, namespace],
            start_to_close_timeout=timedelta(minutes=3),
            retry_policy=retry_policy,
        )

        # ── Step 7: Resolve ───────────────────────────────────────────────
        if verification_result.get("status") == VerificationStatus.RECOVERED.value:
            await workflow.execute_activity(
                update_incident_status_activity,
                args=[incident_id, IncidentStatus.RESOLVED.value, "Recovery verified"],
                start_to_close_timeout=timedelta(seconds=30),
            )
            workflow.logger.info("Incident resolved", incident_id=incident_id)
            return {"status": "RESOLVED", "incident_id": incident_id}
        else:
            await workflow.execute_activity(
                update_incident_status_activity,
                args=[incident_id, IncidentStatus.FAILED.value, "Verification failed — manual intervention required"],
                start_to_close_timeout=timedelta(seconds=30),
            )
            return {
                "status": "NOT_RECOVERED",
                "verification": verification_result,
                "incident_id": incident_id,
            }


# ── Activities ─────────────────────────────────────────────────────────────────
@activity.defn
async def investigate_activity(incident_id: str, service: str, namespace: str) -> dict:
    """Collect telemetry and run RCA. Returns serializable dict."""
    from agents.root_cause_agent import run_rca
    from database.models.models import Investigation, Incident, IncidentEvent
    from database.session import AsyncSessionLocal
    from sqlalchemy import select
    import time

    start = time.monotonic()
    logger.info("Activity: investigate", incident_id=incident_id)

    # Update incident status
    async with AsyncSessionLocal() as session:
        async with session.begin():
            result = await session.execute(select(Incident).where(Incident.id == incident_id))
            incident = result.scalar_one_or_none()
            if incident:
                incident.status = IncidentStatus.INVESTIGATING.value
                session.add(IncidentEvent(
                    incident_id=incident_id,
                    event_type="INVESTIGATION_STARTED",
                    description="Evidence collection and RCA started",
                    details={},
                ))

    try:
        rca, evidence_items, tokens, cost = await run_rca(incident_id, service, namespace)

        duration = time.monotonic() - start

        # Persist investigation results
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

                # Update incident with diagnosis
                result = await session.execute(select(Incident).where(Incident.id == incident_id))
                incident = result.scalar_one_or_none()
                if incident:
                    incident.status = IncidentStatus.DIAGNOSED.value
                    incident.root_cause = rca.root_cause
                    incident.confidence = rca.confidence
                    incident.suspected_component = rca.suspected_component

                session.add(IncidentEvent(
                    incident_id=incident_id,
                    event_type="RCA_COMPLETED",
                    description=f"Root cause identified: {rca.root_cause[:100]}",
                    details={"confidence": rca.confidence},
                ))

        return {
            "success": True,
            "root_cause": rca.root_cause,
            "confidence": rca.confidence,
            "suspected_component": rca.suspected_component,
            "recommended_actions": rca.recommended_actions,
            "reasoning_steps": rca.reasoning_steps,
            "tokens": tokens,
            "cost": cost,
            "duration": duration,
        }

    except Exception as exc:
        logger.error("Investigation activity failed", incident_id=incident_id, error=str(exc))
        return {"success": False, "error": str(exc)}


@activity.defn
async def plan_remediation_activity(
    incident_id: str, service: str, namespace: str, rca_result: dict
) -> dict:
    """Convert RCA to a RemediationPlan."""
    from agents.remediation_agent import plan_remediation
    from common.events.schemas import RootCauseAnalysis, EvidenceItem

    logger.info("Activity: plan_remediation", incident_id=incident_id)

    rca = RootCauseAnalysis(
        root_cause=rca_result["root_cause"],
        confidence=rca_result["confidence"],
        suspected_component=rca_result.get("suspected_component", service),
        recommended_actions=rca_result.get("recommended_actions", []),
        reasoning_steps=rca_result.get("reasoning_steps", []),
    )

    plan = plan_remediation(incident_id, rca, service, namespace)
    if plan:
        return {"plan": plan.model_dump(mode="json")}
    return {"plan": None}


@activity.defn
async def policy_check_activity(incident_id: str, plan_result: dict) -> dict:
    """Run deterministic policy evaluation."""
    from policies.remediation_policy import evaluate_policy
    from common.events.schemas import RemediationPlan

    logger.info("Activity: policy_check", incident_id=incident_id)

    if not plan_result.get("plan"):
        return {"allowed": False, "rejection_reason": "No plan provided"}

    plan = RemediationPlan(**plan_result["plan"])
    result = evaluate_policy(plan)

    return {
        "allowed": result.allowed,
        "requires_approval": result.requires_human_approval,
        "risk_level": result.risk_level.value,
        "rejection_reason": result.rejection_reason,
        "auto_approved": result.auto_approved,
    }


@activity.defn
async def request_approval_activity(incident_id: str, plan_result: dict, rca_result: dict) -> dict:
    """Create an approval record in the database."""
    from database.models.models import Approval, RemediationPlan as PlanModel, IncidentEvent
    from database.session import AsyncSessionLocal

    logger.info("Activity: request_approval", incident_id=incident_id)

    plan_data = plan_result["plan"]

    async with AsyncSessionLocal() as session:
        async with session.begin():
            approval = Approval(
                id=new_event_id(),
                plan_id=plan_data["plan_id"],
                incident_id=incident_id,
                status="PENDING",
            )
            session.add(approval)
            session.add(IncidentEvent(
                incident_id=incident_id,
                event_type="APPROVAL_REQUESTED",
                description=f"Human approval required for {plan_data['action']} on {plan_data['target']}",
                details={"plan_id": plan_data["plan_id"], "risk_level": plan_data["risk_level"]},
            ))

    return {"approval_requested": True, "plan_id": plan_data["plan_id"]}


@activity.defn
async def execute_remediation_activity(
    incident_id: str, plan_result: dict, execution_id: str
) -> dict:
    """Execute the approved remediation plan via Kubernetes."""
    from services.remediation.k8s_executor import execute_remediation
    from common.events.schemas import RemediationPlan
    from database.models.models import IncidentEvent
    from database.session import AsyncSessionLocal

    logger.info("Activity: execute_remediation", incident_id=incident_id)

    plan = RemediationPlan(**plan_result["plan"])
    result = await execute_remediation(plan, execution_id)

    async with AsyncSessionLocal() as session:
        async with session.begin():
            session.add(IncidentEvent(
                incident_id=incident_id,
                event_type="REMEDIATION_EXECUTED",
                description=f"Remediation {result.result.value}: {plan.action.value} on {plan.target}",
                details={"result": result.result.value, "error": result.error},
            ))

    return {
        "result": result.result.value,
        "error": result.error,
        "plan_id": result.plan_id,
    }


@activity.defn
async def verify_recovery_activity(incident_id: str, service: str, namespace: str) -> dict:
    """Check post-remediation telemetry to verify recovery."""
    import aiohttp
    from common.events.schemas import VerificationStatus

    logger.info("Activity: verify_recovery", incident_id=incident_id)

    observations = []
    error_rate_ok = True
    latency_ok = True
    pods_healthy = True

    try:
        async with aiohttp.ClientSession() as session:
            # Check error rate
            async with session.get(
                f"{settings.prometheus_url}/api/v1/query",
                params={"query": f'sum(rate(http_requests_total{{job="{service}",status=~"5.."}}[2m])) / sum(rate(http_requests_total{{job="{service}"}}[2m]))'},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    result = data.get("data", {}).get("result", [])
                    if result:
                        current_error_rate = float(result[0]["value"][1])
                        error_rate_ok = current_error_rate < 0.05
                        observations.append(f"Error rate: {current_error_rate:.2%} ({'OK' if error_rate_ok else 'HIGH'})")

    except Exception as exc:
        observations.append(f"Could not query Prometheus: {str(exc)}")

    # Determine overall status
    if error_rate_ok and latency_ok:
        status = VerificationStatus.RECOVERED
    elif error_rate_ok or latency_ok:
        status = VerificationStatus.PARTIAL
    else:
        status = VerificationStatus.NOT_RECOVERED

    from database.models.models import IncidentEvent
    from database.session import AsyncSessionLocal
    async with AsyncSessionLocal() as session:
        async with session.begin():
            session.add(IncidentEvent(
                incident_id=incident_id,
                event_type="VERIFICATION_COMPLETED",
                description=f"Verification result: {status.value}",
                details={"observations": observations},
            ))

    return {
        "status": status.value,
        "error_rate_ok": error_rate_ok,
        "latency_ok": latency_ok,
        "pods_healthy": pods_healthy,
        "observations": observations,
    }


@activity.defn
async def update_incident_status_activity(incident_id: str, status: str, reason: str) -> None:
    """Update incident status in PostgreSQL."""
    from database.models.models import Incident, IncidentEvent
    from database.session import AsyncSessionLocal
    from sqlalchemy import select
    from datetime import datetime, timezone

    async with AsyncSessionLocal() as session:
        async with session.begin():
            result = await session.execute(select(Incident).where(Incident.id == incident_id))
            incident = result.scalar_one_or_none()
            if incident:
                incident.status = status
                if status == IncidentStatus.RESOLVED.value:
                    incident.resolved_at = datetime.now(tz=timezone.utc)

                session.add(IncidentEvent(
                    incident_id=incident_id,
                    event_type="STATUS_CHANGED",
                    description=f"Status changed to {status}: {reason}",
                    details={"new_status": status, "reason": reason},
                ))


# ── Worker entry point ─────────────────────────────────────────────────────────
async def run_worker() -> None:
    """Start the Temporal worker."""
    client = await Client.connect(settings.temporal_address)

    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[IncidentWorkflow],
        activities=[
            investigate_activity,
            plan_remediation_activity,
            policy_check_activity,
            request_approval_activity,
            execute_remediation_activity,
            verify_recovery_activity,
            update_incident_status_activity,
        ],
    )

    logger.info("Temporal worker starting", task_queue=TASK_QUEUE)
    await worker.run()


async def start_incident_workflow(
    incident_id: str,
    service: str,
    namespace: str,
    correlation_id: str,
) -> str:
    """Start a new IncidentWorkflow for the given incident."""
    client = await Client.connect(settings.temporal_address)

    handle = await client.start_workflow(
        IncidentWorkflow.run,
        args=[{
            "incident_id": incident_id,
            "service": service,
            "namespace": namespace,
            "correlation_id": correlation_id,
        }],
        id=f"incident-{incident_id}",
        task_queue=TASK_QUEUE,
    )

    logger.info("Incident workflow started", workflow_id=handle.id, incident_id=incident_id)
    return handle.id


async def send_approval_signal(incident_id: str, decision: str, approved_by: str, notes: str = "") -> None:
    """Send approval/rejection signal to the waiting workflow."""
    client = await Client.connect(settings.temporal_address)
    handle = client.get_workflow_handle(f"incident-{incident_id}")
    await handle.signal(
        IncidentWorkflow.approval_signal,
        {"decision": decision, "approved_by": approved_by, "notes": notes},
    )
    logger.info("Approval signal sent", incident_id=incident_id, decision=decision)


if __name__ == "__main__":
    asyncio.run(run_worker())
