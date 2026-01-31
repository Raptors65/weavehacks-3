"""Clustering logic using Redis vector search."""

import base64
import logging
import os
import struct
import time
import uuid
from dataclasses import dataclass

import numpy as np
import redis.asyncio as redis
from redis.commands.search.query import Query

from ingest.dedupe import update_signal_topic
from redis_setup import TOPICS_INDEX
from tasks.storage import push_to_classify_queue

logger = logging.getLogger(__name__)

# Redis key prefixes
TOPIC_PREFIX = "topic:"
TOPIC_EMB_PREFIX = "topic:emb:"
TRIAGE_QUEUE = "queue:triage"

# Clustering thresholds (configurable via environment)
THRESHOLD_HIGH = float(os.getenv("CLUSTER_THRESHOLD_HIGH", "0.75"))
THRESHOLD_LOW = float(os.getenv("CLUSTER_THRESHOLD_LOW", "0.60"))


@dataclass
class ClusterResult:
    """Result of clustering a signal."""

    topic_id: str
    action: str  # "attached", "created", "triage"
    similarity: float | None


def embedding_to_bytes(embedding: list[float]) -> bytes:
    """Convert embedding list to bytes for Redis vector search.

    Args:
        embedding: List of floats.

    Returns:
        Packed bytes.
    """
    return struct.pack(f"{len(embedding)}f", *embedding)


def embedding_to_base64(embedding: list[float]) -> str:
    """Convert embedding list to base64 string for Redis hash storage.

    Args:
        embedding: List of floats.

    Returns:
        Base64-encoded string.
    """
    raw_bytes = struct.pack(f"{len(embedding)}f", *embedding)
    return base64.b64encode(raw_bytes).decode("ascii")


def base64_to_embedding(data: str, dimension: int) -> list[float]:
    """Convert base64 string back to embedding list.

    Args:
        data: Base64-encoded string.
        dimension: Expected dimension.

    Returns:
        List of floats.
    """
    raw_bytes = base64.b64decode(data)
    return list(struct.unpack(f"{dimension}f", raw_bytes))


def bytes_to_embedding(data: bytes, dimension: int) -> list[float]:
    """Convert bytes back to embedding list.

    Args:
        data: Packed bytes.
        dimension: Expected dimension.

    Returns:
        List of floats.
    """
    return list(struct.unpack(f"{dimension}f", data))


async def find_similar_topics(
    client: redis.Redis,
    embedding: list[float],
    k: int = 5,
) -> list[tuple[str, float]]:
    """Find the most similar topics using KNN search.

    Args:
        client: Redis client.
        embedding: The query embedding vector.
        k: Number of nearest neighbors to find.

    Returns:
        List of (topic_id, similarity_score) tuples, sorted by similarity descending.
    """
    vec_bytes = embedding_to_bytes(embedding)

    query = (
        Query(f"*=>[KNN {k} @embedding $vec AS score]")
        .sort_by("score")
        .return_fields("score")
        .dialect(2)
    )

    try:
        results = await client.ft(TOPICS_INDEX).search(
            query,
            query_params={"vec": vec_bytes},
        )

        matches = []
        for doc in results.docs:
            # Extract topic_id from key (format: "topic:{id}")
            topic_id = doc.id.replace(TOPIC_PREFIX, "")
            # Convert distance to similarity (cosine distance to similarity)
            # Redis returns distance, we want similarity = 1 - distance
            distance = float(doc.score)
            similarity = 1 - distance
            matches.append((topic_id, similarity))

        return matches

    except redis.ResponseError as e:
        # Index might be empty
        logger.debug("KNN search failed (index may be empty): %s", e)
        return []


async def cluster_signal(
    client: redis.Redis,
    signal_hash: str,
    signal_text: str,
    embedding: list[float],
) -> ClusterResult:
    """Cluster a signal into an existing or new topic.

    Args:
        client: Redis client.
        signal_hash: The signal hash.
        signal_text: The signal text (for new topic title).
        embedding: The signal's embedding vector.

    Returns:
        ClusterResult with the action taken.
    """
    # Find similar topics
    matches = await find_similar_topics(client, embedding)

    if matches:
        best_id, best_similarity = matches[0]
        logger.debug(
            "Best match for signal %s: topic %s (similarity: %.3f)",
            signal_hash[:16],
            best_id,
            best_similarity,
        )

        if best_similarity >= THRESHOLD_HIGH:
            # High confidence match - attach to topic
            await attach_signal_to_topic(client, signal_hash, best_id, embedding)
            return ClusterResult(
                topic_id=best_id,
                action="attached",
                similarity=best_similarity,
            )
        elif best_similarity >= THRESHOLD_LOW:
            # Low confidence - add to triage queue
            await client.rpush(TRIAGE_QUEUE, f"{signal_hash}:{best_id}")
            await update_signal_topic(client, signal_hash, best_id)
            logger.info(
                "Signal %s added to triage queue (similarity: %.3f)",
                signal_hash[:16],
                best_similarity,
            )
            return ClusterResult(
                topic_id=best_id,
                action="triage",
                similarity=best_similarity,
            )

    # No match or low similarity - create new topic
    topic_id = await create_topic(client, signal_hash, signal_text, embedding)
    return ClusterResult(
        topic_id=topic_id,
        action="created",
        similarity=None,
    )


