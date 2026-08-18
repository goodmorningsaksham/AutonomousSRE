"""Initial schema — Aegis complete data model with pgvector.

Revision ID: 0001_initial
Revises:
Create Date: 2024-01-01 00:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enable pgvector extension
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\"")

    # incidents
    op.create_table(
        "incidents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("service", sa.String(100), nullable=False),
        sa.Column("namespace", sa.String(100), nullable=False, server_default="default"),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="DETECTED"),
        sa.Column("root_cause", sa.Text, nullable=True),
        sa.Column("confidence", sa.Float, nullable=True),
        sa.Column("suspected_component", sa.String(200), nullable=True),
        sa.Column("correlation_id", sa.String(36), nullable=False),
        sa.Column("labels", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("alert_ids", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_incidents_status", "incidents", ["status"])
    op.create_index("ix_incidents_service", "incidents", ["service"])
    op.create_index("ix_incidents_correlation_id", "incidents", ["correlation_id"])

    # incident_events
    op.create_table(
        "incident_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("incident_id", sa.String(36), sa.ForeignKey("incidents.id"), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("details", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_incident_events_incident_id", "incident_events", ["incident_id"])

    # alerts
    op.create_table(
        "alerts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("incident_id", sa.String(36), sa.ForeignKey("incidents.id"), nullable=True),
        sa.Column("alert_name", sa.String(200), nullable=False),
        sa.Column("service", sa.String(100), nullable=False),
        sa.Column("namespace", sa.String(100), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="firing"),
        sa.Column("fingerprint", sa.String(100), nullable=False),
        sa.Column("labels", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("annotations", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("raw_payload", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_alerts_incident_id", "alerts", ["incident_id"])
    op.create_index("ix_alerts_fingerprint", "alerts", ["fingerprint"])

    # investigations
    op.create_table(
        "investigations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("incident_id", sa.String(36), sa.ForeignKey("incidents.id"), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="RUNNING"),
        sa.Column("root_cause", sa.Text, nullable=True),
        sa.Column("confidence", sa.Float, nullable=True),
        sa.Column("suspected_component", sa.String(200), nullable=True),
        sa.Column("reasoning_steps", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("recommended_actions", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("llm_tokens_used", sa.Integer, nullable=False, server_default="0"),
        sa.Column("llm_cost_usd", sa.Float, nullable=False, server_default="0.0"),
        sa.Column("duration_seconds", sa.Float, nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_investigations_incident_id", "investigations", ["incident_id"])

    # evidence
    op.create_table(
        "evidence",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("investigation_id", sa.String(36), sa.ForeignKey("investigations.id"), nullable=False),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("observation", sa.Text, nullable=False),
        sa.Column("raw_data", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("confidence_contribution", sa.Float, nullable=False, server_default="0.0"),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_evidence_investigation_id", "evidence", ["investigation_id"])

    # remediation_plans
    op.create_table(
        "remediation_plans",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("incident_id", sa.String(36), sa.ForeignKey("incidents.id"), nullable=False),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("namespace", sa.String(100), nullable=False),
        sa.Column("target", sa.String(200), nullable=False),
        sa.Column("parameters", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("risk_level", sa.String(20), nullable=False),
        sa.Column("requires_approval", sa.Boolean, nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="PROPOSED"),
        sa.Column("policy_allowed", sa.Boolean, nullable=True),
        sa.Column("policy_rejection_reason", sa.Text, nullable=True),
        sa.Column("proposed_by", sa.String(100), nullable=False, server_default="remediation_agent"),
        sa.Column("proposed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_remediation_plans_incident_id", "remediation_plans", ["incident_id"])

    # approvals
    op.create_table(
        "approvals",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("plan_id", sa.String(36), sa.ForeignKey("remediation_plans.id"), nullable=False, unique=True),
        sa.Column("incident_id", sa.String(36), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("approved_by", sa.String(200), nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_approvals_plan_id", "approvals", ["plan_id"])

    # remediation_executions
    op.create_table(
        "remediation_executions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("plan_id", sa.String(36), sa.ForeignKey("remediation_plans.id"), nullable=False, unique=True),
        sa.Column("incident_id", sa.String(36), nullable=False),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("target", sa.String(200), nullable=False),
        sa.Column("namespace", sa.String(100), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="PENDING"),
        sa.Column("result", sa.Text, nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_idempotent_skip", sa.Boolean, nullable=False, server_default="false"),
    )

    # outbox_events
    op.create_table(
        "outbox_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("topic", sa.String(100), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("payload", sa.JSON, nullable=False),
        sa.Column("published", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_outbox_unpublished", "outbox_events", ["published", "created_at"])

    # processed_events (idempotency log)
    op.create_table(
        "processed_events",
        sa.Column("event_id", sa.String(36), primary_key=True),
        sa.Column("consumer_group", sa.String(100), nullable=False, primary_key=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("event_id", "consumer_group", name="uq_processed_event_per_group"),
    )

    # audit_logs
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("incident_id", sa.String(36), nullable=True),
        sa.Column("actor", sa.String(200), nullable=False),
        sa.Column("action", sa.String(200), nullable=False),
        sa.Column("resource_type", sa.String(100), nullable=False),
        sa.Column("resource_id", sa.String(200), nullable=False),
        sa.Column("details", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("outcome", sa.String(50), nullable=False, server_default="success"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_logs_incident_id", "audit_logs", ["incident_id"])

    # runbooks (with pgvector embedding)
    op.create_table(
        "runbooks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("service", sa.String(100), nullable=False),
        sa.Column("failure_type", sa.String(100), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("tags", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("embedding", Vector(1536), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    # historical_incidents (with pgvector embedding)
    op.create_table(
        "historical_incidents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("original_incident_id", sa.String(36), nullable=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("service", sa.String(100), nullable=False),
        sa.Column("root_cause", sa.Text, nullable=False),
        sa.Column("resolution", sa.Text, nullable=False),
        sa.Column("duration_minutes", sa.Integer, nullable=True),
        sa.Column("embedding", Vector(1536), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
    )

    # failure_scenarios
    op.create_table(
        "failure_scenarios",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("scenario_id", sa.String(100), nullable=False, unique=True),
        sa.Column("failure_type", sa.String(100), nullable=False),
        sa.Column("target_service", sa.String(100), nullable=False),
        sa.Column("expected_root_cause", sa.Text, nullable=False),
        sa.Column("acceptable_remediations", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("metadata", sa.JSON, nullable=False, server_default="{}"),
    )

    # benchmark_results
    op.create_table(
        "benchmark_results",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("scenario_id", sa.String(100), nullable=False),
        sa.Column("incident_id", sa.String(36), nullable=True),
        sa.Column("failure_type", sa.String(100), nullable=False),
        sa.Column("mttd_seconds", sa.Float, nullable=True),
        sa.Column("mttr_seconds", sa.Float, nullable=True),
        sa.Column("root_cause_correct", sa.Boolean, nullable=True),
        sa.Column("remediation_success", sa.Boolean, nullable=True),
        sa.Column("policy_rejections", sa.Integer, nullable=False, server_default="0"),
        sa.Column("unsafe_actions", sa.Integer, nullable=False, server_default="0"),
        sa.Column("duplicate_side_effects", sa.Integer, nullable=False, server_default="0"),
        sa.Column("workflow_recovered", sa.Boolean, nullable=True),
        sa.Column("llm_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("llm_cost_usd", sa.Float, nullable=False, server_default="0.0"),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_benchmark_results_run_id", "benchmark_results", ["run_id"])


def downgrade() -> None:
    op.drop_table("benchmark_results")
    op.drop_table("failure_scenarios")
    op.drop_table("historical_incidents")
    op.drop_table("runbooks")
    op.drop_table("audit_logs")
    op.drop_table("processed_events")
    op.drop_table("outbox_events")
    op.drop_table("remediation_executions")
    op.drop_table("approvals")
    op.drop_table("remediation_plans")
    op.drop_table("evidence")
    op.drop_table("investigations")
    op.drop_table("alerts")
    op.drop_table("incident_events")
    op.drop_table("incidents")
    op.execute("DROP EXTENSION IF EXISTS vector")
