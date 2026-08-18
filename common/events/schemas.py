"""
Common Kafka event schemas for Aegis.

Every event MUST include: event_id, event_type, timestamp, correlation_id,
producer, schema_version, and a typed payload.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Generic, Optional, TypeVar

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


def new_event_id() -> str:
    return str(uuid.uuid4())


# ──────────────────────────────────────────────────────────────────────────────
# Topic names
# ──────────────────────────────────────────────────────────────────────────────
class KafkaTopic(str, Enum):
    ALERTS_RAW = "alerts.raw"
    ALERTS_NORMALIZED = "alerts.normalized"
    INCIDENTS_CREATED = "incidents.created"
    INCIDENTS_UPDATED = "incidents.updated"
    INVESTIGATIONS_REQUESTED = "investigations.requested"
    INVESTIGATIONS_COMPLETED = "investigations.completed"
    REMEDIATIONS_REQUESTED = "remediations.requested"
    REMEDIATIONS_APPROVED = "remediations.approved"
    REMEDIATIONS_EXECUTED = "remediations.executed"
    VERIFICATION_REQUESTED = "verification.requested"
    VERIFICATION_COMPLETED = "verification.completed"
    AUDIT_EVENTS = "audit.events"


ALL_TOPICS = [t.value for t in KafkaTopic]


# ──────────────────────────────────────────────────────────────────────────────
# Base event envelope
# ──────────────────────────────────────────────────────────────────────────────
PayloadT = TypeVar("PayloadT", bound=BaseModel)


class AegisEvent(BaseModel, Generic[PayloadT]):
    event_id: str = Field(default_factory=new_event_id)
    event_type: str
    timestamp: datetime = Field(default_factory=utcnow)
    correlation_id: str = Field(default_factory=new_event_id)
    incident_id: Optional[str] = None
    producer: str = "aegis"
    schema_version: str = "1.0"
    payload: PayloadT


# ──────────────────────────────────────────────────────────────────────────────
# Alert payloads
# ──────────────────────────────────────────────────────────────────────────────
class AlertSeverity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    WARNING = "warning"
    INFO = "info"


class AlertStatus(str, Enum):
    FIRING = "firing"
    RESOLVED = "resolved"


class RawAlertPayload(BaseModel):
    """Alertmanager webhook payload — normalized wrapper."""
    alert_name: str
    service: str
    namespace: str
    severity: AlertSeverity
    status: AlertStatus
    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None
    generator_url: Optional[str] = None
    raw_payload: dict[str, Any] = Field(default_factory=dict)


class NormalizedAlertPayload(BaseModel):
    alert_id: str = Field(default_factory=new_event_id)
    alert_name: str
    service: str
    namespace: str
    severity: AlertSeverity
    status: AlertStatus
    labels: dict[str, str] = Field(default_factory=dict)
    summary: str = ""
    description: str = ""
    starts_at: Optional[datetime] = None
    fingerprint: str = ""  # deterministic hash for deduplication


# ──────────────────────────────────────────────────────────────────────────────
# Incident payloads
# ──────────────────────────────────────────────────────────────────────────────
class IncidentSeverity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class IncidentStatus(str, Enum):
    DETECTED = "DETECTED"
    CORRELATING = "CORRELATING"
    INVESTIGATING = "INVESTIGATING"
    DIAGNOSED = "DIAGNOSED"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    REMEDIATING = "REMEDIATING"
    VERIFYING = "VERIFYING"
    RESOLVED = "RESOLVED"
    FAILED = "FAILED"


class IncidentCreatedPayload(BaseModel):
    incident_id: str
    title: str
    service: str
    namespace: str
    severity: IncidentSeverity
    status: IncidentStatus
    alert_ids: list[str] = Field(default_factory=list)
    labels: dict[str, str] = Field(default_factory=dict)


class IncidentUpdatedPayload(BaseModel):
    incident_id: str
    previous_status: IncidentStatus
    new_status: IncidentStatus
    reason: str = ""
    updated_fields: dict[str, Any] = Field(default_factory=dict)


# ──────────────────────────────────────────────────────────────────────────────
# Investigation payloads
# ──────────────────────────────────────────────────────────────────────────────
class EvidenceItem(BaseModel):
    source: str  # prometheus | loki | tempo | kubernetes | runbook | history
    observation: str
    raw_data: Optional[dict[str, Any]] = None
    confidence_contribution: float = 0.0


class RootCauseAnalysis(BaseModel):
    root_cause: str
    confidence: float  # 0.0 – 1.0
    suspected_component: str
    reasoning_steps: list[str] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    recommended_actions: list[dict[str, Any]] = Field(default_factory=list)


class InvestigationRequestedPayload(BaseModel):
    incident_id: str
    service: str
    namespace: str


class InvestigationCompletedPayload(BaseModel):
    incident_id: str
    rca: RootCauseAnalysis
    evidence_count: int
    duration_seconds: float
    llm_tokens_used: int = 0
    llm_cost_usd: float = 0.0


# ──────────────────────────────────────────────────────────────────────────────
# Remediation payloads
# ──────────────────────────────────────────────────────────────────────────────
class RemediationAction(str, Enum):
    RESTART_POD = "RESTART_POD"
    SCALE_DEPLOYMENT = "SCALE_DEPLOYMENT"
    ROLLBACK_DEPLOYMENT = "ROLLBACK_DEPLOYMENT"
    CHANGE_CONFIG = "CHANGE_CONFIG"
    DELETE_RESOURCE = "DELETE_RESOURCE"
    DATABASE_MUTATION = "DATABASE_MUTATION"


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    FORBIDDEN = "FORBIDDEN"


class RemediationPlan(BaseModel):
    plan_id: str = Field(default_factory=new_event_id)
    incident_id: str
    action: RemediationAction
    namespace: str
    target: str  # deployment name / pod name
    parameters: dict[str, Any] = Field(default_factory=dict)
    reason: str
    risk_level: RiskLevel
    requires_approval: bool
    proposed_by: str = "remediation_agent"


class RemediationRequestedPayload(BaseModel):
    plan: RemediationPlan


class RemediationApprovedPayload(BaseModel):
    plan_id: str
    incident_id: str
    approved_by: str
    approved_at: datetime = Field(default_factory=utcnow)
    notes: str = ""


class RemediationResult(str, Enum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    SKIPPED_IDEMPOTENT = "SKIPPED_IDEMPOTENT"


class RemediationExecutedPayload(BaseModel):
    plan_id: str
    incident_id: str
    action: RemediationAction
    target: str
    namespace: str
    result: RemediationResult
    error: Optional[str] = None
    executed_at: datetime = Field(default_factory=utcnow)


# ──────────────────────────────────────────────────────────────────────────────
# Verification payloads
# ──────────────────────────────────────────────────────────────────────────────
class VerificationRequestedPayload(BaseModel):
    incident_id: str
    plan_id: str
    service: str
    namespace: str


class VerificationStatus(str, Enum):
    RECOVERED = "RECOVERED"
    NOT_RECOVERED = "NOT_RECOVERED"
    PARTIAL = "PARTIAL"


class VerificationCompletedPayload(BaseModel):
    incident_id: str
    plan_id: str
    status: VerificationStatus
    error_rate: Optional[float] = None
    p95_latency_ms: Optional[float] = None
    pods_healthy: Optional[bool] = None
    observations: list[str] = Field(default_factory=list)
    observation_window_seconds: int = 30


# ──────────────────────────────────────────────────────────────────────────────
# Audit payloads
# ──────────────────────────────────────────────────────────────────────────────
class AuditEventPayload(BaseModel):
    actor: str
    action: str
    resource_type: str
    resource_id: str
    details: dict[str, Any] = Field(default_factory=dict)
    outcome: str = "success"


# ──────────────────────────────────────────────────────────────────────────────
# Typed event factories
# ──────────────────────────────────────────────────────────────────────────────
def make_alert_raw_event(payload: RawAlertPayload, correlation_id: str | None = None) -> AegisEvent[RawAlertPayload]:
    return AegisEvent(
        event_type="ALERT_RAW_RECEIVED",
        correlation_id=correlation_id or new_event_id(),
        payload=payload,
    )


def make_alert_normalized_event(payload: NormalizedAlertPayload, correlation_id: str) -> AegisEvent[NormalizedAlertPayload]:
    return AegisEvent(
        event_type="ALERT_NORMALIZED",
        correlation_id=correlation_id,
        payload=payload,
    )


def make_incident_created_event(payload: IncidentCreatedPayload, correlation_id: str) -> AegisEvent[IncidentCreatedPayload]:
    return AegisEvent(
        event_type="INCIDENT_CREATED",
        correlation_id=correlation_id,
        incident_id=payload.incident_id,
        payload=payload,
    )


def make_incident_updated_event(payload: IncidentUpdatedPayload, correlation_id: str) -> AegisEvent[IncidentUpdatedPayload]:
    return AegisEvent(
        event_type="INCIDENT_UPDATED",
        correlation_id=correlation_id,
        incident_id=payload.incident_id,
        payload=payload,
    )


def make_investigation_completed_event(payload: InvestigationCompletedPayload, correlation_id: str) -> AegisEvent[InvestigationCompletedPayload]:
    return AegisEvent(
        event_type="INVESTIGATION_COMPLETED",
        correlation_id=correlation_id,
        incident_id=payload.incident_id,
        payload=payload,
    )


def make_remediation_requested_event(payload: RemediationRequestedPayload, correlation_id: str) -> AegisEvent[RemediationRequestedPayload]:
    return AegisEvent(
        event_type="REMEDIATION_REQUESTED",
        correlation_id=correlation_id,
        incident_id=payload.plan.incident_id,
        payload=payload,
    )


def make_remediation_approved_event(payload: RemediationApprovedPayload, correlation_id: str) -> AegisEvent[RemediationApprovedPayload]:
    return AegisEvent(
        event_type="REMEDIATION_APPROVED",
        correlation_id=correlation_id,
        incident_id=payload.incident_id,
        payload=payload,
    )


def make_remediation_executed_event(payload: RemediationExecutedPayload, correlation_id: str) -> AegisEvent[RemediationExecutedPayload]:
    return AegisEvent(
        event_type="REMEDIATION_EXECUTED",
        correlation_id=correlation_id,
        incident_id=payload.incident_id,
        payload=payload,
    )


def make_verification_requested_event(payload: VerificationRequestedPayload, correlation_id: str) -> AegisEvent[VerificationRequestedPayload]:
    return AegisEvent(
        event_type="VERIFICATION_REQUESTED",
        correlation_id=correlation_id,
        incident_id=payload.incident_id,
        payload=payload,
    )


def make_verification_completed_event(payload: VerificationCompletedPayload, correlation_id: str) -> AegisEvent[VerificationCompletedPayload]:
    return AegisEvent(
        event_type="VERIFICATION_COMPLETED",
        correlation_id=correlation_id,
        incident_id=payload.incident_id,
        payload=payload,
    )


def make_audit_event(payload: AuditEventPayload, incident_id: str | None = None) -> AegisEvent[AuditEventPayload]:
    return AegisEvent(
        event_type="AUDIT_EVENT",
        incident_id=incident_id,
        payload=payload,
    )
