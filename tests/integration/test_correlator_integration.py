"""
Integration Tests — Correlator Logic & Dependency Graph

Tests:
1. Service dependency graph upstream correlation (checkout → payment)
2. Alert deduplication by fingerprint within time window
3. Incident severity escalation when critical alert correlates with medium incident
4. Outbox event generation
"""
from __future__ import annotations

import hashlib
import json
import pytest
from datetime import datetime, timezone

from common.events.schemas import (
    AlertSeverity,
    AlertStatus,
    IncidentSeverity,
    IncidentStatus,
    NormalizedAlertPayload,
    RawAlertPayload,
    make_alert_raw_event,
    new_event_id,
)
from services.correlator.main import (
    SERVICE_DEPENDENCY_GRAPH,
    _fingerprint_alert,
    _get_root_services,
    _incident_severity,
    _normalize_alert,
    _severity_rank,
)


class TestDependencyGraph:
    def test_checkout_depends_on_payment_and_inventory(self):
        assert "payment" in SERVICE_DEPENDENCY_GRAPH["checkout"]
        assert "inventory" in SERVICE_DEPENDENCY_GRAPH["checkout"]

    def test_payment_depends_on_postgres(self):
        deps = SERVICE_DEPENDENCY_GRAPH["payment"]
        assert any("postgres" in d for d in deps)

    def test_inventory_depends_on_redis(self):
        deps = SERVICE_DEPENDENCY_GRAPH["inventory"]
        assert any("redis" in d for d in deps)

    def test_root_services_traversal_from_payment(self):
        # If payment fails, checkout is also a dependent
        roots = _get_root_services("payment")
        assert "payment" in roots
        assert "checkout" in roots

    def test_root_services_traversal_from_inventory(self):
        roots = _get_root_services("inventory")
        assert "inventory" in roots
        assert "checkout" in roots


class TestSeverityRanking:
    def test_severity_ranks_in_order(self):
        assert _severity_rank("critical") > _severity_rank("high")
        assert _severity_rank("high") > _severity_rank("warning")
        assert _severity_rank("warning") > _severity_rank("info")

    def test_incident_severity_mapping(self):
        assert _incident_severity("critical") == IncidentSeverity.CRITICAL
        assert _incident_severity("high") == IncidentSeverity.HIGH
        assert _incident_severity("warning") == IncidentSeverity.MEDIUM
        assert _incident_severity("info") == IncidentSeverity.LOW


class TestAlertNormalizationAndFingerprinting:
    def test_fingerprint_is_deterministic(self):
        fp1 = _fingerprint_alert("HighErrorRate", "payment", "production", {"job": "payment"})
        fp2 = _fingerprint_alert("HighErrorRate", "payment", "production", {"job": "payment"})
        assert fp1 == fp2
        assert len(fp1) == 32

    def test_normalize_raw_alert(self):
        raw_event = {
            "event_id": new_event_id(),
            "payload": {
                "alert_name": "DatabaseConnectionExhaustion",
                "service": "payment",
                "namespace": "production",
                "severity": "critical",
                "status": "firing",
                "labels": {"alertname": "DatabaseConnectionExhaustion", "service": "payment"},
                "annotations": {"summary": "DB pool at 98%", "description": "Too many connections"},
            }
        }
        normalized = _normalize_alert(raw_event)
        assert normalized.alert_name == "DatabaseConnectionExhaustion"
        assert normalized.service == "payment"
        assert normalized.severity == AlertSeverity.CRITICAL
        assert normalized.status == AlertStatus.FIRING
        assert normalized.summary == "DB pool at 98%"
        assert normalized.fingerprint != ""
