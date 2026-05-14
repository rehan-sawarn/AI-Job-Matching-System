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
from bs4 import BeautifulSoup
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

    def scrape(self, keywords: list[dict[str, str]] | None = None) -> list[dict[str, Any]]:
        jobs: list[dict[str, Any]] = []

        # Use passed keywords or fall back to defaults
        search_terms: list[tuple[str, str]] = []
        if keywords:
            for item in keywords:
                # Convert "AI Engineer" -> "ai-engineer" for the URL slug
                kw = item.get("keyword", "")
                label = item.get("label", kw)
                slug = kw.lower().replace(" ", "-")
                search_terms.append((slug, label))
        else:
            search_terms = SEARCH_SLUGS

        # We must suppress the exception thrown when quitting undetected-chromedriver on Windows
        try:
            options = uc.ChromeOptions()
            options.add_argument("--window-size=1440,900")
            
            logger.info("Launching undetected-chromedriver...")
            driver = uc.Chrome(
                headless=False,
                use_subprocess=True,
                options=options,
                version_main=148,  # Matches the user's Chrome version
            )

            # Warm-up
            try:
                driver.get(BASE_URL)
                time.sleep(3)
            except Exception as e:
                logger.warning("Warm-up failed: %s", e)

            for slug, label in search_terms:
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

    def enrich_jobs(self, jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Fetch full details for a batch of jobs by reusing one driver session."""
        if not jobs:
            return []

        enriched_jobs = []
        driver = None
        try:
            options = uc.ChromeOptions()
            options.add_argument("--window-size=1440,900")
            options.add_argument("--disable-extensions")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")

            driver = uc.Chrome(options=options, version_main=148)

            for job in jobs:
                url = job.get("url")
                if not url:
                    enriched_jobs.append(job)
                    continue

                try:
                    logger.info("Enriching Naukri job: %s", job.get("title"))
                    driver.get(url)
                    time.sleep(random.uniform(3.0, 5.0))

                    soup = BeautifulSoup(driver.page_source, "html.parser")

                    # Full description usually in .job-desc or similar
                    desc_el = soup.select_one(".job-desc") or soup.select_one(".description") or soup.select_one("section.job-desc")
                    if desc_el:
                        job["detailed_description"] = desc_el.get_text(separator="\n", strip=True)

                    # Additional metadata extraction can go here (salary, company info etc)
                    # If detail page has better salary/experience info, update it

                    job["enriched"] = True
                    enriched_jobs.append(job)

                except Exception as e:
                    logger.warning("Failed to enrich Naukri job %s: %s", url, e)
                    enriched_jobs.append(job)

        except Exception as e:
            logger.error("Naukri enrichment failed: %s", e)
            return jobs # Return as-is if driver fails
        finally:
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass

        return enriched_jobs


    def _scrape_slug(
self, driver: uc.Chrome, slug: str, label: str) -> list[dict[str, Any]]:
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
            html = driver.page_source
            soup = BeautifulSoup(html, "html.parser")
            
            cards = soup.select("div.srp-jobtuple-wrapper")
            if not cards:
                cards = soup.select("article.jobTuple")
            if not cards:
                cards = soup.select(".jobTuple")
        except Exception as exc:
            logger.error("Error reading page source: %s", exc)
            return jobs

        for card in cards:
            try:
                job = self._parse_card(card)
                if job and job.get("url") and job.get("title"):
                    job["source"] = self.source
                    jobs.append(job)
            except Exception as exc:
                logger.debug("Error parsing card: %s", exc)

        if jobs:
            sample = jobs[0]
            desc_preview = (sample.get("description") or "")[:100]
            logger.info(
                "Sample extracted job - Title: '%s', Company: '%s', Experience: '%s', "
                "Skills: %s, Desc preview: '%s...'",
                sample.get("title", ""),
                sample.get("company", ""),
                sample.get("experience", ""),
                sample.get("skills", []),
                desc_preview
            )

        return jobs

    def _parse_card(self, card: Any) -> dict[str, Any] | None:
        job: dict[str, Any] = {
            "title": "",
            "company": "",
            "location": "",
            "url": "",
            "description": "",
            "skills": [],
            "experience": "",
            "salary": "",
        }

        # Title & URL
        title_el = card.select_one("a.title") or card.select_one(".title") or card.select_one("[class*='title']")
        if not title_el:
            return None
            
        job["title"] = title_el.get_text(strip=True)
        job["url"] = title_el.get("href", "")
        if job["url"] and not job["url"].startswith("http"):
            job["url"] = "https://www.naukri.com" + job["url"]
            
        # Company
        company_el = card.select_one("a.comp-name") or card.select_one(".companyName") or card.select_one("[class*='comp-name']")
        if company_el:
            job["company"] = company_el.get_text(strip=True)
            
        # Location
        loc_el = (card.select_one("span.locWdth") or card.select_one(".locWdth") or 
                  card.select_one(".location") or card.select_one("[class*='loc']"))
        if loc_el:
            job["location"] = loc_el.get_text(strip=True)

        # Experience
        exp_el = (card.select_one("span.expwdth") or card.select_one(".expwdth") or 
                  card.select_one(".experience") or card.select_one("[class*='exp']"))
        if exp_el:
            job["experience"] = exp_el.get_text(strip=True)

        # Salary
        sal_el = (card.select_one("span.sal") or card.select_one(".sal") or 
                  card.select_one(".salary") or card.select_one("[class*='salary']"))
        if sal_el:
            val = sal_el.get_text(strip=True)
            if val.lower() not in ["not disclosed", "unspecified", "hidden"]:
                job["salary"] = val

        # Skills / Tech Stack - Very important for Phase 3
        skill_els = card.select("ul.tags-gt > li.tag-li")
        if not skill_els:
            skill_els = card.select("ul.tags > li")
        if not skill_els:
            skill_els = card.select(".tags li")
        if not skill_els:
            skill_els = card.select("[class*='tag'] li")
            
        if skill_els:
            job["skills"] = [skill.get_text(strip=True) for skill in skill_els if skill.get_text(strip=True)]

        # Description / Requirements Summary
        # Often Naukri has a short snippet in 'span.job-desc' or similar
        desc_el = (card.select_one("span.job-desc") or card.select_one(".job-desc") or 
                   card.select_one(".jobDescription") or card.select_one("[class*='desc']"))
        if desc_el:
            job["description"] = desc_el.get_text(strip=True)

        # Enrichment: if description is short and we have skills, combine them
        if (not job["description"] or len(job["description"]) < 50) and job["skills"]:
            skill_str = "Required Skills: " + ", ".join(job["skills"])
            if job["description"]:
                job["description"] = f"{job['description']}\n\n{skill_str}"
            else:
                job["description"] = skill_str

        return job