async def attach_signal_to_topic(
    client: redis.Redis,
    signal_hash: str,
    topic_id: str,
    embedding: list[float],
) -> None:
    """Attach a signal to an existing topic and update centroid.

    Args:
        client: Redis client.
        signal_hash: The signal hash.
        topic_id: The topic ID to attach to.
        embedding: The signal's embedding vector.
    """
    topic_key = f"{TOPIC_PREFIX}{topic_id}"

    # Get current signal count
    signal_count_str = await client.hget(topic_key, "signal_count")
    signal_count = int(signal_count_str) if signal_count_str else 1

    # Get current embedding (stored as base64)
    current_emb_b64 = await client.hget(topic_key, "embedding_b64")
    if current_emb_b64:
        current_emb = base64_to_embedding(current_emb_b64, len(embedding))

        # Update centroid incrementally:
        # new_centroid = (old_centroid * count + new_vec) / (count + 1)
        current_arr = np.array(current_emb)
        new_arr = np.array(embedding)
        updated_arr = (current_arr * signal_count + new_arr) / (signal_count + 1)
        updated_emb = updated_arr.tolist()

        # Store updated embedding (base64 for retrieval, bytes for vector search)
        await client.hset(
            topic_key,
            mapping={
                "embedding": embedding_to_bytes(updated_emb),
                "embedding_b64": embedding_to_base64(updated_emb),
            },
        )

    # Update signal count and timestamp
    await client.hset(
        topic_key,
        mapping={
            "signal_count": signal_count + 1,
            "updated_at": int(time.time()),
        },
    )

    # Update signal's topic_id
    await update_signal_topic(client, signal_hash, topic_id)

    logger.info(
        "Attached signal %s to topic %s (now %d signals)",
        signal_hash[:16],
        topic_id,
        signal_count + 1,
    )


async def create_topic(
    client: redis.Redis,
    signal_hash: str,
    signal_text: str,
    embedding: list[float],
) -> str:
    """Create a new topic from a signal.

    Args:
        client: Redis client.
        signal_hash: The signal hash.
        signal_text: The signal text (used for title).
        embedding: The signal's embedding vector.

    Returns:
        The new topic ID.
    """
    topic_id = str(uuid.uuid4())[:8]
    topic_key = f"{TOPIC_PREFIX}{topic_id}"

    now = int(time.time())

    # Create a title from the signal text (truncate if too long)
    title = signal_text[:100] + "..." if len(signal_text) > 100 else signal_text

    # Store topic metadata with embedding for vector search
    # embedding: raw bytes for RediSearch vector index
    # embedding_b64: base64 for Python retrieval (decode_responses=True)
    await client.hset(
        topic_key,
        mapping={
            "title": title,
            "summary": "",
            "status": "open",
            "signal_count": 1,
            "created_at": now,
            "updated_at": now,
            "embedding": embedding_to_bytes(embedding),
            "embedding_b64": embedding_to_base64(embedding),
        },
    )

    # Update signal's topic_id
    await update_signal_topic(client, signal_hash, topic_id)

    # Queue topic for classification
    await push_to_classify_queue(client, topic_id)

    logger.info("Created new topic %s from signal %s", topic_id, signal_hash[:16])
    return topic_id


# Fields to fetch for topic metadata (excludes binary embedding)
TOPIC_FIELDS = [
    "title",
    "summary",
    "status",
    "signal_count",
    "created_at",
    "updated_at",
]


def _convert_topic_types(data: dict) -> dict:
    """Convert string values to proper types for topic data."""
    if data.get("signal_count"):
        data["signal_count"] = int(data["signal_count"])
    if data.get("created_at"):
        data["created_at"] = int(data["created_at"])
    if data.get("updated_at"):
        data["updated_at"] = int(data["updated_at"])
    return data


async def get_topic(client: redis.Redis, topic_id: str) -> dict | None:
    """Get a topic by ID.

    Args:
        client: Redis client.
        topic_id: The topic ID.

    Returns:
        Topic data dict or None if not found.
    """
    key = f"{TOPIC_PREFIX}{topic_id}"

    # Fetch specific fields to avoid binary embedding
    values = await client.hmget(key, TOPIC_FIELDS)
    if not any(values):
        return None

    data = dict(zip(TOPIC_FIELDS, values))
    return _convert_topic_types(data)


async def list_topics(
    client: redis.Redis,
    limit: int = 50,
) -> list[dict]:
    """List all topics sorted by signal count.

    Args:
        client: Redis client.
        limit: Maximum number of topics to return.

    Returns:
        List of topic dicts.
    """
    # Scan for topic keys
    topics = []
    async for key in client.scan_iter(match=f"{TOPIC_PREFIX}*"):
        # Skip embedding keys
        if key.startswith(TOPIC_EMB_PREFIX):
            continue

        # Fetch specific fields to avoid binary embedding
        values = await client.hmget(key, TOPIC_FIELDS)
        if any(values):
            topic_id = key.replace(TOPIC_PREFIX, "")
            data = dict(zip(TOPIC_FIELDS, values))
            data["id"] = topic_id
            topics.append(_convert_topic_types(data))

    # Sort by signal_count descending
    topics.sort(key=lambda x: x.get("signal_count") or 0, reverse=True)

    return topics[:limit]
