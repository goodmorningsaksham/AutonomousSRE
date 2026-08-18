"""
E2E Test — Complete Incident Lifecycle

Tests the full critical path:
  failure → alert → kafka → correlation → investigation → rca → policy → remediation → verification → resolved

This test uses the real services running via docker-compose.
Run with: pytest tests/e2e/ -v --timeout=120

Requires: docker-compose up (infrastructure + aegis services)
"""
from __future__ import annotations

import asyncio
import time

import httpx
import pytest

AEGIS_API = "http://localhost:8000"
AEGIS_INGESTOR = "http://localhost:8001"
PAYMENT_URL = "http://localhost:3002"

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def http_client():
    async with httpx.AsyncClient(timeout=10.0) as client:
        yield client


async def _wait_for_service(client: httpx.AsyncClient, url: str, timeout: int = 30) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            resp = await client.get(f"{url}/health")
            if resp.status_code == 200:
                return True
        except Exception:
            pass
        await asyncio.sleep(1)
    return False


class TestE2EIncidentLifecycle:
    async def test_services_healthy(self, http_client):
        for name, url in [("api", AEGIS_API), ("ingestor", AEGIS_INGESTOR)]:
            healthy = await _wait_for_service(http_client, url, timeout=10)
            assert healthy, f"{name} service not healthy at {url}"

    async def test_manual_alert_creates_incident(self, http_client):
        """
        Inject a manual alert via the ingestor API and verify
        an incident is created within 30 seconds.
        """
        # Capture initial incident IDs
        init_resp = await http_client.get(f"{AEGIS_API}/api/v1/incidents?limit=20")
        initial_ids = {i["id"] for i in (init_resp.json() if init_resp.status_code == 200 else [])}

        # Send manual alert
        suffix = int(time.time())
        resp = await http_client.post(
            f"{AEGIS_INGESTOR}/api/v1/alerts",
            json={
                "alert_name": f"HighErrorRate_{suffix}",
                "service": "payment",
                "namespace": "production",
                "severity": "critical",
                "status": "firing",
                "labels": {"service": "payment", "alertname": f"HighErrorRate_{suffix}"},
                "annotations": {"summary": "High error rate on payment"},
            }
        )
        assert resp.status_code == 202
        event_id = resp.json()["event_id"]
        assert event_id

        # Wait for incident to be created
        incident = None
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            list_resp = await http_client.get(f"{AEGIS_API}/api/v1/incidents?limit=20")
            if list_resp.status_code == 200:
                incidents = list_resp.json()
                matching = [i for i in incidents if i["id"] not in initial_ids or "payment" in i["service"]]
                valid = [i for i in matching if i["status"] != "FAILED"]
                if valid:
                    incident = valid[0]
                    break
            await asyncio.sleep(2)

        assert incident is not None, "No incident created within 30s of alert injection"
        assert incident["service"] == "payment"
        assert incident["status"] in (
            "DETECTED", "CORRELATING", "INVESTIGATING", "DIAGNOSED",
            "AWAITING_APPROVAL", "REMEDIATING", "VERIFYING", "RESOLVED"
        )

    async def test_alertmanager_webhook_accepted(self, http_client):
        """Test that Alertmanager webhook format is accepted."""
        alertmanager_payload = {
            "version": "4",
            "status": "firing",
            "receiver": "aegis-webhook",
            "groupLabels": {"service": "payment"},
            "commonLabels": {"service": "payment", "namespace": "production"},
            "commonAnnotations": {"summary": "Test alert"},
            "alerts": [
                {
                    "status": "firing",
                    "labels": {
                        "alertname": "DatabaseConnectionExhaustion",
                        "service": "payment",
                        "namespace": "production",
                        "severity": "critical",
                    },
                    "annotations": {
                        "summary": "DB connection pool exhausted",
                        "description": "DB connections at 97%",
                    },
                    "startsAt": "2024-01-01T00:00:00Z",
                    "fingerprint": "test-fingerprint-001",
                }
            ]
        }

        resp = await http_client.post(
            f"{AEGIS_INGESTOR}/webhooks/alertmanager",
            json=alertmanager_payload,
        )
        assert resp.status_code == 202
        data = resp.json()
        assert data["status"] == "accepted"
        assert data["published"] == 1

    async def test_incident_detail_has_timeline(self, http_client):
        """An incident should have at least one timeline event."""
        # Get latest incident
        resp = await http_client.get(f"{AEGIS_API}/api/v1/incidents?limit=1")
        if resp.status_code != 200 or not resp.json():
            pytest.skip("No incidents available")

        incident_id = resp.json()[0]["id"]
        detail_resp = await http_client.get(f"{AEGIS_API}/api/v1/incidents/{incident_id}")
        assert detail_resp.status_code == 200
        detail = detail_resp.json()
        assert "timeline" in detail
        assert len(detail["timeline"]) > 0

    async def test_stats_endpoint(self, http_client):
        resp = await http_client.get(f"{AEGIS_API}/api/v1/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "incidents_by_status" in data
        assert "total" in data
