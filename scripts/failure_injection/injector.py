"""
Failure Injection Framework

Provides reproducible failure scenarios for testing Aegis.
Each failure records metadata for automated evaluation.

Usage:
  python scripts/failure_injection/injector.py --scenario db-exhaustion
  python scripts/failure_injection/injector.py --scenario bad-deployment
  python scripts/failure_injection/injector.py --scenario pod-crash
  python scripts/failure_injection/injector.py --recover
"""
from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Optional

import click
import httpx

PAYMENT_URL = "http://localhost:3002"
CHECKOUT_URL = "http://localhost:3001"
INVENTORY_URL = "http://localhost:3003"


@dataclass
class FailureRecord:
    failure_id: str
    failure_type: str
    target_service: str
    start_time: str
    expected_root_cause: str
    expected_remediation: str
    parameters: dict


async def _post(url: str, params: dict | None = None) -> dict:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(url, params=params)
        return resp.json()


async def inject_db_exhaustion() -> FailureRecord:
    """Hold all DB connections in payment service to exhaust the pool."""
    click.echo("🔴 Injecting: Database Connection Pool Exhaustion → payment service")
    await _post(f"{PAYMENT_URL}/admin/inject/db-exhaustion")
    record = FailureRecord(
        failure_id=str(uuid.uuid4()),
        failure_type="db_exhaustion",
        target_service="payment",
        start_time=datetime.now(tz=timezone.utc).isoformat(),
        expected_root_cause="database connection pool exhaustion",
        expected_remediation="ROLLBACK_DEPLOYMENT or RESTART_POD",
        parameters={"held_connections": "max_pool_size"},
    )
    click.echo(f"✓ Failure injected: {record.failure_id}")
    return record


async def inject_latency(ms: int = 2000) -> FailureRecord:
    """Add artificial latency to payment service."""
    click.echo(f"🔴 Injecting: Artificial Latency ({ms}ms) → payment service")
    await _post(f"{PAYMENT_URL}/admin/inject/latency", params={"ms": ms})
    record = FailureRecord(
        failure_id=str(uuid.uuid4()),
        failure_type="latency_injection",
        target_service="payment",
        start_time=datetime.now(tz=timezone.utc).isoformat(),
        expected_root_cause="elevated latency due to artificial delay",
        expected_remediation="SCALE_DEPLOYMENT or RESTART_POD",
        parameters={"latency_ms": ms},
    )
    click.echo(f"✓ Failure injected: {record.failure_id}")
    return record


async def inject_error_rate(rate: float = 0.8) -> FailureRecord:
    """Inject high error rate in payment service (simulates bad deployment)."""
    click.echo(f"🔴 Injecting: Bad Deployment / High Error Rate ({rate*100:.0f}%) → payment service")
    await _post(f"{PAYMENT_URL}/admin/inject/error-rate", params={"rate": rate})
    record = FailureRecord(
        failure_id=str(uuid.uuid4()),
        failure_type="bad_deployment",
        target_service="payment",
        start_time=datetime.now(tz=timezone.utc).isoformat(),
        expected_root_cause="bad deployment introducing 500 errors",
        expected_remediation="ROLLBACK_DEPLOYMENT",
        parameters={"error_rate": rate},
    )
    click.echo(f"✓ Failure injected: {record.failure_id}")
    return record


async def inject_cpu_saturation(duration_seconds: int = 30) -> FailureRecord:
    """Inject CPU saturation on payment service."""
    click.echo(f"🔴 Injecting: CPU Saturation ({duration_seconds}s) → payment service")
    await _post(f"{PAYMENT_URL}/admin/inject/cpu-saturation", params={"duration_seconds": duration_seconds})
    record = FailureRecord(
        failure_id=str(uuid.uuid4()),
        failure_type="cpu_saturation",
        target_service="payment",
        start_time=datetime.now(tz=timezone.utc).isoformat(),
        expected_root_cause="cpu saturation causing service degradation",
        expected_remediation="SCALE_DEPLOYMENT",
        parameters={"duration_seconds": duration_seconds},
    )
    click.echo(f"✓ Failure injected: {record.failure_id}")
    return record


async def inject_memory_pressure(megabytes: int = 256) -> FailureRecord:
    """Inject memory pressure on payment service."""
    click.echo(f"🔴 Injecting: Memory Pressure ({megabytes}MB) → payment service")
    await _post(f"{PAYMENT_URL}/admin/inject/memory-pressure", params={"megabytes": megabytes})
    record = FailureRecord(
        failure_id=str(uuid.uuid4()),
        failure_type="memory_pressure",
        target_service="payment",
        start_time=datetime.now(tz=timezone.utc).isoformat(),
        expected_root_cause="memory pressure causing near-OOM state",
        expected_remediation="RESTART_POD",
        parameters={"allocated_mb": megabytes},
    )
    click.echo(f"✓ Failure injected: {record.failure_id}")
    return record


