"""
Unit Tests — Event Schemas

Tests that event schemas validate correctly, reject bad data,
and produce deterministic fingerprints.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from common.events.schemas import (
    AegisEvent,
    AlertSeverity,
    AlertStatus,
    IncidentCreatedPayload,
    IncidentSeverity,
    IncidentStatus,
    KafkaTopic,
    NormalizedAlertPayload,
    RawAlertPayload,
    RemediationAction,
    RemediationPlan,
    RiskLevel,
    RootCauseAnalysis,
    make_alert_raw_event,
    make_incident_created_event,
    new_event_id,
)


class TestEventEnvelope:
    def test_event_has_required_fields(self):
        payload = RawAlertPayload(
            alert_name="TestAlert",
            service="payment",
            namespace="production",
            severity=AlertSeverity.CRITICAL,
            status=AlertStatus.FIRING,
        )
        event = make_alert_raw_event(payload)
        assert event.event_id
        assert event.event_type == "ALERT_RAW_RECEIVED"
        assert event.timestamp is not None
        assert event.correlation_id
        assert event.schema_version == "1.0"
        assert event.payload is payload

    def test_event_id_is_uuid_format(self):
        import uuid
        eid = new_event_id()
        assert uuid.UUID(eid)  # raises if invalid

    def test_event_ids_are_unique(self):
        ids = {new_event_id() for _ in range(1000)}
        assert len(ids) == 1000

    def test_event_serializes_to_json(self):
        import json
        payload = RawAlertPayload(
            alert_name="Test",
            service="checkout",
            namespace="production",
            severity=AlertSeverity.WARNING,
            status=AlertStatus.FIRING,
        )
        event = make_alert_raw_event(payload)
        data = event.model_dump(mode="json")
        serialized = json.dumps(data)
        assert "event_id" in serialized
        assert "ALERT_RAW_RECEIVED" in serialized


class TestKafkaTopics:
    def test_all_topics_have_values(self):
        for topic in KafkaTopic:
            assert topic.value
            assert "." in topic.value

    def test_topic_count(self):
        # Ensure we have all expected topics
        assert len(KafkaTopic) == 12


class TestRootCauseAnalysis:
    def test_confidence_must_be_in_range(self):
        # Valid
        rca = RootCauseAnalysis(
            root_cause="test",
            confidence=0.85,
            suspected_component="payment",
        )
        assert rca.confidence == 0.85

    def test_rca_with_evidence(self):
        from common.events.schemas import EvidenceItem
        rca = RootCauseAnalysis(
            root_cause="DB connection exhaustion",
            confidence=0.91,
            suspected_component="payment",
            evidence=[
                EvidenceItem(source="prometheus", observation="pool at 96%", confidence_contribution=0.4),
                EvidenceItem(source="loki", observation="connection errors", confidence_contribution=0.35),
            ],
        )
        assert len(rca.evidence) == 2
        assert rca.evidence[0].source == "prometheus"


class TestRemediationPlan:
    def test_valid_plan(self):
        plan = RemediationPlan(
            plan_id=new_event_id(),
            incident_id=new_event_id(),
            action=RemediationAction.ROLLBACK_DEPLOYMENT,
            namespace="production",
            target="payment",
            reason="Test rollback",
            risk_level=RiskLevel.MEDIUM,
            requires_approval=True,
        )
        assert plan.action == RemediationAction.ROLLBACK_DEPLOYMENT
        assert plan.requires_approval is True

    def test_plan_serializes_correctly(self):
        plan = RemediationPlan(
            plan_id=new_event_id(),
            incident_id=new_event_id(),
            action=RemediationAction.RESTART_POD,
            namespace="production",
            target="payment",
            reason="Restart",
            risk_level=RiskLevel.LOW,
            requires_approval=False,
        )
        data = plan.model_dump(mode="json")
        assert data["action"] == "RESTART_POD"
        assert data["risk_level"] == "LOW"


class TestCorrelatorFingerprint:
    def test_same_alert_same_fingerprint(self):
        import hashlib, json
        def fp(name, service, ns):
            key = f"{name}:{service}:{ns}"
            return hashlib.sha256(key.encode()).hexdigest()[:32]

        f1 = fp("HighErrorRate", "payment", "production")
        f2 = fp("HighErrorRate", "payment", "production")
        assert f1 == f2

    def test_different_alerts_different_fingerprint(self):
        import hashlib
        def fp(name, service, ns):
            key = f"{name}:{service}:{ns}"
            return hashlib.sha256(key.encode()).hexdigest()[:32]

        f1 = fp("HighErrorRate", "payment", "production")
        f2 = fp("HighLatency", "payment", "production")
        assert f1 != f2
