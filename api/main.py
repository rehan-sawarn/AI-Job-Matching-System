"""
FastAPI application — AI Job Matching System (Phase 2 + UI)

API Endpoints (JSON):
    GET  /api/jobs      → filtered & sorted jobs from DB
    GET  /api/jobs/top  → top 20 jobs by relevance score
    POST /run           → scrape + score + save pipeline
    GET  /health        → health check

UI Pages (HTML):
    GET  /              → Dashboard with filters
    GET  /top           → Top-ranked jobs
    GET  /job/{id}      → Job detail page
"""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from db.crud import get_all_jobs, get_filtered_jobs, get_top_jobs, save_jobs
from db.database import get_db, init_db
from db.models import Job, make_job_id
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
# Template setup
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

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
    description="Phase 2 — Job aggregation, scoring & filtering pipeline with UI",
    version="2.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files directory (if it exists)
static_dir = BASE_DIR / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


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
# UI Routes (HTML pages)
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def dashboard_page(
    request: Request,
    keyword: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    min_score: Optional[float] = Query(None, ge=0.0, le=1.0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """Dashboard page — renders the job listing with filters."""
    # Get total count for display
    total_jobs = db.query(Job).count()

    # Apply filters
    effective_min_score = min_score if min_score and min_score > 0 else None
    jobs = get_filtered_jobs(
        db,
        min_score=effective_min_score,
        keyword=keyword,
        source=source,
        limit=limit,
    )

    return templates.TemplateResponse("index.html", {
        "request": request,
        "jobs": jobs,
        "total_jobs": total_jobs,
        "keyword": keyword,
        "source": source,
        "min_score": min_score,
        "active_page": "dashboard",
    })


@app.get("/top", response_class=HTMLResponse, include_in_schema=False)
def top_jobs_page(
    request: Request,
    db: Session = Depends(get_db),
):
    """Top jobs page — shows highest-scored jobs."""
    jobs = get_top_jobs(db, min_score=0.3, limit=20)

    return templates.TemplateResponse("top.html", {
        "request": request,
        "jobs": jobs,
        "active_page": "top",
    })


@app.get("/job/{job_id}", response_class=HTMLResponse, include_in_schema=False)
def job_detail_page(
    job_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """Job detail page — shows full description and metadata."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return templates.TemplateResponse("detail.html", {
        "request": request,
        "job": job,
        "active_page": None,
    })


# ---------------------------------------------------------------------------
# API Routes (JSON — prefixed with /api for clarity, plus originals)
# ---------------------------------------------------------------------------

@app.get("/api/jobs", summary="Get jobs with filtering & sorting")
@app.get("/jobs", summary="Get jobs with filtering & sorting (legacy)", include_in_schema=False)
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


@app.get("/api/jobs/top", summary="Get top-ranked jobs")
@app.get("/jobs/top", summary="Get top-ranked jobs (legacy)", include_in_schema=False)
def get_top_jobs_api(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
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
    avg = sum(scores) / len(scores) if scores else 0.0
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

    avg_score = sum(j.get("relevance_score", 0.0) for j in jobs) / len(jobs) if jobs else 0.0

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