async def inject_pod_crash() -> FailureRecord:
    """Trigger process termination / pod crash loop on payment service."""
    click.echo("🔴 Injecting: Pod Crash / Process Kill → payment service")
    try:
        await _post(f"{PAYMENT_URL}/admin/inject/pod-crash")
    except Exception:
        pass
    record = FailureRecord(
        failure_id=str(uuid.uuid4()),
        failure_type="pod_crash",
        target_service="payment",
        start_time=datetime.now(tz=timezone.utc).isoformat(),
        expected_root_cause="pod crash loop",
        expected_remediation="RESTART_POD",
        parameters={"crash_type": "process_exit"},
    )
    click.echo(f"✓ Failure injected: {record.failure_id}")
    return record


async def inject_redis_failure() -> FailureRecord:
    """Inject Redis failure on inventory service."""
    click.echo("🔴 Injecting: Redis Connection Failure → inventory service")
    await _post(f"{INVENTORY_URL}/admin/inject/redis-failure")
    record = FailureRecord(
        failure_id=str(uuid.uuid4()),
        failure_type="redis_failure",
        target_service="inventory",
        start_time=datetime.now(tz=timezone.utc).isoformat(),
        expected_root_cause="redis cache failure",
        expected_remediation="RESTART_POD",
        parameters={"service": "inventory", "target": "redis"},
    )
    click.echo(f"✓ Failure injected: {record.failure_id}")
    return record


async def inject_dependency_timeout() -> FailureRecord:
    """Inject dependency timeout in checkout service."""
    click.echo("🔴 Injecting: Upstream Dependency Timeout → checkout service")
    await _post(f"{CHECKOUT_URL}/admin/inject/dependency-timeout")
    record = FailureRecord(
        failure_id=str(uuid.uuid4()),
        failure_type="dependency_timeout",
        target_service="checkout",
        start_time=datetime.now(tz=timezone.utc).isoformat(),
        expected_root_cause="upstream dependency failure / timeout",
        expected_remediation="RESTART_POD",
        parameters={"service": "checkout", "timeout_shortened": True},
    )
    click.echo(f"✓ Failure injected: {record.failure_id}")
    return record


async def recover_all() -> None:
    """Clear all active failure injections across all services."""
    click.echo("🟢 Recovering all services...")
    for url in [PAYMENT_URL, CHECKOUT_URL, INVENTORY_URL]:
        try:
            await _post(f"{url}/admin/recover")
        except Exception:
            pass
    click.echo("✓ All services recovered")


@click.command()
@click.option("--scenario", type=click.Choice([
    "db-exhaustion",
    "latency",
    "bad-deployment",
    "cpu-saturation",
    "memory-pressure",
    "pod-crash",
    "redis-failure",
    "dependency-timeout",
    "recover",
]), required=True, help="Failure scenario to inject")
@click.option("--latency-ms", default=2000, help="Latency in milliseconds (for latency scenario)")
@click.option("--error-rate", default=0.8, help="Error rate 0.0-1.0 (for bad-deployment scenario)")
@click.option("--output", default=None, help="JSON file to write failure record")
def main(scenario: str, latency_ms: int, error_rate: float, output: Optional[str]):
    """Aegis Failure Injection Framework."""

    async def run():
        record = None
        if scenario == "db-exhaustion":
            record = await inject_db_exhaustion()
        elif scenario == "latency":
            record = await inject_latency(latency_ms)
        elif scenario == "bad-deployment":
            record = await inject_error_rate(error_rate)
        elif scenario == "cpu-saturation":
            record = await inject_cpu_saturation()
        elif scenario == "memory-pressure":
            record = await inject_memory_pressure()
        elif scenario == "pod-crash":
            record = await inject_pod_crash()
        elif scenario == "redis-failure":
            record = await inject_redis_failure()
        elif scenario == "dependency-timeout":
            record = await inject_dependency_timeout()
        elif scenario == "recover":
            await recover_all()

        if record and output:
            with open(output, "w") as f:
                json.dump(asdict(record), f, indent=2)
            click.echo(f"✓ Failure record written to {output}")

        if record:
            click.echo(f"\nFailure Record:")
            click.echo(json.dumps(asdict(record), indent=2))

    asyncio.run(run())


if __name__ == "__main__":
    main()
