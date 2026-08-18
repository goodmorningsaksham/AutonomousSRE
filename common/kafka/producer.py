from __future__ import annotations

import json
import asyncio
from typing import Any, Optional

from aiokafka import AIOKafkaProducer
from aiokafka.errors import KafkaConnectionError

from common.config.settings import get_settings
from common.logging.logger import get_logger

logger = get_logger(__name__)


class AegisProducer:
    """
    Thin async Kafka producer wrapper.

    Usage:
        producer = AegisProducer()
        await producer.start()
        await producer.send(KafkaTopic.ALERTS_RAW, event)
        await producer.stop()
    """

    def __init__(self) -> None:
        self._settings = get_settings()
        self._producer: Optional[AIOKafkaProducer] = None

    async def start(self) -> None:
        self._producer = AIOKafkaProducer(
            bootstrap_servers=self._settings.kafka_bootstrap_servers,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            key_serializer=lambda k: k.encode("utf-8") if k else None,
            acks="all",
            enable_idempotence=True,
            retry_backoff_ms=500,
        )
        await self._producer.start()
        logger.info("Kafka producer started", bootstrap=self._settings.kafka_bootstrap_servers)

    async def stop(self) -> None:
        if self._producer:
            await self._producer.stop()
            logger.info("Kafka producer stopped")

    async def send(
        self,
        topic: str,
        event: Any,
        key: Optional[str] = None,
    ) -> None:
        """
        Serialise an AegisEvent (or any dict/BaseModel) and publish it.
        Retries 3 times with exponential back-off before raising.
        """
        if self._producer is None:
            raise RuntimeError("Producer not started — call .start() first")

        if hasattr(event, "model_dump"):
            payload = event.model_dump(mode="json")
        elif isinstance(event, dict):
            payload = event
        else:
            payload = dict(event)

        routing_key = key or payload.get("correlation_id") or payload.get("event_id")

        for attempt in range(1, 4):
            try:
                await self._producer.send_and_wait(topic, value=payload, key=routing_key)
                logger.debug(
                    "Event published",
                    topic=topic,
                    event_type=payload.get("event_type"),
                    event_id=payload.get("event_id"),
                )
                return
            except KafkaConnectionError as exc:
                if attempt == 3:
                    logger.error("Kafka publish failed after 3 attempts", topic=topic, error=str(exc))
                    raise
                await asyncio.sleep(0.5 * (2 ** attempt))

    async def __aenter__(self) -> "AegisProducer":
        await self.start()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.stop()


# ── Singleton for use inside long-running services ────────────────────────────
_producer_instance: Optional[AegisProducer] = None


async def get_producer() -> AegisProducer:
    global _producer_instance
    if _producer_instance is None:
        _producer_instance = AegisProducer()
        await _producer_instance.start()
    return _producer_instance


async def shutdown_producer() -> None:
    global _producer_instance
    if _producer_instance is not None:
        await _producer_instance.stop()
        _producer_instance = None
