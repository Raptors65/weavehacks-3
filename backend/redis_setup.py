"""Redis connection and index setup."""

import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import redis.asyncio as redis
from redis.commands.search.field import TagField, TextField, VectorField
from redis.commands.search.index_definition import IndexDefinition, IndexType

logger = logging.getLogger(__name__)

# Default Redis URL
DEFAULT_REDIS_URL = "redis://localhost:6379"

# Index names
TOPICS_INDEX = "idx:topics"
SUCCESSFUL_FIXES_INDEX = "idx:successful_fixes"

# Global Redis client (set during app startup)
_redis_client: redis.Redis | None = None


def get_redis_url() -> str:
    """Get Redis URL from environment."""
    return os.getenv("REDIS_URL", DEFAULT_REDIS_URL)


async def create_redis_client() -> redis.Redis:
    """Create and return a Redis client."""
    url = get_redis_url()
    logger.info("Connecting to Redis at %s", url)
    client = redis.from_url(url, decode_responses=True)
    await client.ping()
    logger.info("Redis connection established")
    return client


async def get_redis() -> redis.Redis:
    """Get the global Redis client.

    Raises:
        RuntimeError: If Redis is not initialized.
    """
    if _redis_client is None:
        raise RuntimeError("Redis not initialized. Call init_redis() first.")
    return _redis_client


async def init_redis() -> redis.Redis:
    """Initialize the global Redis client and create indexes."""
    global _redis_client
    _redis_client = await create_redis_client()
    await ensure_indexes(_redis_client)
    return _redis_client


async def close_redis() -> None:
    """Close the Redis connection."""
    global _redis_client
    if _redis_client:
        await _redis_client.close()
        _redis_client = None
        logger.info("Redis connection closed")


async def ensure_indexes(client: redis.Redis, dimension: int = 384) -> None:
    """Ensure required Redis indexes exist.

    Args:
        client: Redis client.
        dimension: Embedding vector dimension (384 for all-MiniLM-L6-v2).
    """
    try:
        # Check if index exists
        await client.ft(TOPICS_INDEX).info()
        logger.info("Index %s already exists", TOPICS_INDEX)
    except redis.ResponseError:
        # Create the index
        logger.info("Creating index %s with dimension %d", TOPICS_INDEX, dimension)

        schema = (
            TextField("title"),
            TextField("summary"),
            TagField("status"),
            VectorField(
                "embedding",
                "FLAT",
                {
                    "TYPE": "FLOAT32",
                    "DIM": dimension,
                    "DISTANCE_METRIC": "COSINE",
                },
            ),
        )

        definition = IndexDefinition(prefix=["topic:"], index_type=IndexType.HASH)

        await client.ft(TOPICS_INDEX).create_index(schema, definition=definition)
        logger.info("Index %s created successfully", TOPICS_INDEX)

    # Ensure successful fixes index exists (for self-improvement)
    try:
        await client.ft(SUCCESSFUL_FIXES_INDEX).info()
        logger.info("Index %s already exists", SUCCESSFUL_FIXES_INDEX)
    except redis.ResponseError:
        logger.info("Creating index %s for successful fixes", SUCCESSFUL_FIXES_INDEX)

        fixes_schema = (
            TagField("category"),
            TextField("title"),
            TextField("summary"),
            TagField("product"),
            VectorField(
                "embedding",
                "FLAT",
                {
                    "TYPE": "FLOAT32",
                    "DIM": dimension,
                    "DISTANCE_METRIC": "COSINE",
                },
            ),
        )

        fixes_definition = IndexDefinition(
            prefix=["fix:success:"], index_type=IndexType.HASH
        )

        await client.ft(SUCCESSFUL_FIXES_INDEX).create_index(
            fixes_schema, definition=fixes_definition
        )
        logger.info("Index %s created successfully", SUCCESSFUL_FIXES_INDEX)


async def health_check() -> dict:
    """Check Redis health.

    Returns:
        Health status dict.
    """
    try:
        client = await get_redis()
        await client.ping()
        info = await client.info("server")
        return {
            "status": "healthy",
            "redis_version": info.get("redis_version"),
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e),
        }


@asynccontextmanager
async def redis_lifespan() -> AsyncGenerator[redis.Redis, None]:
    """Context manager for Redis lifecycle."""
    client = await init_redis()
    try:
        yield client
    finally:
        await close_redis()
