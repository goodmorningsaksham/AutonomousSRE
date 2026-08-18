"""
Aegis API — Main REST API Service

Provides:
  - Incident management endpoints
  - Approval endpoints (POST approve/reject triggers Temporal signal)
  - Investigation/RCA query endpoints
  - System health and metrics
"""
from __future__ import annotations

import contextlib
from datetime import datetime, timezone
from typing import Any, Optional

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import Counter, Histogram, make_asgi_app
from pydantic import BaseModel
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from common.config.settings import get_settings
from common.events.schemas import IncidentStatus, new_event_id
from common.kafka.admin import ensure_topics_exist
from common.logging.logger import get_logger
from database.models.models import (
    Approval,
    Incident,
    IncidentEvent,
    Investigation,
    RemediationPlan,
)
from database.session import get_db

logger = get_logger(__name__)
settings = get_settings()

# ── Prometheus Metrics ────────────────────────────────────────────────────────
INCIDENTS_CREATED = Counter("aegis_incidents_created_total", "Total incidents created")
INCIDENTS_RESOLVED = Counter("aegis_incidents_resolved_total", "Total incidents resolved")
API_LATENCY = Histogram("aegis_api_request_duration_seconds", "API request latency", ["endpoint"])


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    await ensure_topics_exist()
    logger.info("Aegis API started", port=settings.aegis_api_port)
    yield
    logger.info("Aegis API stopped")


app = FastAPI(
    title="Aegis API",
    description="Autonomous SRE Incident Response Platform API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)


# ── Schemas ───────────────────────────────────────────────────────────────────
class IncidentResponse(BaseModel):
    id: str
    title: str
    service: str
    namespace: str
    severity: str
    status: str
    root_cause: Optional[str]
    confidence: Optional[float]
    correlation_id: str
    alert_ids: list[str]
    labels: dict
    created_at: datetime
    updated_at: datetime
    resolved_at: Optional[datetime]

    class Config:
        from_attributes = True


class IncidentDetailResponse(BaseModel):
    incident: IncidentResponse
    timeline: list[dict]
    investigations: list[dict]
    remediation_plans: list[dict]


class ApprovalDecision(BaseModel):
    decision: str  # "approved" | "rejected"
    approved_by: str
    notes: str = ""


# ── Health ────────────────────────────────────────────────────────────────────
@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "aegis-api", "timestamp": datetime.now(tz=timezone.utc).isoformat()}


# ── Incidents ─────────────────────────────────────────────────────────────────
@app.get("/api/v1/incidents", response_model=list[IncidentResponse])
async def list_incidents(
    status: Optional[str] = None,
    service: Optional[str] = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
) -> list[IncidentResponse]:
    query = select(Incident).order_by(desc(Incident.created_at)).limit(min(limit, 200))

    if status:
        query = query.where(Incident.status == status.upper())
    if service:
        query = query.where(Incident.service == service)

    result = await db.execute(query)
    incidents = result.scalars().all()
    return [IncidentResponse.model_validate(i) for i in incidents]


