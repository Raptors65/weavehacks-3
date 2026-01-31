"""FastAPI application for the browser agent."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

# Load environment variables from .env file
load_dotenv(Path(__file__).parent / ".env")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

from ingest.cluster import get_topic, list_topics
from ingest.service import BatchIngestResult, IngestService
from models import Signal, ScrapeConfig
from tasks import get_task, list_tasks, update_task_status
from redis_setup import (
    close_redis,
    get_redis,
    health_check as redis_health_check,
    init_redis,
)
from scrapers import RedditScraper, WebScraper
from workers import ClassifyWorker, EmbedWorker

# Global worker references
_embed_worker: EmbedWorker | None = None
_classify_worker: ClassifyWorker | None = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Application lifespan for startup/shutdown."""
    global _embed_worker, _classify_worker  # noqa: PLW0603

    # Startup
    logger.info("Starting up...")

    # Initialize Redis
    redis_client = await init_redis()
    logger.info("Redis initialized")

    # Start embed worker
    _embed_worker = EmbedWorker(redis_client)
    _embed_worker.start()
    logger.info("Embed worker started")

    # Start classify worker
    _classify_worker = ClassifyWorker(redis_client)
    _classify_worker.start()
    logger.info("Classify worker started")

    yield

    # Shutdown
    logger.info("Shutting down...")

    if _classify_worker:
        await _classify_worker.stop()
        logger.info("Classify worker stopped")

    if _embed_worker:
        await _embed_worker.stop()
        logger.info("Embed worker stopped")

    await close_redis()
    logger.info("Redis connection closed")


app = FastAPI(
    title="Browser Agent API",
    description="Scrape user signals from various sources and cluster into issues",
    version="0.1.0",
    lifespan=lifespan,
)


class WebScrapeConfig(BaseModel):
    """Configuration for generic web scraping via Browserbase."""

    url: str = Field(description="URL to scrape")
    instruction: str = Field(
        description="Natural language instruction for what to extract"
    )
    source_name: str = Field(
        default="web", description="Name to use for the source field"
    )
    max_items: int = Field(default=20, ge=1, le=100)


class TopicResponse(BaseModel):
    """Response model for topics."""

    id: str
    title: str
    summary: str
    status: str
    signal_count: int
    created_at: int
    updated_at: int


# Health endpoints


@app.get("/health")
async def health_check() -> dict:
    """Health check endpoint."""
    redis_status = await redis_health_check()
    return {
        "status": "ok" if redis_status["status"] == "healthy" else "degraded",
        "redis": redis_status,
    }


# Scrape endpoints


@app.post("/scrape", response_model=list[Signal])
async def scrape_signals(config: ScrapeConfig) -> list[Signal]:
    """Scrape signals from a source based on configuration.

    Args:
        config: Scrape configuration specifying product, source, and limits.

    Returns:
        List of normalized Signal objects.
    """
    logger.info(
        "Received scrape request: product=%s, subreddit=%s, max_posts=%d",
        config.product_name,
        config.subreddit,
        config.max_posts,
    )
    try:
        scraper = RedditScraper()
        signals = await scraper.scrape(config)
        logger.info("Scrape completed successfully, returning %d signals", len(signals))
        return signals
    except Exception as e:
        logger.exception("Failed to scrape signals: %s", e)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to scrape signals: {str(e)}",
        ) from e


@app.post("/scrape/web", response_model=list[Signal])
async def scrape_web(config: WebScrapeConfig) -> list[Signal]:
    """Scrape signals from any URL using Browserbase/Stagehand.

    This endpoint uses AI-powered browser automation to extract content
    from any webpage. Use this for sites without APIs (forums, GitHub, etc.).

    Args:
        config: Web scrape configuration with URL and extraction instruction.

    Returns:
        List of normalized Signal objects.
    """
    logger.info(
        "Received web scrape request: url=%s, source=%s",
        config.url,
        config.source_name,
    )
    try:
        scraper = WebScraper(source_name=config.source_name)
        signals = await scraper.scrape_url(
            url=config.url,
            extraction_instruction=config.instruction,
            max_items=config.max_items,
        )
        logger.info(
            "Web scrape completed successfully, returning %d signals",
            len(signals),
        )
        return signals
    except Exception as e:
        logger.exception("Failed to scrape web page: %s", e)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to scrape web page: {str(e)}",
        ) from e


