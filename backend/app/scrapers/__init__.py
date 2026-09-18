"""Pluggable collectors for public reviews, posts, comments and articles."""

from app.scrapers.base import BaseScraper
from app.scrapers.models import ScrapedItem
from app.scrapers.registry import ScraperRegistry

__all__ = ["BaseScraper", "ScrapedItem", "ScraperRegistry"]
