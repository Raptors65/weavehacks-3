"""Pydantic models for the browser agent."""

from datetime import datetime

from pydantic import BaseModel, Field


class ScrapeConfig(BaseModel):
    """Configuration for a scrape job."""

    product_name: str = Field(
        description="Name of the product to search for complaints about"
    )
    subreddit: str = Field(description="Subreddit to scrape (without r/ prefix)")
    max_posts: int = Field(
        default=20,
        ge=1,
        le=100,
        description="Maximum number of posts to scrape",
    )
    sort_by: str = Field(
        default="new",
        description="How to sort posts: 'new', 'hot', 'top'",
    )


class Signal(BaseModel):
    """A normalized signal (post/comment) extracted from a source.

    Signals are raw scraped data that will be deduplicated, embedded,
    and clustered into Issues downstream.
    """

    id: str = Field(description="Unique identifier for this signal")
    text: str = Field(description="The signal text content")
    source: str = Field(description="Source platform (e.g., 'reddit')")
    url: str = Field(description="URL to the original post")
    timestamp: datetime = Field(description="When the signal was posted")
    title: str | None = Field(default=None, description="Post title if available")
    author: str | None = Field(default=None, description="Author username if available")
