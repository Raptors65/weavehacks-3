"""Task storage in Redis."""

import logging
import time
import uuid

import redis.asyncio as redis

from classify.classifier import ClassificationResult

logger = logging.getLogger(__name__)

# Redis key prefixes
TASK_PREFIX = "task:"
CLASSIFY_QUEUE = "queue:to-classify"

# Fields to fetch for task metadata
TASK_FIELDS = [
    "topic_id",
    "category",
    "summary",
    "severity",
    "suggested_action",
    "confidence",
    "status",
    "created_at",
    "updated_at",
]


def _convert_task_types(data: dict) -> dict:
    """Convert string values to proper types for task data."""
    if data.get("confidence"):
        try:
            data["confidence"] = float(data["confidence"])
        except (ValueError, TypeError):
            data["confidence"] = 0.0
    if data.get("created_at"):
        data["created_at"] = int(data["created_at"])
    if data.get("updated_at"):
        data["updated_at"] = int(data["updated_at"])
    return data


async def create_task(
    client: redis.Redis,
    topic_id: str,
    classification: ClassificationResult,
) -> str:
    """Create a new task from a classification result.

    Args:
        client: Redis client.
        topic_id: The topic ID this task is for.
        classification: The classification result.

    Returns:
        The new task ID.
    """
    task_id = str(uuid.uuid4())[:8]
    task_key = f"{TASK_PREFIX}{task_id}"

    now = int(time.time())

    await client.hset(
        task_key,
        mapping={
            "topic_id": topic_id,
            "category": classification.category,
            "summary": classification.summary,
            "severity": classification.severity or "",
            "suggested_action": classification.suggested_action,
            "confidence": str(classification.confidence),
            "status": "open",
            "created_at": now,
            "updated_at": now,
        },
    )

    logger.info(
        "Created task %s for topic %s (category: %s)",
        task_id,
        topic_id,
        classification.category,
    )

    return task_id


async def get_task(client: redis.Redis, task_id: str) -> dict | None:
    """Get a task by ID.

    Args:
        client: Redis client.
        task_id: The task ID.

    Returns:
        Task data dict or None if not found.
    """
    key = f"{TASK_PREFIX}{task_id}"
    values = await client.hmget(key, TASK_FIELDS)

    if not any(values):
        return None

    data = dict(zip(TASK_FIELDS, values))
    data["id"] = task_id
    return _convert_task_types(data)


async def list_tasks(
    client: redis.Redis,
    status: str | None = None,
    category: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """List tasks, optionally filtered by status or category.

    Args:
        client: Redis client.
        status: Filter by status (open, in_progress, done).
        category: Filter by category (BUG, FEATURE, UX).
        limit: Maximum number of tasks to return.

    Returns:
        List of task dicts.
    """
    tasks = []

    async for key in client.scan_iter(match=f"{TASK_PREFIX}*"):
        values = await client.hmget(key, TASK_FIELDS)
        if any(values):
            task_id = key.replace(TASK_PREFIX, "")
            data = dict(zip(TASK_FIELDS, values))
            data["id"] = task_id
            data = _convert_task_types(data)

            # Apply filters
            if status and data.get("status") != status:
                continue
            if category and data.get("category") != category:
                continue

            tasks.append(data)

    # Sort by created_at descending
    tasks.sort(key=lambda x: x.get("created_at") or 0, reverse=True)

    return tasks[:limit]


async def update_task_status(
    client: redis.Redis,
    task_id: str,
    status: str,
) -> bool:
    """Update a task's status.

    Args:
        client: Redis client.
        task_id: The task ID.
        status: New status (open, in_progress, done).

    Returns:
        True if updated, False if task not found.
    """
    key = f"{TASK_PREFIX}{task_id}"

    if not await client.exists(key):
        return False

    await client.hset(
        key,
        mapping={
            "status": status,
            "updated_at": int(time.time()),
        },
    )

    logger.info("Updated task %s status to %s", task_id, status)
    return True


async def push_to_classify_queue(client: redis.Redis, topic_id: str) -> None:
    """Push a topic ID to the classification queue.

    Args:
        client: Redis client.
        topic_id: The topic ID to classify.
    """
    await client.rpush(CLASSIFY_QUEUE, topic_id)
    logger.debug("Pushed topic %s to classification queue", topic_id)


async def pop_classify_queue(client: redis.Redis) -> str | None:
    """Pop a topic ID from the classification queue.

    Args:
        client: Redis client.

    Returns:
        Topic ID or None if queue is empty.
    """
    return await client.lpop(CLASSIFY_QUEUE)


async def get_classify_queue_length(client: redis.Redis) -> int:
    """Get the length of the classification queue.

    Args:
        client: Redis client.

    Returns:
        Queue length.
    """
    return await client.llen(CLASSIFY_QUEUE)

