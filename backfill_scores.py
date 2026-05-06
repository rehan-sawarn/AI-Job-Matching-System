import logging
from sqlalchemy.orm import Session
from db.database import SessionLocal
from db.models import Job
from scoring.relevance import score_job

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def backfill():
    db: Session = SessionLocal()
    try:
        # Get all jobs to force a re-calculate with the new keywords and weights
        jobs = db.query(Job).all()
        if not jobs:
            logger.info("No jobs to backfill.")
            return

        logger.info(f"Backfilling {len(jobs)} jobs...")
        updated = 0
        for job in jobs:
            job_dict = {
                "title": job.title,
                "description": job.description,
            }
            score = score_job(job_dict)
            job.relevance_score = score
            updated += 1
        
        db.commit()
        logger.info(f"Successfully backfilled {updated} jobs.")
    except Exception as e:
        logger.error(f"Error: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    backfill()
