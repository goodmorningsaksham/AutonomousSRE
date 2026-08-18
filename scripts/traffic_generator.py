"""
Traffic Generator — simulates realistic user traffic against demo services.

Runs continuous checkout requests at configurable RPS.
Tracks success/failure rates for baseline measurement.
"""
from __future__ import annotations

import asyncio
import os
import random
import time
from datetime import datetime

import click
import httpx

CHECKOUT_URL = os.getenv("CHECKOUT_URL", "http://localhost:3001")
DEFAULT_RPS = 5
ITEM_IDS = [f"item-{i}" for i in range(1, 21)]


async def send_checkout(client: httpx.AsyncClient, session_id: str) -> bool:
    item = random.choice(ITEM_IDS)
    amount = round(random.uniform(5.0, 500.0), 2)
    try:
        resp = await client.post(
            f"{CHECKOUT_URL}/api/v1/checkout",
            params={"item_id": item, "quantity": 1, "amount": amount},
            timeout=5.0,
        )
        return resp.status_code == 200
    except Exception:
        return False


async def run_traffic(rps: int, duration_seconds: int | None) -> None:
    """Generate continuous traffic at the given requests per second."""
    interval = 1.0 / rps
    start_time = time.monotonic()
    total = 0
    successes = 0
    failures = 0

    click.echo(f"🚦 Traffic generator started: {rps} RPS → {CHECKOUT_URL}")
    if duration_seconds:
        click.echo(f"   Duration: {duration_seconds}s")
    else:
        click.echo("   Duration: infinite (Ctrl+C to stop)")

    async with httpx.AsyncClient() as client:
        while True:
            if duration_seconds and (time.monotonic() - start_time) >= duration_seconds:
                break

            session_id = str(random.randint(1000, 9999))
            success = await send_checkout(client, session_id)
            total += 1
            if success:
                successes += 1
            else:
                failures += 1

            if total % (rps * 10) == 0:
                elapsed = time.monotonic() - start_time
                error_rate = failures / total if total > 0 else 0
                click.echo(
                    f"  [{elapsed:.0f}s] Requests: {total} | "
                    f"Success: {successes} | Failures: {failures} | "
                    f"Error rate: {error_rate:.1%}"
                )

            await asyncio.sleep(interval)

    click.echo(f"\n✓ Done. Total: {total}, Successes: {successes}, Failures: {failures}")


@click.command()
@click.option("--rps", default=DEFAULT_RPS, help="Requests per second")
@click.option("--duration", default=None, type=int, help="Duration in seconds (default: infinite)")
def main(rps: int, duration: int | None):
    """Aegis Demo Traffic Generator."""
    asyncio.run(run_traffic(rps, duration))


if __name__ == "__main__":
    main()
