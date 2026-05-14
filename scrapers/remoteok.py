"""
RemoteOK scraper using the public JSON API.

RemoteOK exposes a free, no-auth JSON API at https://remoteok.com/api
Useful as an always-working baseline source while Wellfound/Naukri are tuned.
"""

import logging
import time
from typing import Any

import requests

from scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

# Tags to query — RemoteOK supports multiple ?tag= params
TAG_QUERIES: list[list[str]] = [
    ["python", "ai"],
    ["machine-learning"],
    ["backend", "python"],
    ["llm"],
]

API_BASE = "https://remoteok.com/api"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; JobMatcher/1.0; +https://github.com/rehan)",
    "Accept": "application/json",
}


class RemoteOKScraper(BaseScraper):
    source = "remoteok"

    def scrape(self, keywords: list[dict[str, str]] | None = None) -> list[dict[str, Any]]:
        jobs: list[dict[str, Any]] = []
        seen_ids: set[str] = set()

        # Use passed keywords or fall back to defaults
        search_terms: list[list[str]] = []
        if keywords:
            # RemoteOK likes simple tags
            for item in keywords:
                kw = item.get("keyword", "").lower()
                # Split by space if it's a multi-word keyword for RemoteOK tags
                search_terms.append(kw.split())
        else:
            search_terms = TAG_QUERIES

        for tags in search_terms:
            tag_label = "+".join(tags)
            logger.info("Fetching RemoteOK jobs: tags=%s", tag_label)

            try:
                params = [("tag", t) for t in tags]
                resp = requests.get(
                    API_BASE,
                    params=params,
                    headers=HEADERS,
                    timeout=15,
                )
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:
                logger.warning("RemoteOK request failed for tags=%s: %s", tag_label, exc)
                time.sleep(2)
                continue

            # First element is metadata, skip it
            listings = [item for item in data if isinstance(item, dict) and "id" in item]
            logger.info("Got %d listings for tags=%s", len(listings), tag_label)

            for item in listings:
                job_id = str(item.get("id", ""))
                if job_id in seen_ids:
                    continue
                seen_ids.add(job_id)

                url = item.get("url", "") or f"https://remoteok.com/remote-jobs/{job_id}"
                jobs.append({
                    "title": (item.get("position") or "").strip(),
                    "company": (item.get("company") or "").strip(),
                    "location": (item.get("location") or "Remote").strip(),
                    "url": url,
                    "source": self.source,
                    "description": (item.get("description") or "")[:2000].strip(),
                })

            # Be polite between tag queries
            time.sleep(2)

        if not jobs:
            logger.warning("RemoteOKScraper returned 0 jobs.")

        # Log 3 samples for verification
        for i, job in enumerate(jobs[:3]):
            logger.info(
                "Sample job %d: title=%r  company=%r  url=%r",
                i + 1, job.get("title"), job.get("company"), job.get("url"),
            )

        return jobs
