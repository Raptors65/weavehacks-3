"""Reddit scraper using Reddit's JSON API."""

import hashlib
import logging
from datetime import datetime

import httpx

from models import Signal, ScrapeConfig
from scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

# Reddit requires a custom User-Agent
USER_AGENT = "ComplaintScraper/1.0 (educational project)"


class RedditScraper(BaseScraper):
    """Scraper for Reddit posts using Reddit's public JSON API.

    Reddit provides JSON data by appending .json to any URL.
    This is more reliable than browser scraping and avoids bot detection.
    """

    @property
    def source_name(self) -> str:
        return "reddit"

    async def scrape(self, config: ScrapeConfig) -> list[Signal]:
        """Scrape signals from a subreddit using Reddit's JSON API.

        Args:
            config: Scrape configuration with subreddit and limits.

        Returns:
            List of normalized Signal objects.
        """
        logger.info(
            "Starting Reddit scrape for r/%s (product: %s, max_posts: %d)",
            config.subreddit,
            config.product_name,
            config.max_posts,
        )

        url = f"https://www.reddit.com/r/{config.subreddit}/{config.sort_by}.json"
        params = {"limit": min(config.max_posts, 100)}  # Reddit caps at 100 per request

        logger.info("Fetching %s", url)

        async with httpx.AsyncClient() as client:
            response = await client.get(
                url,
                params=params,
                headers={"User-Agent": USER_AGENT},
                follow_redirects=True,
            )
            response.raise_for_status()
            data = response.json()

        posts = data.get("data", {}).get("children", [])
        logger.info("Fetched %d posts from Reddit API", len(posts))

        if posts:
            logger.debug("Sample post title: %s", posts[0].get("data", {}).get("title"))

        signals = self._normalize_posts(posts, config)
        logger.info("Normalized to %d signals", len(signals))
        return signals

    def _normalize_posts(self, posts: list[dict], config: ScrapeConfig) -> list[Signal]:
        """Convert raw Reddit API posts to normalized Signal objects."""
        signals = []

        for post_wrapper in posts[: config.max_posts]:
            post = post_wrapper.get("data", {})

            title = post.get("title", "")
            body = post.get("selftext", "")  # selftext is the post body
            url = post.get("permalink", "")
            author = post.get("author", "")
            created_utc = post.get("created_utc", 0)

            # Combine title and body for the complaint text
            text = f"{title}\n\n{body}".strip() if body else title

            # Generate a stable ID from the Reddit post ID
            post_id = post.get("id", self._generate_id(url))

            # Convert Unix timestamp to datetime
            timestamp = (
                datetime.fromtimestamp(created_utc) if created_utc else datetime.now()
            )

            signals.append(
                Signal(
                    id=post_id,
                    text=text,
                    source=self.source_name,
                    url=self._ensure_full_url(url),
                    timestamp=timestamp,
                    title=title,
                    author=author if author else None,
                )
            )

        return signals

    def _generate_id(self, url: str) -> str:
        """Generate a stable ID from the post URL."""
        return hashlib.sha256(url.encode()).hexdigest()[:16]

    def _ensure_full_url(self, url: str) -> str:
        """Ensure the URL is a full Reddit URL."""
        if url.startswith("/"):
            return f"https://www.reddit.com{url}"
        if not url.startswith("http"):
            return f"https://www.reddit.com/{url}"
        return url
