"""Generic web scraper using Stagehand/Browserbase.

Use this for sources that don't have a JSON API (forums, GitHub, Discourse, etc.).
"""

import hashlib
import logging
from datetime import datetime

from stagehand import AsyncStagehand

from models import Signal, ScrapeConfig
from scrapers.base import BaseScraper

logger = logging.getLogger(__name__)


class WebScraper(BaseScraper):
    """Generic web scraper using Stagehand browser automation.

    This scraper uses Browserbase to control a real browser, enabling
    scraping of JavaScript-heavy sites and handling of complex interactions.
    """

    def __init__(self, source_name: str = "web"):
        self._source_name = source_name

    @property
    def source_name(self) -> str:
        return self._source_name

    async def scrape_url(
        self,
        url: str,
        extraction_instruction: str,
        max_items: int = 20,
    ) -> list[Signal]:
        """Scrape complaints from any URL using AI-powered extraction.

        Args:
            url: The URL to scrape.
            extraction_instruction: Natural language instruction for what to extract.
            max_items: Maximum number of items to extract.

        Returns:
            List of normalized Signal objects.
        """
        logger.info("Starting web scrape of %s", url)

        async with AsyncStagehand() as client:
            logger.debug("Stagehand client created, starting session...")
            session = await client.sessions.start(model_name="openai/gpt-4o-mini")
            logger.info("Session started: %s", session.id)

            # Log the Browserbase live view URL for debugging
            live_url = f"https://www.browserbase.com/sessions/{session.id}"
            logger.info("🔗 Live view: %s", live_url)

            try:
                logger.info("Navigating to %s", url)
                await session.navigate(url=url)
                logger.debug("Navigation complete")

                # Try to dismiss any popups
                logger.debug("Checking for popups to dismiss...")
                try:
                    await session.act(
                        input="If there are any cookie consent banners, popups, or overlay dialogs visible, close or dismiss them. If nothing is blocking the page, do nothing."
                    )
                except Exception as e:
                    logger.debug("No popups to dismiss or error: %s", e)

                # Extract using the provided instruction
                logger.info("Extracting content from page...")
                extract_response = await session.extract(
                    instruction=f"""
                    {extraction_instruction}
                    
                    Extract up to {max_items} items. For each item, extract:
                    - title: the main title or heading
                    - body: the content/description text
                    - author: who posted it (if available)
                    - url: link to the item (if available)
                    - timestamp: when it was posted (if available)
                    """,
                    schema={
                        "type": "object",
                        "properties": {
                            "items": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "title": {"type": "string"},
                                        "body": {"type": "string"},
                                        "author": {"type": "string"},
                                        "url": {"type": "string"},
                                        "timestamp": {"type": "string"},
                                    },
                                    "required": ["title"],
                                },
                            }
                        },
                        "required": ["items"],
                    },
                )

                logger.info("Extract response: %s", extract_response.data)

                items = extract_response.data.result.get("items", [])
                logger.info("Extracted %d items from page", len(items))

                return self._normalize_items(items, url, max_items)

            finally:
                logger.debug("Ending session...")
                await session.end()
                logger.info("Session ended")

    async def scrape(self, config: ScrapeConfig) -> list[Signal]:
        """Not implemented - use scrape_url() directly for generic web scraping."""
        raise NotImplementedError(
            "WebScraper.scrape() is not implemented. Use scrape_url() instead, "
            "or use a source-specific scraper like RedditScraper."
        )

    def _normalize_items(
        self, items: list[dict], base_url: str, max_items: int
    ) -> list[Signal]:
        """Convert extracted items to normalized Signal objects."""
        signals = []

        for item in items[:max_items]:
            title = item.get("title", "")
            body = item.get("body", "")
            url = item.get("url", base_url)

            text = f"{title}\n\n{body}".strip() if body else title
            post_id = self._generate_id(url + title)

            signals.append(
                Signal(
                    id=post_id,
                    text=text,
                    source=self.source_name,
                    url=url if url.startswith("http") else base_url,
                    timestamp=datetime.now(),  # Could parse item.get("timestamp")
                    title=title,
                    author=item.get("author"),
                )
            )

        return signals

    def _generate_id(self, content: str) -> str:
        """Generate a stable ID from content."""
        return hashlib.sha256(content.encode()).hexdigest()[:16]
