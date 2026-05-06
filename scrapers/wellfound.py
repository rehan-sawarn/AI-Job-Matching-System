"""
Wellfound job scraper using Playwright sync API (headless Chromium).

Anti-detection strategy:
  - playwright-stealth patches navigator.webdriver, chrome APIs, etc.
  - Realistic browser headers, viewport, locale, timezone
  - Human-like delays between actions
  - Warm-up: visit homepage first before navigating to job pages

URL pattern: https://wellfound.com/role/l/{role-slug}/{location-slug}?page=N
"""

import logging
import random
import time
from typing import Any

from playwright.sync_api import sync_playwright, Browser, Page, TimeoutError as PWTimeout
from playwright_stealth import stealth_sync

from scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

# Maps to Wellfound's /role/l/<role>/<location> URL pattern
ROLE_SEARCHES: list[tuple[str, str]] = [
    ("artificial-intelligence-engineer", "india"),
    ("machine-learning-engineer", "india"),
    ("backend-engineer", "india"),
    ("data-scientist", "india"),
]

BASE_URL = "https://wellfound.com/role/l"
PAGES_PER_ROLE = 2

# Realistic Chrome on Windows headers
EXTRA_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
}

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


class WellfoundScraper(BaseScraper):
    source = "wellfound"

    def scrape(self) -> list[dict[str, Any]]:
        jobs: list[dict[str, Any]] = []

        with sync_playwright() as pw:
            browser: Browser = pw.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                ],
            )
            context = browser.new_context(
                user_agent=USER_AGENT,
                viewport={"width": 1440, "height": 900},
                locale="en-US",
                timezone_id="Asia/Kolkata",
                extra_http_headers=EXTRA_HEADERS,
            )

            page: Page = context.new_page()

            # Apply stealth patches (hides navigator.webdriver, fixes chrome APIs, etc.)
            stealth_sync(page)

            # Warm up: visit the homepage first so we look like a real visitor
            self._warm_up(page)

            for role_slug, location_slug in ROLE_SEARCHES:
                label = f"{role_slug}/{location_slug}"
                logger.info("Scraping Wellfound: %s", label)
                role_jobs = self._scrape_role(page, role_slug, location_slug)
                logger.info("Found %d jobs for %s", len(role_jobs), label)
                jobs.extend(role_jobs)
                time.sleep(random.uniform(3.0, 6.0))

            browser.close()

        # Deduplicate by URL
        seen: set[str] = set()
        unique: list[dict[str, Any]] = []
        for job in jobs:
            url = job.get("url", "")
            if url and url not in seen:
                seen.add(url)
                unique.append(job)

        if not unique:
            logger.warning(
                "WellfoundScraper returned 0 jobs — "
                "may be blocked or page structure changed."
            )

        # Log 3 sample jobs for Phase 1 verification
        for i, job in enumerate(unique[:3]):
            logger.info(
                "Sample job %d: title=%r  company=%r  url=%r",
                i + 1,
                job.get("title"),
                job.get("company"),
                job.get("url"),
            )

        return unique

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _warm_up(self, page: Page) -> None:
        """Visit the Wellfound homepage to establish a real browser session."""
        try:
            logger.info("Warming up — visiting wellfound.com homepage...")
            # networkidle ensures any CF challenge on homepage also fully resolves
            page.goto(
                "https://wellfound.com",
                wait_until="networkidle",
                timeout=45_000,
            )
            time.sleep(random.uniform(2.0, 4.0))
            page.mouse.move(random.randint(200, 800), random.randint(200, 600))
            time.sleep(random.uniform(1.0, 2.0))
            logger.info("Warm-up complete. Page title: %r", page.title())
        except Exception as exc:
            logger.warning("Warm-up failed (non-fatal): %s", exc)

    def _build_url(self, role_slug: str, location_slug: str, page_num: int) -> str:
        base = f"{BASE_URL}/{role_slug}/{location_slug}"
        return f"{base}?page={page_num}" if page_num > 1 else base

    def _scrape_role(
        self, page: Page, role_slug: str, location_slug: str
    ) -> list[dict[str, Any]]:
        jobs: list[dict[str, Any]] = []

        for page_num in range(1, PAGES_PER_ROLE + 1):
            url = self._build_url(role_slug, location_slug, page_num)
            logger.info("Fetching: %s", url)

            try:
                # networkidle waits until the Cloudflare JS challenge has
                # auto-solved + redirected to the real page (domcontentloaded
                # fires on the challenge page itself, too early)
                page.goto(url, wait_until="networkidle", timeout=45_000)
            except PWTimeout:
                logger.warning("Timeout on %s — skipping", url)
                continue
            except Exception as exc:
                logger.warning("Error loading %s: %s", url, exc)
                continue

            logger.info("Page title after load: %r", page.title())

            # If still showing CF challenge, give it up to 10 more seconds
            if self._is_blocked(page):
                logger.warning(
                    "CF challenge still active on %s — waiting 10s for it to resolve...", url
                )
                time.sleep(10)
                if self._is_blocked(page):
                    logger.warning("Still blocked after retry — skipping %s", url)
                    continue
                logger.info("Challenge resolved after wait.")

            page_jobs = self._extract_jobs(page)
            logger.info("Page %d: extracted %d jobs", page_num, len(page_jobs))
            jobs.extend(page_jobs)

            if not page_jobs:
                logger.info("No jobs on page %d — stopping pagination", page_num)
                break

            time.sleep(random.uniform(2.0, 4.0))

        return jobs

    def _is_blocked(self, page: Page) -> bool:
        """Detect Cloudflare or login walls."""
        try:
            content = page.content()
            title = page.title().lower()
            blocked_signals = [
                "'t':'bv'",          # Cloudflare BV challenge
                "data-cfasync",      # Cloudflare script tag
                "Just a moment",     # Cloudflare waiting room
                "cf-browser-verification",
                "Enable JavaScript and cookies to continue",
            ]
            if any(sig in content for sig in blocked_signals):
                return True
            if "just a moment" in title or "attention required" in title:
                return True
        except Exception:
            pass
        return False

    def _extract_jobs(self, page: Page) -> list[dict[str, Any]]:
        """
        Extract jobs from a Wellfound role/location listing page.

        Primary: <a class="text-brand-burgandy"> links (job titles)
        Fallback: any <a href*="/jobs/"> links
        """
        jobs: list[dict[str, Any]] = []

        # Try primary selector first
        try:
            job_links = page.query_selector_all("a.text-brand-burgandy")
            logger.debug(
                "Primary selector 'a.text-brand-burgandy': %d matches", len(job_links)
            )
        except Exception as exc:
            logger.warning("Selector query failed: %s", exc)
            job_links = []

        # Fallback selectors
        if not job_links:
            fallback_selectors = [
                "a[href*='/jobs/']",
                "a[href*='/role/']",
                "[class*='JobListing'] a",
                "[data-test*='job'] a",
            ]
            for sel in fallback_selectors:
                try:
                    job_links = page.query_selector_all(sel)
                    if job_links:
                        logger.info("Fallback selector %r matched %d links", sel, len(job_links))
                        break
                except Exception:
                    continue

        if not job_links:
            logger.warning(
                "No job links found. Page title: %r | First 300 chars: %s",
                page.title(),
                page.content()[:300],
            )
            return jobs

        for link in job_links:
            try:
                job = self._parse_job_link(link, page)
                if job and job.get("url") and job.get("title"):
                    job["source"] = self.source
                    jobs.append(job)
            except Exception as exc:
                logger.debug("Error parsing job link: %s", exc)

        return jobs

    def _parse_job_link(self, link, page: Page) -> dict[str, Any] | None:
        job: dict[str, Any] = {
            "title": "",
            "company": "",
            "location": "",
            "url": "",
            "description": "",
        }

        # title
        try:
            job["title"] = (link.inner_text() or "").strip()
        except Exception:
            pass

        # url
        try:
            href = link.get_attribute("href") or ""
            job["url"] = (
                href if href.startswith("http") else f"https://wellfound.com{href}"
            )
        except Exception:
            pass

        if not job["title"] or not job["url"]:
            return None

        # company: walk up DOM to find nearest h2
        try:
            company = page.evaluate(
                """(el) => {
                    let node = el;
                    for (let i = 0; i < 12; i++) {
                        node = node.parentElement;
                        if (!node) break;
                        const h2 = node.querySelector('h2');
                        if (h2) return h2.innerText.trim();
                    }
                    return '';
                }""",
                link,
            )
            job["company"] = (company or "").strip()
        except Exception:
            pass

        # location: look for remote/office signals near the link
        try:
            location = page.evaluate(
                """(el) => {
                    let node = el.parentElement;
                    for (let i = 0; i < 8; i++) {
                        if (!node) break;
                        const text = node.innerText || '';
                        const m = text.match(/(Remote|In office[^\\n]*|Hybrid[^\\n]*)/i);
                        if (m) return m[1].trim();
                        node = node.parentElement;
                    }
                    return '';
                }""",
                link,
            )
            job["location"] = (location or "").strip()
        except Exception:
            pass

        return job
