import logging
from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from db.models import Job, make_job_id

logger = logging.getLogger(__name__)


def save_jobs(db: Session, jobs: list[dict[str, Any]]) -> dict[str, int]:
    """
    Insert jobs that do not already exist (idempotent via on_conflict_do_nothing).

    Returns a dict with:
        - scraped: total jobs attempted
        - new_saved: jobs actually inserted
        - duplicates: jobs skipped (already in DB)
    """
    if not jobs:
        return {"scraped": 0, "new_saved": 0, "duplicates": 0}

    scraped = len(jobs)
    rows = []
    for job in jobs:
        url = job.get("url", "").strip()
        if not url:
            logger.warning("Skipping job with empty URL: %s", job)
            continue

        rows.append(
            {
                "id": make_job_id(url),
                "title": job.get("title", ""),
                "company": job.get("company", ""),
                "location": job.get("location", ""),
                "url": url,
                "source": job.get("source", ""),
                "description": job.get("description", ""),
                "experience": job.get("experience", ""),
                "salary": job.get("salary", ""),
                "skills": job.get("skills", []),
                "relevance_score": job.get("relevance_score"),
                "alerted": False,
                "applied": False,
                "notes": job.get("notes"),
            }
        )

    if not rows:
        return {"scraped": scraped, "new_saved": 0, "duplicates": scraped}

    stmt = insert(Job).values(rows).on_conflict_do_nothing(index_elements=["id"])
    result = db.execute(stmt)
    db.commit()

    new_saved = result.rowcount
    duplicates = scraped - new_saved

    logger.info(
        "save_jobs — scraped=%d  new_saved=%d  duplicates=%d",
        scraped,
        new_saved,
        duplicates,
    )
    return {"scraped": scraped, "new_saved": new_saved, "duplicates": duplicates}


def get_all_jobs(db: Session) -> list[Job]:
    """Return all jobs ordered by created_at descending."""
    return db.query(Job).order_by(Job.created_at.desc()).all()


def get_filtered_jobs(
    db: Session,
    *,
    min_score: float | None = None,
    keyword: str | None = None,
    source: str | None = None,
    limit: int = 100,
) -> list[Job]:
    """
    Return jobs filtered by score, keyword, and source,
    sorted by relevance_score DESC (nulls last).
    """
    from sqlalchemy import func, case

    q = db.query(Job)

    if min_score is not None:
        q = q.filter(Job.relevance_score >= min_score)

    if keyword:
        pattern = f"%{keyword.lower()}%"
        q = q.filter(
            func.lower(Job.title).like(pattern)
            | func.lower(Job.description).like(pattern)
        )

    if source:
        q = q.filter(Job.source == source.lower())

    # Sort: scored jobs first (desc), then unscored
    q = q.order_by(
        case((Job.relevance_score.is_(None), 1), else_=0),
        Job.relevance_score.desc(),
    )

    return q.limit(min(limit, 500)).all()


def get_top_jobs(
    db: Session,
    *,
    min_score: float = 0.5,
    limit: int = 20,
) -> list[Job]:
    """Return the top N jobs above *min_score*, sorted by relevance_score DESC."""
    return (
        db.query(Job)
        .filter(Job.relevance_score.isnot(None))
        .filter(Job.relevance_score >= min_score)
        .order_by(Job.relevance_score.desc())
        .limit(limit)
        .all()
    )
