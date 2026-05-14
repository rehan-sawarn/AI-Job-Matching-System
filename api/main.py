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

from db.crud import (
    add_keyword,
    delete_keyword,
    get_active_keywords,
    get_all_jobs,
    get_all_keywords,
    get_filtered_jobs,
    get_top_jobs,
    purge_jobs_by_source,
    save_jobs,
    toggle_job_applied,
    toggle_keyword_enabled,
    update_job_details,
)
from db.database import get_db, init_db
from db.models import Job, make_job_id
from scoring.experience import extract_experience_level
from scoring.relevance import score_job
from scrapers.naukri import NaukriScraper
from scrapers.remoteok import RemoteOKScraper
from scrapers.internshala import InternshalaScraper
# Wellfound kept but excluded until a proxy is added (Cloudflare blocks headless)
# from scrapers.wellfound import WellfoundScraper

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ENRICHMENT_LIMIT = 25  # Max jobs to deep-enrich per run

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
        "experience": j.experience,
        "experience_level": j.experience_level,
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
    experience_level: Optional[str] = Query(None),
    applied: Optional[str] = Query(None), # Changed to str to handle empty/invalid inputs
    min_score: Optional[float] = Query(None, ge=0.0, le=1.0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """Dashboard page — renders the job listing with filters."""
    # Convert 'applied' string to boolean or None
    applied_bool = None
    if applied == "true":
        applied_bool = True
    elif applied == "false":
        applied_bool = False

    # Get total count for display
    total_jobs = db.query(Job).count()

    # Apply filters
    effective_min_score = min_score if min_score and min_score > 0 else None
    jobs = get_filtered_jobs(
        db,
        min_score=effective_min_score,
        keyword=keyword,
        source=source,
        experience_level=experience_level,
        applied=applied_bool,
        limit=limit,
    )

    return templates.TemplateResponse("index.html", {
        "request": request,
        "jobs": jobs,
        "total_jobs": total_jobs,
        "keyword": keyword,
        "source": source,
        "experience_level": experience_level,
        "applied": applied_bool,
        "min_score": min_score,
        "active_page": "dashboard",
    })


@app.get("/settings", response_class=HTMLResponse, include_in_schema=False)
def settings_page(
    request: Request,
    db: Session = Depends(get_db),
):
    """Settings / Admin page."""
    keywords = get_all_keywords(db)
    
    # Get counts for each source
    source_counts = {}
    for source in ["remoteok", "naukri", "internshala"]:
        source_counts[source] = db.query(Job).filter(Job.source == source).count()

    return templates.TemplateResponse("settings.html", {
        "request": request,
        "keywords": keywords,
        "source_counts": source_counts,
        "active_page": "settings",
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
    experience_level: Optional[str] = Query(None, description="Filter by experience level"),
    applied: Optional[str] = Query(None, description="Filter by applied status (true/false)"),
    limit: int = Query(100, ge=1, le=500, description="Max results to return"),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """
    Return jobs from the database, filtered and sorted by relevance score.

    - **min_score**: only return jobs with relevance_score >= this value
    - **keyword**: case-insensitive search in title and description
    - **source**: filter by source name (e.g. 'remoteok', 'naukri')
    - **experience_level**: filter by level (internship, fresher, junior, mid-level, senior)
    - **applied**: filter by applied status ('true' or 'false')
    - **limit**: max number of results (default 100, max 500)
    """
    applied_bool = None
    if applied == "true":
        applied_bool = True
    elif applied == "false":
        applied_bool = False

    jobs = get_filtered_jobs(
        db,
        min_score=min_score,
        keyword=keyword,
        source=source,
        experience_level=experience_level,
        applied=applied_bool,
        limit=limit
    )
        
    return [_job_to_dict(j) for j in jobs]


@app.post("/api/jobs/{job_id}/toggle_applied", summary="Toggle job applied status")
def toggle_applied_api(job_id: str, db: Session = Depends(get_db)):
    """Toggle the 'applied' status of a job."""
    job = toggle_job_applied(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"id": job.id, "applied": job.applied}


@app.post("/api/keywords", summary="Add a keyword")
def add_keyword_api(
    keyword: str = Query(...),
    label: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    kw = add_keyword(db, keyword, label)
    return {"id": kw.id, "keyword": kw.keyword, "label": kw.label}


@app.delete("/api/keywords/{kw_id}", summary="Delete a keyword")
def delete_keyword_api(kw_id: str, db: Session = Depends(get_db)):
    success = delete_keyword(db, kw_id)
    if not success:
        raise HTTPException(status_code=404, detail="Keyword not found")
    return {"success": True}


@app.post("/api/keywords/{kw_id}/toggle", summary="Toggle keyword enabled status")
def toggle_keyword_api(kw_id: str, db: Session = Depends(get_db)):
    kw = toggle_keyword_enabled(db, kw_id)
    if not kw:
        raise HTTPException(status_code=404, detail="Keyword not found")
    return {"id": kw.id, "enabled": kw.enabled}


@app.post("/api/maintenance/purge", summary="Purge jobs by source")
def purge_jobs_api(source: str = Query(...), db: Session = Depends(get_db)):
    count = purge_jobs_by_source(db, source)
    return {"source": source, "deleted_count": count}


@app.get("/api/jobs/top", summary="Get top-ranked jobs")
@app.get("/jobs/top", summary="Get top-ranked jobs (legacy)", include_in_schema=False)
def get_top_jobs_api(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    """Return top 20 jobs with relevance_score > 0.5, sorted by score descending."""
    jobs = get_top_jobs(db, min_score=0.5, limit=20)
    return [_job_to_dict(j) for j in jobs]


# ---------------------------------------------------------------------------
# Scraper + Scoring Pipeline
# ---------------------------------------------------------------------------

def _run_all_scrapers(
    sources: list[str] | None = None,
    keywords: list[dict[str, str]] | None = None
) -> list[dict[str, Any]]:
    """
    Run selected scrapers sequentially in a worker thread.
    """
    import sys
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    all_jobs: list[dict[str, Any]] = []

    available_scrapers = [
        ("remoteok", RemoteOKScraper()),
        ("naukri",   NaukriScraper()),
        ("internshala", InternshalaScraper()),
    ]

    for name, scraper in available_scrapers:
        # Skip if sources are specified and this source is not included
        if sources and name not in sources:
            logger.info("Skipping %s scraper (not selected)", name)
            continue

        try:
            logger.info("Running %s scraper with %d keywords...", name, len(keywords) if keywords else 0)
            jobs = scraper.scrape(keywords=keywords)
            logger.info("%s returned %d jobs", name, len(jobs))
            all_jobs.extend(jobs)
        except Exception as exc:
            logger.error("%s scraper failed: %s", name, exc, exc_info=True)

    return all_jobs


def _score_all_jobs(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach a relevance_score and experience_level to every job dict."""
    for job in jobs:
        try:
            job["relevance_score"] = score_job(job)
            job["experience_level"] = extract_experience_level(job)
        except Exception as exc:
            logger.warning("Processing failed for %r: %s", job.get("title"), exc)
            job["relevance_score"] = job.get("relevance_score", 0.0)
            job["experience_level"] = job.get("experience_level", "junior")

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
            "  #%d  score=%.4f  title=%r  company=%r  exp=%r  skills=%s  desc=%r...",
            i + 1,
            job.get("relevance_score", 0.0),
            job.get("title", ""),
            job.get("company", ""),
            job.get("experience", ""),
            job.get("skills", []),
            (job.get("description") or "")[:100],
        )


@app.post("/run", summary="Run scraper pipeline")
async def run_pipeline(
    sources: Optional[list[str]] = Query(None),
    db: Session = Depends(get_db)
) -> dict[str, Any]:
    """
    Trigger selected scrapers, score each job, and persist to DB.
    """
    logger.info("POST /run — starting scraper pipeline (sources=%s)", sources)

    # Fetch active keywords from DB
    active_kws = get_active_keywords(db)
    keywords_data = [{"keyword": kw.keyword, "label": kw.label} for kw in active_kws]

    # 1. Scrape
    try:
        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor(max_workers=1) as pool:
            jobs = await loop.run_in_executor(
                pool, _run_all_scrapers, sources, keywords_data
            )
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

    # 4. Selective Enrichment
    # We want to enrich top-ranked jobs that aren't enriched yet.
    to_enrich = (
        db.query(Job)
        .filter(Job.enriched == False)
        .filter(Job.relevance_score > 0.3)
        .order_by(Job.relevance_score.desc())
        .limit(ENRICHMENT_LIMIT)
        .all()
    )

    enriched_count = 0
    if to_enrich:
        logger.info("Starting enrichment for %d priority jobs...", len(to_enrich))
        by_source: dict[str, list[Job]] = {}
        for j in to_enrich:
            by_source.setdefault(j.source, []).append(j)

        scrapers_map = {
            "naukri": NaukriScraper(),
            "internshala": InternshalaScraper(),
        }

        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor(max_workers=1) as pool:
            for src_name, job_objs in by_source.items():
                scraper = scrapers_map.get(src_name)
                if not scraper:
                    continue

                job_dicts = [_job_to_dict(j) for j in job_objs]
                try:
                    # Internshala enrichment is fast, Naukri is slow/browser-based
                    # but both are now handled via enrich_jobs
                    enriched_dicts = await loop.run_in_executor(
                        pool, scraper.enrich_jobs, job_dicts
                    )
                    
                    for ed in enriched_dicts:
                        if ed.get("enriched"):
                            update_job_details(db, ed["id"], {
                                "detailed_description": ed.get("detailed_description"),
                                "salary": ed.get("salary"),
                                "skills": ed.get("skills"),
                                "enriched": True
                            })
                            enriched_count += 1
                except Exception as exc:
                    logger.error("Enrichment failed for %s: %s", src_name, exc)

    logger.info("Pipeline complete — enriched %d jobs", enriched_count)

    avg_score = sum(j.get("relevance_score", 0.0) for j in jobs) / len(jobs) if jobs else 0.0

    if enriched_count > 0:
        # Log sample
        sample = db.query(Job).filter(Job.enriched == True).order_by(Job.created_at.desc()).first()
        if sample:
             logger.info(
                "Sample enriched job: title=%r  desc_len=%d  skills=%s",
                sample.title,
                len(sample.detailed_description or ""),
                sample.skills
            )

    return {**result, "avg_score": round(avg_score, 4), "enriched": enriched_count}


@app.get("/health", summary="Health check")
def health() -> dict[str, str]:
    return {"status": "ok"}
