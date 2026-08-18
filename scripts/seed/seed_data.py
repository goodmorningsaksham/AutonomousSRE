"""Seed runbooks and historical incidents for RAG."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from database.models.models import Runbook, HistoricalIncident
from database.session import AsyncSessionLocal
from common.events.schemas import new_event_id


RUNBOOKS = [
    {
        "title": "Database Connection Pool Exhaustion Runbook",
        "service": "payment",
        "failure_type": "db_exhaustion",
        "content": """## Database Connection Pool Exhaustion

### Symptoms
- `db_pool_connections_used / db_pool_connections_max > 0.90`
- HTTP 500 errors with message "connection pool exhausted"
- Increased latency on payment endpoints

### Root Cause Analysis
1. Check recent deployments for connection leak in new code
2. Check for connection not being released in exception paths
3. Check for long-running transactions blocking pool slots

### Remediation Steps
1. **Immediate**: Rollback recent deployment if present (< 1 hour)
2. **Short term**: Increase pool size temporarily (SCALE_DEPLOYMENT)
3. **Root fix**: Fix connection leak in application code

### Prevention
- Always use context managers for DB connections
- Set connection timeout in pool config
- Monitor pool utilization with Prometheus alerts at 80%""",
        "tags": ["database", "connection-pool", "payment", "postgresql"],
    },
    {
        "title": "Bad Deployment Rollback Runbook",
        "service": "payment",
        "failure_type": "bad_deployment",
        "content": """## Bad Deployment Response

### Symptoms
- Error rate spike immediately after deployment
- Stack traces point to new code paths
- p99 latency increase

### Root Cause Analysis
1. Correlate error spike timestamp with deployment time
2. Check deployment logs for image tag change
3. Review new code paths in stack traces

### Remediation Steps
1. Immediately rollback to previous revision: ROLLBACK_DEPLOYMENT
2. Verify error rate returns to baseline after rollback
3. Create post-mortem for deployment failure

### Prevention
- Add integration tests for all new code paths
- Use canary deployments
- Set max surge to 1 replica during rollouts""",
        "tags": ["deployment", "rollback", "payment"],
    },
    {
        "title": "Pod Crash Loop Recovery Runbook",
        "service": "payment",
        "failure_type": "pod_crash",
        "content": """## Pod CrashLoop Recovery

### Symptoms
- Pod restart count > 3 in last 10 minutes
- OOMKilled or exit code != 0

### Root Cause Analysis
1. Check pod logs for crash reason (OOMKilled / application panic)
2. Check memory limits vs. actual usage
3. Check for missing environment variables or secrets

### Remediation Steps
1. If OOMKilled: increase memory limit or rollback recent deployment
2. If application crash: ROLLBACK_DEPLOYMENT to stable version
3. If config issue: CHANGE_CONFIG (requires approval)

### Prevention
- Set memory requests and limits based on profiling
- Add liveness probes with appropriate thresholds""",
        "tags": ["pod", "crash", "oomkilled", "kubernetes"],
    },
]

HISTORICAL = [
    {
        "title": "Payment DB Connection Exhaustion — Q1 Incident",
        "service": "payment",
        "root_cause": "database connection pool exhaustion caused by missing connection.close() in exception handler",
        "resolution": "Rolled back payment-v38 which introduced the connection leak. Fixed in v39 with proper context manager usage.",
        "duration_minutes": 23,
    },
    {
        "title": "Payment 500s After Deployment",
        "service": "payment",
        "root_cause": "NullPointerException in new payment validation code path for international cards",
        "resolution": "Rolled back payment deployment to v41. Patched in v42 with null check.",
        "duration_minutes": 8,
    },
    {
        "title": "Checkout Cascade Failure from Payment Outage",
        "service": "checkout",
        "root_cause": "checkout service cascade failures caused by payment service being unreachable",
        "resolution": "Added circuit breaker to checkout→payment call. Restored payment service via pod restart.",
        "duration_minutes": 15,
    },
    {
        "title": "Inventory Redis Cache Miss Causing Latency",
        "service": "inventory",
        "root_cause": "Redis cache evicted all inventory data causing cache stampede on PostgreSQL",
        "resolution": "Increased Redis maxmemory-policy to allkeys-lru, increased TTL for hot items.",
        "duration_minutes": 12,
    },
]


async def seed() -> None:
    print("Seeding runbooks and historical incidents...")
    async with AsyncSessionLocal() as session:
        async with session.begin():
            for rb_data in RUNBOOKS:
                rb = Runbook(
                    id=new_event_id(),
                    title=rb_data["title"],
                    service=rb_data["service"],
                    failure_type=rb_data["failure_type"],
                    content=rb_data["content"],
                    tags=rb_data["tags"],
                    created_at=datetime.now(tz=timezone.utc),
                )
                session.add(rb)

            for hi_data in HISTORICAL:
                hi = HistoricalIncident(
                    id=new_event_id(),
                    title=hi_data["title"],
                    service=hi_data["service"],
                    root_cause=hi_data["root_cause"],
                    resolution=hi_data["resolution"],
                    duration_minutes=hi_data["duration_minutes"],
                    occurred_at=datetime.now(tz=timezone.utc),
                )
                session.add(hi)

    print(f"✓ Seeded {len(RUNBOOKS)} runbooks and {len(HISTORICAL)} historical incidents")


if __name__ == "__main__":
    asyncio.run(seed())
