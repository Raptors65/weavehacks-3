"""Scrapers for various complaint sources."""

from scrapers.base import BaseScraper
from scrapers.reddit import RedditScraper
from scrapers.web import WebScraper

__all__ = ["BaseScraper", "RedditScraper", "WebScraper"]

