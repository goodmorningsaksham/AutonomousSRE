from __future__ import annotations

import asyncio
import json
from abc import ABC, abstractmethod
from typing import Any, Callable, Coroutine, Optional

from aiokafka import AIOKafkaConsumer
from aiokafka.structs import ConsumerRecord

from common.config.settings import get_settings
from common.logging.logger import get_logger

logger = get_logger(__name__)

MessageHandler = Callable[[dict[str, Any]], Coroutine[Any, Any, None]]


class AegisConsumer:
    """
    Generic async Kafka consumer.

    Implements the canonical at-least-once consume loop:
        receive → validate → idempotency check → process → commit offset

    The caller provides a handler coroutine and an optional idempotency checker.
    """

    def __init__(
        self,
        topics: list[str],
        group_id: str,
        handler: MessageHandler,
        idempotency_checker: Optional[Callable[[str], Coroutine[Any, Any, bool]]] = None,
        auto_offset_reset: str = "earliest",
    ) -> None:
        self._settings = get_settings()
        self._topics = topics
        self._group_id = group_id
        self._handler = handler
        self._idempotency_checker = idempotency_checker
        self._auto_offset_reset = auto_offset_reset
        self._consumer: Optional[AIOKafkaConsumer] = None
        self._running = False

    async def start(self) -> None:
        self._consumer = AIOKafkaConsumer(
            *self._topics,
            bootstrap_servers=self._settings.kafka_bootstrap_servers,
            group_id=self._group_id,
            value_deserializer=lambda v: json.loads(v.decode("utf-8")),
            auto_offset_reset=self._auto_offset_reset,
            enable_auto_commit=False,  # manual commit after successful processing
            session_timeout_ms=30_000,
            heartbeat_interval_ms=10_000,
            max_poll_interval_ms=300_000,
        )
        await self._consumer.start()
        self._running = True
        logger.info(
            "Kafka consumer started",
            topics=self._topics,
            group_id=self._group_id,
        )

    async def stop(self) -> None:
        self._running = False
        if self._consumer:
            await self._consumer.stop()
            logger.info("Kafka consumer stopped", group_id=self._group_id)

    async def run(self) -> None:
        """Main consume loop. Runs until stop() is called."""
        if self._consumer is None:
            raise RuntimeError("Consumer not started")

        async for record in self._consumer:
            if not self._running:
                break
            await self._process_record(record)

    async def _process_record(self, record: ConsumerRecord) -> None:
        try:
            payload: dict[str, Any] = record.value
            event_id: str = payload.get("event_id", "")

            # ── Idempotency check ──────────────────────────────────────────────
            if self._idempotency_checker and event_id:
                already_processed = await self._idempotency_checker(event_id)
                if already_processed:
                    logger.info(
                        "Skipping duplicate event",
                        event_id=event_id,
                        topic=record.topic,
                    )
                    await self._consumer.commit()
                    return

            # ── Process ───────────────────────────────────────────────────────
            await self._handler(payload)

            # ── Commit offset AFTER successful processing ──────────────────────
            await self._consumer.commit()

        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Error processing Kafka record",
                topic=record.topic,
                partition=record.partition,
                offset=record.offset,
                error=str(exc),
                exc_info=True,
            )
            # Do NOT commit — the record will be redelivered
            await asyncio.sleep(1)  # brief back-pressure pause

    async def __aenter__(self) -> "AegisConsumer":
        await self.start()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.stop()
