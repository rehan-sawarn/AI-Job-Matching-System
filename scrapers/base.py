from abc import ABC, abstractmethod
from typing import Any


class BaseScraper(ABC):
    """Abstract base class for all job scrapers."""

    source: str = ""

    @abstractmethod
    def scrape(self, keywords: list[dict[str, str]] | None = None) -> list[dict[str, Any]]:
        """
        Scrape job listings using the provided keywords.

        Args:
            keywords: Optional list of dicts with 'keyword' and 'label'.
                     If None, the scraper should use its internal defaults.

        Returns:
            A list of job dicts.
        """
        ...

    def enrich_jobs(self, jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Optional: Batch enrichment for a list of jobs.
        Useful for scrapers that can reuse a session/browser.
        """
        return [self.enrich_job(j) for j in jobs]

    def enrich_job(self, job: dict[str, Any]) -> dict[str, Any]:
        """
        Optional: Fetch full details for a specific job.
        Default implementation returns the job as-is.
        """
        return job