# Ingest endpoints


@app.post("/ingest")
async def ingest_signals(signals: list[Signal]) -> BatchIngestResult:
    """Ingest signals into the pipeline.

    Performs deduplication and queues new signals for embedding.

    Args:
        signals: List of signals to ingest.

    Returns:
        BatchIngestResult with stats on processed signals.
    """
    logger.info("Received ingest request with %d signals", len(signals))

    try:
        redis_client = await get_redis()
        service = IngestService(redis_client)
        result = await service.ingest_batch(signals)
        return result
    except Exception as e:
        logger.exception("Failed to ingest signals: %s", e)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to ingest signals: {str(e)}",
        ) from e


# Topic endpoints


@app.get("/topics")
async def get_topics(limit: int = 50) -> list[dict]:
    """Get all topics sorted by signal count.

    Args:
        limit: Maximum number of topics to return.

    Returns:
        List of topics with their metadata.
    """
    try:
        redis_client = await get_redis()
        topics = await list_topics(redis_client, limit=limit)
        return topics
    except Exception as e:
        logger.exception("Failed to get topics: %s", e)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get topics: {str(e)}",
        ) from e


@app.get("/topics/{topic_id}")
async def get_topic_by_id(topic_id: str) -> dict:
    """Get a specific topic by ID.

    Args:
        topic_id: The topic ID.

    Returns:
        Topic metadata.
    """
    try:
        redis_client = await get_redis()
        topic = await get_topic(redis_client, topic_id)
        if not topic:
            raise HTTPException(status_code=404, detail="Topic not found")
        topic["id"] = topic_id
        return topic
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to get topic: %s", e)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get topic: {str(e)}",
        ) from e


# Task endpoints


@app.get("/tasks")
async def get_tasks(
    limit: int = 50,
    status: str | None = None,
    category: str | None = None,
) -> list[dict]:
    """Get all tasks (actionable topics).

    Args:
        limit: Maximum number of tasks to return.
        status: Filter by status (open, in_progress, done).
        category: Filter by category (BUG, FEATURE, UX).

    Returns:
        List of tasks with their metadata.
    """
    try:
        redis_client = await get_redis()
        tasks = await list_tasks(
            redis_client,
            status=status,
            category=category,
            limit=limit,
        )
        return tasks
    except Exception as e:
        logger.exception("Failed to get tasks: %s", e)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get tasks: {str(e)}",
        ) from e


@app.get("/tasks/{task_id}")
async def get_task_by_id(task_id: str) -> dict:
    """Get a specific task by ID.

    Args:
        task_id: The task ID.

    Returns:
        Task metadata.
    """
    try:
        redis_client = await get_redis()
        task = await get_task(redis_client, task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        return task
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to get task: %s", e)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get task: {str(e)}",
        ) from e


class TaskStatusUpdate(BaseModel):
    """Request to update task status."""

    status: str = Field(..., description="New status (open, in_progress, done)")


@app.patch("/tasks/{task_id}")
async def update_task(task_id: str, update: TaskStatusUpdate) -> dict:
    """Update a task's status.

    Args:
        task_id: The task ID.
        update: The status update.

    Returns:
        Updated task metadata.
    """
    valid_statuses = ("open", "in_progress", "done")
    if update.status not in valid_statuses:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Must be one of: {valid_statuses}",
        )

    try:
        redis_client = await get_redis()
        updated = await update_task_status(redis_client, task_id, update.status)
        if not updated:
            raise HTTPException(status_code=404, detail="Task not found")

        task = await get_task(redis_client, task_id)
        return task
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to update task: %s", e)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update task: {str(e)}",
        ) from e


def run_server() -> None:
    """Run the FastAPI server with uvicorn."""
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    run_server()
