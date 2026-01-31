"""Background worker for classifying topics."""

import asyncio
import logging
import os

import redis.asyncio as redis

from classify import TopicClassifier
from ingest.cluster import get_topic, TOPIC_PREFIX
from llm import get_llm
from tasks.storage import (
    create_task,
    pop_classify_queue,
    get_classify_queue_length,
)

logger = logging.getLogger(__name__)

# Worker configuration
POLL_INTERVAL = float(os.getenv("CLASSIFY_WORKER_POLL_INTERVAL", "2.0"))
BATCH_SIZE = int(os.getenv("CLASSIFY_WORKER_BATCH_SIZE", "5"))


class ClassifyWorker:
    """Background worker that classifies topics into actionable tasks.

    This worker:
    1. Pops topic IDs from queue:to-classify
    2. Fetches the topic data from Redis
    3. Uses LLM to classify the topic
    4. Creates a task if the topic is actionable
    5. Updates the topic with its category
    """

    def __init__(
        self,
        redis_client: redis.Redis,
        classifier: TopicClassifier | None = None,
    ):
        """Initialize the classify worker.

        Args:
            redis_client: Redis client instance.
            classifier: TopicClassifier to use. Creates one if not provided.
        """
        self.redis = redis_client

        if classifier:
            self.classifier = classifier
        else:
            llm = get_llm(os.getenv("LLM_PROVIDER", "openai"))
            self.classifier = TopicClassifier(llm)

        self._running = False
        self._task: asyncio.Task | None = None

    async def process_one(self) -> bool:
        """Process a single topic from the queue.

        Returns:
            True if a topic was processed, False if queue was empty.
        """
        # Pop from queue
        topic_id = await pop_classify_queue(self.redis)
        if not topic_id:
            return False

        logger.debug("Classifying topic: %s", topic_id)

        # Get topic data
        topic_data = await get_topic(self.redis, topic_id)
        if not topic_data:
            logger.warning("Topic not found in Redis: %s", topic_id)
            return True

        title = topic_data.get("title", "")
        if not title:
            logger.warning("Topic has no title: %s", topic_id)
            return True

        # Get signals for this topic (for now, just use the title)
        # TODO: Fetch actual signals linked to this topic
        signals = [title]

        # Classify the topic
        try:
            result = await self.classifier.classify(title, signals)
        except Exception as e:
            logger.error("Failed to classify topic %s: %s", topic_id, e)
            return True

        # Update topic with category
        topic_key = f"{TOPIC_PREFIX}{topic_id}"
        await self.redis.hset(topic_key, "category", result.category)

        # Create task if actionable
        if result.is_actionable:
            task_id = await create_task(self.redis, topic_id, result)
            logger.info(
                "Created task %s for topic %s (category: %s, severity: %s)",
                task_id,
                topic_id,
                result.category,
                result.severity,
            )
        else:
            logger.info(
                "Topic %s classified as %s (not actionable)",
                topic_id,
                result.category,
            )

        return True

    async def process_batch(self, batch_size: int = BATCH_SIZE) -> int:
        """Process a batch of topics.

        Args:
            batch_size: Maximum topics to process in this batch.

        Returns:
            Number of topics processed.
        """
        processed = 0
        for _ in range(batch_size):
            if await self.process_one():
                processed += 1
            else:
                break
        return processed

    async def run(self) -> None:
        """Run the worker loop."""
        self._running = True
        logger.info("Classify worker started")

        while self._running:
            try:
                queue_len = await get_classify_queue_length(self.redis)
                if queue_len > 0:
                    logger.debug("Classification queue length: %d", queue_len)
                    processed = await self.process_batch()
                    if processed > 0:
                        logger.info("Classified %d topics", processed)
                else:
                    await asyncio.sleep(POLL_INTERVAL)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception("Error in classify worker: %s", e)
                await asyncio.sleep(POLL_INTERVAL)

        logger.info("Classify worker stopped")

    def start(self) -> asyncio.Task:
        """Start the worker as a background task.

        Returns:
            The asyncio Task running the worker.
        """
        self._task = asyncio.create_task(self.run())
        return self._task

    async def stop(self) -> None:
        """Stop the worker."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

