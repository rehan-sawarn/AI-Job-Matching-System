from abc import ABC, abstractmethod
from typing import Any


class BaseScraper(ABC):
    """Abstract base class for all job scrapers."""

    source: str = ""

    @abstractmethod
    def scrape(self) -> list[dict[str, Any]]:
        """
        Scrape job listings.

        Returns:
            A list of job dicts, each containing at minimum:
            title, company, location, url, source, description
        """
        ...
