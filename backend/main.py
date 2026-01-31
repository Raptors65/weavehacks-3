"""FastAPI application for the browser agent."""

import logging
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException

# Load environment variables from .env file
load_dotenv(Path(__file__).parent / ".env")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

from pydantic import BaseModel, Field

from models import Signal, ScrapeConfig
from scrapers import RedditScraper, WebScraper


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


app = FastAPI(
    title="Browser Agent API",
    description="Scrape user complaints from various sources using Stagehand",
    version="0.1.0",
)


@app.get("/health")
async def health_check() -> dict:
    """Health check endpoint."""
    return {"status": "ok"}


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


def run_server() -> None:
    """Run the FastAPI server with uvicorn."""
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    run_server()
