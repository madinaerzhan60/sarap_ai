from __future__ import annotations

from collections.abc import Callable

from app.scrapers.base import BaseScraper


class ScraperRegistry:
    def __init__(self) -> None:
        self._factories: dict[str, Callable[[], BaseScraper]] = {}

    def register(self, name: str, factory: Callable[[], BaseScraper]) -> None:
        key = name.casefold().strip()
        if key in self._factories:
            raise ValueError(f"Scraper already registered: {name}")
        self._factories[key] = factory

    def create(self, name: str) -> BaseScraper:
        try:
            return self._factories[name.casefold().strip()]()
        except KeyError as exc:
            raise KeyError(f"Unknown scraper {name}; available: {', '.join(sorted(self._factories))}") from exc

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._factories))
