"""
FastAPI application — AI Job Matching System (Phase 2)

Endpoints:
    GET  /jobs      → filtered & sorted jobs from DB
    GET  /jobs/top  → top 20 jobs by relevance score
    POST /run       → scrape + score + save pipeline
    GET  /health    → health check
"""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from typing import Any, Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from db.crud import get_all_jobs, get_filtered_jobs, get_top_jobs, save_jobs
from db.database import get_db, init_db
from scoring.relevance import score_job
from scrapers.naukri import NaukriScraper
from scrapers.remoteok import RemoteOKScraper
# Wellfound kept but excluded until a proxy is added (Cloudflare blocks headless)
# from scrapers.wellfound import WellfoundScraper

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lifespan — initialise DB tables on startup
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initialising database tables…")
    try:
        init_db()
        logger.info("Database ready.")
    except Exception as exc:
        logger.error("Failed to initialise database: %s", exc)
        raise
    yield
    logger.info("Shutting down.")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="AI Job Matching System",
    description="Phase 2 — Job aggregation, scoring & filtering pipeline",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _job_to_dict(j) -> dict[str, Any]:
    """Serialise a Job ORM object to a plain dict."""
    return {
        "id": j.id,
        "title": j.title,
        "company": j.company,
        "location": j.location,
        "url": j.url,
        "source": j.source,
        "description": j.description,
        "relevance_score": j.relevance_score,
        "alerted": j.alerted,
        "applied": j.applied,
        "notes": j.notes,
        "created_at": j.created_at.isoformat() if j.created_at else None,
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/jobs", summary="Get jobs with filtering & sorting")
def list_jobs(
    min_score: Optional[float] = Query(None, ge=0.0, le=1.0, description="Minimum relevance score"),
    keyword: Optional[str] = Query(None, description="Search keyword (title + description)"),
    source: Optional[str] = Query(None, description="Filter by source (remoteok, naukri)"),
    limit: int = Query(100, ge=1, le=500, description="Max results to return"),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """
    Return jobs from the database, filtered and sorted by relevance score.

    - **min_score**: only return jobs with relevance_score >= this value
    - **keyword**: case-insensitive search in title and description
    - **source**: filter by source name (e.g. 'remoteok', 'naukri')
    - **limit**: max number of results (default 100, max 500)
    """
    jobs = get_filtered_jobs(
        db, min_score=min_score, keyword=keyword, source=source, limit=limit
    )
    return [_job_to_dict(j) for j in jobs]


@app.get("/jobs/top", summary="Get top-ranked jobs")
def top_jobs(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    """Return top 20 jobs with relevance_score > 0.5, sorted by score descending."""
    jobs = get_top_jobs(db, min_score=0.5, limit=20)
    return [_job_to_dict(j) for j in jobs]


# ---------------------------------------------------------------------------
# Scraper + Scoring Pipeline
# ---------------------------------------------------------------------------

def _run_all_scrapers() -> list[dict[str, Any]]:
    """
    Run all active scrapers sequentially in a worker thread.

    On Windows, uvicorn sets a process-wide WindowsSelectorEventLoopPolicy.
    Playwright's sync_playwright internally calls asyncio.new_event_loop() which
    inherits that policy. We force ProactorEventLoop here before any scraper runs.

    Active scrapers (in order):
      1. RemoteOKScraper  — free JSON API, no bot detection
      2. NaukriScraper    — India-focused, undetected-chromedriver, fresher-friendly
    """
    import sys
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    all_jobs: list[dict[str, Any]] = []

    scrapers = [
        ("RemoteOK", RemoteOKScraper()),
        ("Naukri",   NaukriScraper()),
    ]

    for name, scraper in scrapers:
        try:
            logger.info("Running %s scraper...", name)
            jobs = scraper.scrape()
            logger.info("%s returned %d jobs", name, len(jobs))
            all_jobs.extend(jobs)
        except Exception as exc:
            logger.error("%s scraper failed: %s", name, exc, exc_info=True)
            # Continue with remaining scrapers

    return all_jobs


def _score_all_jobs(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach a relevance_score to every job dict."""
    for job in jobs:
        try:
            job["relevance_score"] = score_job(job)
        except Exception as exc:
            logger.warning("Scoring failed for %r: %s", job.get("title"), exc)
            job["relevance_score"] = 0.0
    return jobs


def _log_scoring_summary(jobs: list[dict[str, Any]]) -> None:
    """Log top 3 scored jobs and average score for debugging."""
    if not jobs:
        return

    scores = [j.get("relevance_score", 0.0) for j in jobs]
    avg = sum(scores) / len(scores)
    logger.info("Scoring summary — %d jobs, avg_score=%.4f", len(jobs), avg)

    ranked = sorted(jobs, key=lambda j: j.get("relevance_score", 0.0), reverse=True)
    for i, job in enumerate(ranked[:3]):
        logger.info(
            "  #%d  score=%.4f  title=%r  company=%r",
            i + 1,
            job.get("relevance_score", 0.0),
            job.get("title", ""),
            job.get("company", ""),
        )


@app.post("/run", summary="Run scraper pipeline")
async def run_pipeline(db: Session = Depends(get_db)) -> dict[str, Any]:
    """
    Trigger all active scrapers, score each job for relevance,
    persist to database, and return a summary.
    """
    logger.info("POST /run — starting scraper pipeline")

    # 1. Scrape
    try:
        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor(max_workers=1) as pool:
            jobs = await loop.run_in_executor(pool, _run_all_scrapers)
    except Exception as exc:
        logger.error("Pipeline failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Scraper error: {exc}")

    if not jobs:
        logger.warning("All scrapers returned no jobs.")
        return {"scraped": 0, "new_saved": 0, "duplicates": 0, "avg_score": 0.0}

    # 2. Score
    jobs = _score_all_jobs(jobs)
    _log_scoring_summary(jobs)

    # 3. Save
    try:
        result = save_jobs(db, jobs)
    except Exception as exc:
        logger.error("DB save failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Database error: {exc}")

    avg_score = sum(j.get("relevance_score", 0.0) for j in jobs) / len(jobs)

    logger.info(
        "Pipeline complete — scraped=%d  new_saved=%d  duplicates=%d  avg_score=%.4f",
        result["scraped"],
        result["new_saved"],
        result["duplicates"],
        avg_score,
    )
    return {**result, "avg_score": round(avg_score, 4)}


@app.get("/health", summary="Health check")
def health() -> dict[str, str]:
    return {"status": "ok"}
