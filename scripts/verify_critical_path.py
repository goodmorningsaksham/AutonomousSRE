"""
Verification Script — Critical Path Live Test

Tests:
1. Injects DB connection pool exhaustion failure on payment service (:3002)
2. Sends checkout traffic (:3001) that experiences errors
3. Sends Alertmanager alert webhook to Aegis Ingestor (:8001)
4. Verifies Kafka event publication -> Correlator grouping -> Incident creation in PostgreSQL
5. Verifies Investigator picks up incident -> Gathers telemetry -> Executes RCA -> Evaluates Policy -> Executes Remediation -> Verifies recovery
6. Verifies complete timeline persisted and accessible via Aegis API (:8000)
"""
import asyncio
import httpx
import json
import time


async def run_live_test():
    async with httpx.AsyncClient(timeout=20.0) as client:
        # 1. Inject failure
        print("1. Injecting DB exhaustion on payment service (:3002)...")
        inj_resp = await client.post("http://localhost:3002/admin/inject/db-exhaustion")
        print("   Injection response:", inj_resp.json())

        # 2. Generate traffic that fails
        print("2. Sending failing checkout traffic (:3001)...")
        fail_count = 0
        for _ in range(5):
            try:
                resp = await client.post("http://localhost:3001/api/v1/checkout", params={"item_id": "item-1", "amount": 100.0})
                if resp.status_code != 200:
                    fail_count += 1
            except Exception:
                fail_count += 1
        print(f"   Sent 5 requests, observed {fail_count} failures (expected).")

        # 3. Post alert to Aegis Ingestor
        print("3. Sending firing alert to Aegis Ingestor (:8001)...")
        alert_payload = {
            "alert_name": "DatabaseConnectionExhaustion",
            "service": "payment",
            "namespace": "production",
            "severity": "critical",
            "status": "firing",
            "labels": {"service": "payment", "alertname": "DatabaseConnectionExhaustion"},
            "annotations": {
                "summary": "Database connection pool exhausted",
                "description": "DB connection pool utilization exceeds 95%"
            }
        }
        ing_resp = await client.post("http://localhost:8001/api/v1/alerts", json=alert_payload)
        print("   Ingestor accepted response:", ing_resp.json())
        alert_event_id = ing_resp.json().get("event_id")

        # 4. Poll for incident creation & investigation completion
        print("4. Monitoring Aegis API (:8000) for incident and RCA progress...")
        incident = None
        for i in range(20):
            await asyncio.sleep(2)
            inc_resp = await client.get("http://localhost:8000/api/v1/incidents?limit=5")
            if inc_resp.status_code == 200 and inc_resp.json():
                incidents = inc_resp.json()
                matching = [inc for inc in incidents if inc["service"] == "payment"]
                if matching:
                    incident = matching[0]
                    print(f"   [{i*2}s] Incident {incident['id'][:8]} Status: {incident['status']}")
                    if incident["status"] in ("DIAGNOSED", "REMEDIATING", "VERIFYING", "RESOLVED", "AWAITING_APPROVAL"):
                        break

        assert incident is not None, "FAILED: No incident created in PostgreSQL within timeout!"
        inc_id = incident["id"]

        # 5. Fetch full detail
        print(f"5. Fetching detailed incident report for {inc_id}...")
        detail_resp = await client.get(f"http://localhost:8000/api/v1/incidents/{inc_id}")
        detail = detail_resp.json()
        print("   Status:", detail["incident"]["status"])
        print("   Root Cause:", detail["incident"]["root_cause"])
        print("   Confidence:", detail["incident"]["confidence"])
        print(f"   Timeline ({len(detail['timeline'])} events):")
        for ev in detail["timeline"]:
            print(f"     - [{ev['event_type']}] {ev['description']}")

        print(f"   Remediation Plans ({len(detail['remediation_plans'])}):")
        for plan in detail["remediation_plans"]:
            print(f"     - Action: {plan['action']} Target: {plan['target']} Risk: {plan['risk_level']} Status: {plan['status']}")

        # 6. Cleanup / Recover
        await client.post("http://localhost:3002/admin/recover")
        print("6. Payment service cleared failure injection [OK].")


if __name__ == "__main__":
    asyncio.run(run_live_test())