@app.get("/api/v1/incidents/{incident_id}", response_model=IncidentDetailResponse)
async def get_incident(incident_id: str, db: AsyncSession = Depends(get_db)) -> IncidentDetailResponse:
    result = await db.execute(select(Incident).where(Incident.id == incident_id))
    incident = result.scalar_one_or_none()
    if not incident:
        raise HTTPException(status_code=404, detail=f"Incident {incident_id!r} not found")

    # Timeline
    timeline_result = await db.execute(
        select(IncidentEvent)
        .where(IncidentEvent.incident_id == incident_id)
        .order_by(IncidentEvent.created_at.asc())
    )
    timeline = [
        {
            "id": e.id,
            "event_type": e.event_type,
            "description": e.description,
            "details": e.details,
            "created_at": e.created_at.isoformat(),
        }
        for e in timeline_result.scalars().all()
    ]

    # Investigations
    inv_result = await db.execute(
        select(Investigation).where(Investigation.incident_id == incident_id)
    )
    investigations = [
        {
            "id": inv.id,
            "status": inv.status,
            "root_cause": inv.root_cause,
            "confidence": inv.confidence,
            "suspected_component": inv.suspected_component,
            "reasoning_steps": inv.reasoning_steps,
            "recommended_actions": inv.recommended_actions,
            "llm_tokens_used": inv.llm_tokens_used,
            "duration_seconds": inv.duration_seconds,
            "started_at": inv.started_at.isoformat() if inv.started_at else None,
            "completed_at": inv.completed_at.isoformat() if inv.completed_at else None,
        }
        for inv in inv_result.scalars().all()
    ]

    # Remediation plans
    plans_result = await db.execute(
        select(RemediationPlan).where(RemediationPlan.incident_id == incident_id)
    )
    plans = [
        {
            "id": p.id,
            "action": p.action,
            "namespace": p.namespace,
            "target": p.target,
            "parameters": p.parameters,
            "reason": p.reason,
            "risk_level": p.risk_level,
            "requires_approval": p.requires_approval,
            "status": p.status,
            "policy_allowed": p.policy_allowed,
            "proposed_at": p.proposed_at.isoformat() if p.proposed_at else None,
        }
        for p in plans_result.scalars().all()
    ]

    return IncidentDetailResponse(
        incident=IncidentResponse.model_validate(incident),
        timeline=timeline,
        investigations=investigations,
        remediation_plans=plans,
    )


# ── Approvals ─────────────────────────────────────────────────────────────────
@app.get("/api/v1/approvals/pending")
async def list_pending_approvals(db: AsyncSession = Depends(get_db)) -> list[dict]:
    result = await db.execute(
        select(Approval, RemediationPlan)
        .join(RemediationPlan, Approval.plan_id == RemediationPlan.id)
        .where(Approval.status == "PENDING")
        .order_by(desc(Approval.requested_at))
        .limit(50)
    )
    rows = result.all()

    approvals = []
    for approval, plan in rows:
        approvals.append({
            "approval_id": approval.id,
            "plan_id": plan.id,
            "incident_id": approval.incident_id,
            "action": plan.action,
            "target": plan.target,
            "namespace": plan.namespace,
            "risk_level": plan.risk_level,
            "reason": plan.reason,
            "requested_at": approval.requested_at.isoformat(),
        })
    return approvals


@app.post("/api/v1/approvals/{approval_id}/approve", status_code=status.HTTP_200_OK)
async def approve_remediation(
    approval_id: str,
    decision: ApprovalDecision,
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(select(Approval).where(Approval.id == approval_id))
    approval = result.scalar_one_or_none()
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")
    if approval.status != "PENDING":
        raise HTTPException(status_code=409, detail=f"Approval already decided: {approval.status}")

    # Update approval record
    approval.status = "APPROVED" if decision.decision == "approved" else "REJECTED"
    approval.approved_by = decision.approved_by
    approval.notes = decision.notes
    approval.decided_at = datetime.now(tz=timezone.utc)
    await db.commit()

    # Send Temporal signal
    try:
        from workflows.incident_workflow import send_approval_signal
        await send_approval_signal(
            incident_id=approval.incident_id,
            decision=decision.decision,
            approved_by=decision.approved_by,
            notes=decision.notes,
        )
        logger.info("Approval signal sent", approval_id=approval_id, decision=decision.decision)
    except Exception as exc:
        logger.warning("Could not send Temporal signal (Temporal may be unavailable)", error=str(exc))

    return {
        "approval_id": approval_id,
        "status": approval.status,
        "incident_id": approval.incident_id,
    }


# ── Stats ─────────────────────────────────────────────────────────────────────
@app.get("/api/v1/stats")
async def get_stats(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    from sqlalchemy import func

    result = await db.execute(
        select(Incident.status, func.count(Incident.id).label("count"))
        .group_by(Incident.status)
    )
    by_status = {row.status: row.count for row in result.all()}

    return {
        "incidents_by_status": by_status,
        "total": sum(by_status.values()),
    }


if __name__ == "__main__":
    uvicorn.run(
        "services.api.main:app",
        host="0.0.0.0",
        port=settings.aegis_api_port,
        reload=settings.aegis_env == "development",
    )
