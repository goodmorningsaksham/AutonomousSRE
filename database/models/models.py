"""
SQLAlchemy ORM models for Aegis.

All IDs are UUIDs stored as strings for portability.
Timestamps are always UTC.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from pgvector.sqlalchemy import Vector

from database.session import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


# ──────────────────────────────────────────────────────────────────────────────
# Incidents
# ──────────────────────────────────────────────────────────────────────────────
class Incident(Base):
    __tablename__ = "incidents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    service: Mapped[str] = mapped_column(String(100), nullable=False)
    namespace: Mapped[str] = mapped_column(String(100), nullable=False, default="default")
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="DETECTED")
    root_cause: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    suspected_component: Mapped[str | None] = mapped_column(String(200), nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    labels: Mapped[dict] = mapped_column(JSON, default=dict)
    alert_ids: Mapped[list] = mapped_column(JSON, default=list)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # relationships
    events: Mapped[list["IncidentEvent"]] = relationship("IncidentEvent", back_populates="incident", cascade="all, delete-orphan")
    alerts: Mapped[list["Alert"]] = relationship("Alert", back_populates="incident")
    investigations: Mapped[list["Investigation"]] = relationship("Investigation", back_populates="incident")
    remediation_plans: Mapped[list["RemediationPlan"]] = relationship("RemediationPlan", back_populates="incident")

    __table_args__ = (
        Index("ix_incidents_status", "status"),
        Index("ix_incidents_service", "service"),
    )


class IncidentEvent(Base):
    """Immutable timeline events for an incident."""
    __tablename__ = "incident_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    incident_id: Mapped[str] = mapped_column(String(36), ForeignKey("incidents.id"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    incident: Mapped["Incident"] = relationship("Incident", back_populates="events")


# ──────────────────────────────────────────────────────────────────────────────
# Alerts
# ──────────────────────────────────────────────────────────────────────────────
class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    incident_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("incidents.id"), nullable=True, index=True)
    alert_name: Mapped[str] = mapped_column(String(200), nullable=False)
    service: Mapped[str] = mapped_column(String(100), nullable=False)
    namespace: Mapped[str] = mapped_column(String(100), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="firing")
    fingerprint: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    labels: Mapped[dict] = mapped_column(JSON, default=dict)
    annotations: Mapped[dict] = mapped_column(JSON, default=dict)
    raw_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    incident: Mapped["Incident | None"] = relationship("Incident", back_populates="alerts")


# ──────────────────────────────────────────────────────────────────────────────
# Investigation & Evidence
# ──────────────────────────────────────────────────────────────────────────────
class Investigation(Base):
    __tablename__ = "investigations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    incident_id: Mapped[str] = mapped_column(String(36), ForeignKey("incidents.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="RUNNING")
    root_cause: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    suspected_component: Mapped[str | None] = mapped_column(String(200), nullable=True)
    reasoning_steps: Mapped[list] = mapped_column(JSON, default=list)
    recommended_actions: Mapped[list] = mapped_column(JSON, default=list)
    llm_tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    llm_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    incident: Mapped["Incident"] = relationship("Incident", back_populates="investigations")
    evidence: Mapped[list["Evidence"]] = relationship("Evidence", back_populates="investigation", cascade="all, delete-orphan")


class Evidence(Base):
    __tablename__ = "evidence"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    investigation_id: Mapped[str] = mapped_column(String(36), ForeignKey("investigations.id"), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False)  # prometheus|loki|tempo|kubernetes|runbook
    observation: Mapped[str] = mapped_column(Text, nullable=False)
    raw_data: Mapped[dict] = mapped_column(JSON, default=dict)
    confidence_contribution: Mapped[float] = mapped_column(Float, default=0.0)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    investigation: Mapped["Investigation"] = relationship("Investigation", back_populates="evidence")


# ──────────────────────────────────────────────────────────────────────────────
# Remediation
# ──────────────────────────────────────────────────────────────────────────────
class RemediationPlan(Base):
    __tablename__ = "remediation_plans"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    incident_id: Mapped[str] = mapped_column(String(36), ForeignKey("incidents.id"), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    namespace: Mapped[str] = mapped_column(String(100), nullable=False)
    target: Mapped[str] = mapped_column(String(200), nullable=False)
    parameters: Mapped[dict] = mapped_column(JSON, default=dict)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(20), nullable=False)
    requires_approval: Mapped[bool] = mapped_column(Boolean, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="PROPOSED")
    policy_allowed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    policy_rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    proposed_by: Mapped[str] = mapped_column(String(100), nullable=False, default="remediation_agent")
    proposed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    incident: Mapped["Incident"] = relationship("Incident", back_populates="remediation_plans")
    approval: Mapped["Approval | None"] = relationship("Approval", back_populates="plan", uselist=False)
    execution: Mapped["RemediationExecution | None"] = relationship("RemediationExecution", back_populates="plan", uselist=False)


class Approval(Base):
    __tablename__ = "approvals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    plan_id: Mapped[str] = mapped_column(String(36), ForeignKey("remediation_plans.id"), nullable=False, unique=True, index=True)
    incident_id: Mapped[str] = mapped_column(String(36), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")  # PENDING|APPROVED|REJECTED
    approved_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    plan: Mapped["RemediationPlan"] = relationship("RemediationPlan", back_populates="approval")


class RemediationExecution(Base):
    __tablename__ = "remediation_executions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    plan_id: Mapped[str] = mapped_column(String(36), ForeignKey("remediation_plans.id"), nullable=False, unique=True, index=True)
    incident_id: Mapped[str] = mapped_column(String(36), nullable=False)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    target: Mapped[str] = mapped_column(String(200), nullable=False)
    namespace: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="PENDING")  # PENDING|EXECUTING|SUCCESS|FAILURE|SKIPPED
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_idempotent_skip: Mapped[bool] = mapped_column(Boolean, default=False)

    plan: Mapped["RemediationPlan"] = relationship("RemediationPlan", back_populates="execution")


# ──────────────────────────────────────────────────────────────────────────────
# Transactional Outbox
# ──────────────────────────────────────────────────────────────────────────────
class OutboxEvent(Base):
    """
    Transactional outbox: events are written here inside the same DB transaction
    as the business operation, then a background poller publishes them to Kafka.
    """
    __tablename__ = "outbox_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    topic: Mapped[str] = mapped_column(String(100), nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    published: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_outbox_unpublished", "published", "created_at"),
    )


# ──────────────────────────────────────────────────────────────────────────────
# Idempotency Log
# ──────────────────────────────────────────────────────────────────────────────
class ProcessedEvent(Base):
    """Tracks processed Kafka event IDs to ensure idempotent consumers."""
    __tablename__ = "processed_events"

    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    consumer_group: Mapped[str] = mapped_column(String(100), nullable=False)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("event_id", "consumer_group", name="uq_processed_event_per_group"),
    )


# ──────────────────────────────────────────────────────────────────────────────
# Audit Log
# ──────────────────────────────────────────────────────────────────────────────
class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    incident_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    actor: Mapped[str] = mapped_column(String(200), nullable=False)
    action: Mapped[str] = mapped_column(String(200), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(200), nullable=False)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    outcome: Mapped[str] = mapped_column(String(50), nullable=False, default="success")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


# ──────────────────────────────────────────────────────────────────────────────
# RAG — Runbooks & Historical Incidents (pgvector)
# ──────────────────────────────────────────────────────────────────────────────
class Runbook(Base):
    __tablename__ = "runbooks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    service: Mapped[str] = mapped_column(String(100), nullable=False)
    failure_type: Mapped[str] = mapped_column(String(100), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    embedding = mapped_column(Vector(1536), nullable=True)  # OpenAI text-embedding-3-small
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class HistoricalIncident(Base):
    __tablename__ = "historical_incidents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    original_incident_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    service: Mapped[str] = mapped_column(String(100), nullable=False)
    root_cause: Mapped[str] = mapped_column(Text, nullable=False)
    resolution: Mapped[str] = mapped_column(Text, nullable=False)
    duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    embedding = mapped_column(Vector(1536), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


# ──────────────────────────────────────────────────────────────────────────────
# Benchmark
# ──────────────────────────────────────────────────────────────────────────────
class FailureScenario(Base):
    __tablename__ = "failure_scenarios"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    scenario_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    failure_type: Mapped[str] = mapped_column(String(100), nullable=False)
    target_service: Mapped[str] = mapped_column(String(100), nullable=False)
    expected_root_cause: Mapped[str] = mapped_column(Text, nullable=False)
    acceptable_remediations: Mapped[list] = mapped_column(JSON, default=list)
    scenario_metadata: Mapped[dict] = mapped_column(JSON, default=dict)


class BenchmarkResult(Base):
    __tablename__ = "benchmark_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    scenario_id: Mapped[str] = mapped_column(String(100), nullable=False)
    incident_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    failure_type: Mapped[str] = mapped_column(String(100), nullable=False)
    mttd_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    mttr_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    root_cause_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    remediation_success: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    policy_rejections: Mapped[int] = mapped_column(Integer, default=0)
    unsafe_actions: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_side_effects: Mapped[int] = mapped_column(Integer, default=0)
    workflow_recovered: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    llm_tokens: Mapped[int] = mapped_column(Integer, default=0)
    llm_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
