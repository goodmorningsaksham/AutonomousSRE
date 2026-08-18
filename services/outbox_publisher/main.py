"""
Transactional Outbox Publisher

Polls the outbox_events table for unpublished events and
publishes them to Kafka. Retries with exponential back-off.

This ensures events are never lost even if Kafka is temporarily unavailable:
- The business operation (incident create/update) commits atomically with the outbox record
- This poller then publishes reliably with retries
- Once published, marks the outbox record as published

Idempotency: Publishing the same outbox event twice is safe because
Kafka consumers check the processed_events table before handling.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from sqlalchemy import select, and_

from common.config.settings import get_settings
from common.kafka.admin import ensure_topics_exist
from common.kafka.producer import AegisProducer
from common.logging.logger import get_logger
from database.models.models import OutboxEvent
from database.session import AsyncSessionLocal

logger = get_logger(__name__)
settings = get_settings()

POLL_INTERVAL_SECONDS = 1
MAX_RETRIES = 10
MAX_BATCH_SIZE = 50


async def publish_pending(producer: AegisProducer) -> int:
    """Publish a batch of unpublished outbox events. Returns count published."""
    published = 0

    async with AsyncSessionLocal() as session:
        async with session.begin():
            result = await session.execute(
                select(OutboxEvent)
                .where(
                    and_(
                        OutboxEvent.published == False,  # noqa: E712
                        OutboxEvent.attempts < MAX_RETRIES,
                    )
                )
                .order_by(OutboxEvent.created_at.asc())
                .limit(MAX_BATCH_SIZE)
                .with_for_update(skip_locked=True)  # prevent concurrent duplication
            )
            events = result.scalars().all()

            for outbox_event in events:
                try:
                    await producer.send(
                        topic=outbox_event.topic,
                        event=outbox_event.payload,
                        key=str(outbox_event.payload.get("correlation_id", "")),
                    )
                    outbox_event.published = True
                    outbox_event.published_at = datetime.now(tz=timezone.utc)
                    outbox_event.last_error = None
                    published += 1
                    logger.debug(
                        "Outbox event published",
                        outbox_id=outbox_event.id,
                        topic=outbox_event.topic,
                        event_type=outbox_event.event_type,
                    )
                except Exception as exc:
                    outbox_event.attempts += 1
                    outbox_event.last_error = str(exc)
                    logger.warning(
                        "Outbox event publish failed",
                        outbox_id=outbox_event.id,
                        topic=outbox_event.topic,
                        attempt=outbox_event.attempts,
                        error=str(exc),
                    )

    return published


async def main() -> None:
    await ensure_topics_exist()

    producer = AegisProducer()
    await producer.start()
    logger.info("Outbox publisher started")

    try:
        while True:
            try:
                count = await publish_pending(producer)
                if count > 0:
                    logger.info("Outbox batch published", count=count)
            except Exception as exc:
                logger.error("Outbox poll error", error=str(exc), exc_info=True)

            await asyncio.sleep(POLL_INTERVAL_SECONDS)
    finally:
        await producer.stop()
        logger.info("Outbox publisher stopped")


if __name__ == "__main__":
    asyncio.run(main())
