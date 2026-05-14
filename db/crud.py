import logging
from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from db.models import Job, Keyword, make_job_id, make_keyword_id

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
                "detailed_description": job.get("detailed_description"),
                "experience": job.get("experience", ""),
                "experience_level": job.get("experience_level", ""),
                "salary": job.get("salary", ""),
                "skills": job.get("skills", []),
                "relevance_score": job.get("relevance_score"),
                "alerted": False,
                "applied": False,
                "enriched": job.get("enriched", False),
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


def toggle_job_applied(db: Session, job_id: str) -> Job | None:
    """Toggle the applied status of a job."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if job:
        job.applied = not job.applied
        db.commit()
        db.refresh(job)
    return job


def update_job_details(db: Session, job_id: str, updates: dict[str, Any]) -> Job | None:
    """Update specific fields of a job (e.g. after enrichment)."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if job:
        for key, value in updates.items():
            if hasattr(job, key):
                setattr(job, key, value)
        db.commit()
        db.refresh(job)
    return job


def get_all_jobs(db: Session) -> list[Job]:
    """Return all jobs ordered by created_at descending."""
    return db.query(Job).order_by(Job.created_at.desc()).all()


def get_filtered_jobs(
    db: Session,
    *,
    min_score: float | None = None,
    keyword: str | None = None,
    source: str | None = None,
    experience_level: str | None = None,
    applied: bool | None = None,
    limit: int = 100,
) -> list[Job]:
    """
    Return jobs filtered by score, keyword, source, experience_level, and applied status,
    sorted by applied status (not applied first), then relevance_score DESC (nulls last).
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

    if experience_level:
        q = q.filter(Job.experience_level == experience_level.lower())

    if applied is not None:
        q = q.filter(Job.applied == applied)

    # Ranking logic:
    # 1. Unapplied jobs first
    # 2. Fresher/Internship boost: we can do this by adding a case statement in order_by
    # 3. relevance_score DESC
    q = q.order_by(
        Job.applied.asc(), # False (0) before True (1)
        case(
            (Job.experience_level.in_(["fresher", "internship"]), 0),
            else_=1
        ),
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


def purge_jobs_by_source(db: Session, source: str) -> int:
    """Delete all jobs from a specific source. Returns number of deleted rows."""
    count = db.query(Job).filter(Job.source == source.lower()).delete()
    db.commit()
    logger.info("Purged %d jobs for source=%s", count, source)
    return count


# ── Keyword Management ─────────────────────────────────────────────

def get_all_keywords(db: Session) -> list[Keyword]:
    """Return all keywords ordered by label/keyword."""
    return db.query(Keyword).order_by(Keyword.label, Keyword.keyword).all()


def get_active_keywords(db: Session) -> list[Keyword]:
    """Return only enabled keywords."""
    return db.query(Keyword).filter(Keyword.enabled == True).all()


def add_keyword(db: Session, keyword: str, label: str | None = None) -> Keyword:
    """Add a new keyword (idempotent via merge)."""
    kw_id = make_keyword_id(keyword)
    obj = Keyword(
        id=kw_id,
        keyword=keyword.strip(),
        label=(label or keyword).strip(),
        enabled=True
    )
    db.merge(obj)
    db.commit()
    return obj


def delete_keyword(db: Session, kw_id: str) -> bool:
    """Delete a keyword by ID."""
    result = db.query(Keyword).filter(Keyword.id == kw_id).delete()
    db.commit()
    return result > 0


def toggle_keyword_enabled(db: Session, kw_id: str) -> Keyword | None:
    """Toggle the enabled status of a keyword."""
    kw = db.query(Keyword).filter(Keyword.id == kw_id).first()
    if kw:
        kw.enabled = not kw.enabled
        db.commit()
        db.refresh(kw)
    return kw
