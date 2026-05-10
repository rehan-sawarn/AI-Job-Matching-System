import hashlib
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class Job(Base):
    __tablename__ = "jobs"

    # Primary key is MD5 hash of the job URL — ensures deterministic dedup
    id = Column(String(32), primary_key=True)
    title = Column(String(512), nullable=False)
    company = Column(String(512), nullable=False)
    location = Column(String(256), nullable=True)
    url = Column(Text, unique=True, nullable=False)
    source = Column(String(128), nullable=False)
    description = Column(Text, nullable=True)
    experience = Column(String(128), nullable=True)
    salary = Column(String(128), nullable=True)
    from sqlalchemy import JSON
    skills = Column(JSON, nullable=True)
    relevance_score = Column(Float, nullable=True)
    alerted = Column(Boolean, default=False, nullable=False)
    applied = Column(Boolean, default=False, nullable=False)
    notes = Column(Text, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<Job id={self.id!r} title={self.title!r} company={self.company!r}>"


def make_job_id(url: str) -> str:
    """Generate a deterministic MD5 job ID from the job URL."""
    return hashlib.md5(url.encode("utf-8")).hexdigest()
