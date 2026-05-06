"""
CLI entrypoint — run the scraper pipeline directly (without the API server).

Usage:
    python main.py
"""

import logging

from db.crud import save_jobs
from db.database import SessionLocal, init_db
from scrapers.wellfound import WellfoundScraper

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def main() -> None:
    logger.info("Initialising database…")
    init_db()

    logger.info("Starting Wellfound scraper…")
    scraper = WellfoundScraper()
    jobs = scraper.scrape()
    logger.info("Scraper finished — %d jobs collected.", len(jobs))

    with SessionLocal() as db:
        result = save_jobs(db, jobs)

    logger.info(
        "Done — scraped=%d  new_saved=%d  duplicates=%d",
        result["scraped"],
        result["new_saved"],
        result["duplicates"],
    )


if __name__ == "__main__":
    main()
