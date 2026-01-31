"""Base scraper protocol for extensibility."""

from abc import ABC, abstractmethod

from models import Signal, ScrapeConfig


class BaseScraper(ABC):
    """Abstract base class for complaint scrapers.

    Implement this to add support for new sources (GitHub, Discourse, etc.).
    """

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Return the source identifier (e.g., 'reddit', 'github')."""

    @abstractmethod
    async def scrape(self, config: ScrapeConfig) -> list[Signal]:
        """Scrape signals based on the provided configuration.

        Args:
            config: Scrape configuration with product name, limits, etc.

        Returns:
            List of normalized Signal objects.
        """
