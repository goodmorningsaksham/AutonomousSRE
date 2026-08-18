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
        expected_remediation="RESTART_POD",
        parameters={"latency_ms": ms},
    )
    click.echo(f"✓ Failure injected: {record.failure_id}")
    return record


async def inject_error_rate(rate: float = 0.8) -> FailureRecord:
    """Inject high error rate in payment service (simulates bad deployment)."""
    click.echo(f"🔴 Injecting: High Error Rate ({rate*100:.0f}%) → payment service")
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


async def recover_all() -> None:
    """Clear all active failure injections."""
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
