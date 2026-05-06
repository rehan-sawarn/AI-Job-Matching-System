"""
Naukri.com job scraper using undetected-chromedriver (Selenium).

Naukri relies on Akamai Bot Manager which easily blocks Playwright (even in headed mode).
undetected-chromedriver modifies the chromedriver executable to remove CDC variables 
and bypasses these blocks completely.

Confirmed selectors from live DOM inspection (2026-05-05).
"""

import logging
import random
import time
from typing import Any

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By

from scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

SEARCH_SLUGS: list[tuple[str, str]] = [
    ("ai-engineer", "AI Engineer"),
    ("machine-learning-engineer", "ML Engineer"),
    ("python-developer", "Python Developer"),
    ("llm-engineer", "LLM Engineer"),
    ("data-scientist", "Data Scientist"),
]

BASE_URL = "https://www.naukri.com"
PAGES_PER_SEARCH = 2

class NaukriScraper(BaseScraper):
    source = "naukri"

    def scrape(self) -> list[dict[str, Any]]:
        jobs: list[dict[str, Any]] = []

        # We must suppress the exception thrown when quitting undetected-chromedriver on Windows
        try:
            options = uc.ChromeOptions()
            options.add_argument("--window-size=1440,900")
            
            logger.info("Launching undetected-chromedriver...")
            driver = uc.Chrome(
                headless=False,
                use_subprocess=True,
                options=options,
                version_main=146,  # Matches the user's Chrome version
            )

            # Warm-up
            try:
                driver.get(BASE_URL)
                time.sleep(3)
            except Exception as e:
                logger.warning("Warm-up failed: %s", e)

            for slug, label in SEARCH_SLUGS:
                logger.info("Scraping Naukri: %s", label)
                slug_jobs = self._scrape_slug(driver, slug, label)
                logger.info("Found %d jobs for %s", len(slug_jobs), label)
                jobs.extend(slug_jobs)
                time.sleep(random.uniform(2.0, 4.0))

            try:
                driver.quit()
            except OSError:
                pass # WinError 6 is expected here due to a known bug in uc
        except Exception as e:
            logger.error("Failed to run undetected-chromedriver: %s", e, exc_info=True)

        # Deduplicate
        seen: set[str] = set()
        unique: list[dict[str, Any]] = []
        for job in jobs:
            url = job.get("url", "")
            if url and url not in seen:
                seen.add(url)
                unique.append(job)

        if not unique:
            logger.warning("NaukriScraper returned 0 jobs.")

        return unique

    def _build_url(self, slug: str, page_num: int) -> str:
        base = f"{BASE_URL}/{slug}-jobs-in-india"
        return base if page_num == 1 else f"{base}-{page_num}"

    def _scrape_slug(self, driver: uc.Chrome, slug: str, label: str) -> list[dict[str, Any]]:
        jobs: list[dict[str, Any]] = []

        for page_num in range(1, PAGES_PER_SEARCH + 1):
            url = self._build_url(slug, page_num)
            logger.info("Fetching: %s", url)

            try:
                driver.get(url)
                time.sleep(random.uniform(3.0, 5.0))
            except Exception as exc:
                logger.warning("Error loading %s: %s", url, exc)
                continue

            title = driver.title
            logger.info("Page title: %r", title)

            if "access denied" in title.lower():
                logger.warning("Access denied on %s — skipping slug", url)
                break

            page_jobs = self._extract_jobs(driver)
            logger.info("Page %d: extracted %d jobs", page_num, len(page_jobs))
            jobs.extend(page_jobs)

            if not page_jobs:
                logger.info("No jobs on page %d — stopping pagination", page_num)
                break

            time.sleep(random.uniform(1.5, 3.0))

        return jobs

    def _extract_jobs(self, driver: uc.Chrome) -> list[dict[str, Any]]:
        jobs: list[dict[str, Any]] = []

        try:
            cards = driver.find_elements(By.CSS_SELECTOR, "div.srp-jobtuple-wrapper")
            if not cards:
                cards = driver.find_elements(By.CSS_SELECTOR, "article.jobTuple")
        except Exception:
            return jobs

        for card in cards:
            try:
                job = self._parse_card(card)
                if job and job.get("url") and job.get("title"):
                    job["source"] = self.source
                    jobs.append(job)
            except Exception as exc:
                logger.debug("Error parsing card: %s", exc)

        return jobs

    def _parse_card(self, card) -> dict[str, Any] | None:
        job: dict[str, Any] = {
            "title": "",
            "company": "",
            "location": "",
            "url": "",
            "description": "",
        }

        try:
            title_el = card.find_element(By.CSS_SELECTOR, "a.title")
            job["title"] = title_el.text.strip()
            job["url"] = title_el.get_attribute("href")
        except Exception:
            return None
            
        try:
            company_el = card.find_element(By.CSS_SELECTOR, "a.comp-name")
            job["company"] = company_el.text.strip()
        except Exception:
            pass
            
        try:
            loc_el = card.find_element(By.CSS_SELECTOR, "span.locWdth")
            job["location"] = loc_el.text.strip()
        except Exception:
            pass

        return job
