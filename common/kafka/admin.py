"""
Kafka admin helpers — topic creation on startup.
"""
from __future__ import annotations

import asyncio

from aiokafka.admin import AIOKafkaAdminClient, NewTopic
from aiokafka.errors import TopicAlreadyExistsError

from common.config.settings import get_settings
from common.events.schemas import ALL_TOPICS
from common.logging.logger import get_logger

logger = get_logger(__name__)


async def ensure_topics_exist(
    extra_topics: list[str] | None = None,
    num_partitions: int = 3,
    replication_factor: int = 1,
) -> None:
    """
    Idempotently create all required Aegis Kafka topics.
    Safe to call on every service startup.
    """
    settings = get_settings()
    topics = list(ALL_TOPICS) + (extra_topics or [])

    admin = AIOKafkaAdminClient(
        bootstrap_servers=settings.kafka_bootstrap_servers,
    )

    for attempt in range(1, 6):
        try:
            await admin.start()
            break
        except Exception as exc:
            if attempt == 5:
                raise
            logger.warning(
                "Kafka not ready, retrying",
                attempt=attempt,
                error=str(exc),
            )
            await asyncio.sleep(3 * attempt)

    try:
        new_topics = [
            NewTopic(name=t, num_partitions=num_partitions, replication_factor=replication_factor)
            for t in topics
        ]
        await admin.create_topics(new_topics, validate_only=False)
        logger.info("Kafka topics created/verified", topics=topics)
    except TopicAlreadyExistsError:
        logger.debug("All Kafka topics already exist")
    except Exception as exc:
        logger.warning("Topic creation warning (may already exist)", error=str(exc))
    finally:
        await admin.close()
