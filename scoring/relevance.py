"""
Deterministic relevance scoring for jobs.

Scores a job between 0.0 and 1.0 based on keyword matching in
title (heavy weight) and description (lighter weight).
"""

import re
from typing import Any

# ── Keyword tiers ──────────────────────────────────────────────────
STRONG_POSITIVE = [
    "ai", "artificial intelligence", "machine learning", "ml",
    "llm", "large language model", "nlp", "natural language processing",
    "deep learning", "generative ai", "gen ai", "computer vision",
    "transformer", "pytorch", "tensorflow", "langchain",
]

MEDIUM_POSITIVE = [
    "python", "backend", "data", "api", "software engineer", "swe", "sde",
    "software development engineer", "frontend", "fullstack", "full stack",
    "data engineer", "data scientist", "mlops", "cloud",
    "aws", "gcp", "docker", "kubernetes", "fastapi", "flask",
    "sql", "postgres", "mongodb",
]

NEGATIVE = [
    "sales", "marketing", "hr", "human resources",
    "recruitment", "recruiter", "content writer",
    "graphic design", "seo", "social media",
    "chartered accountant", "finance manager",
]

# ── Weights ────────────────────────────────────────────────────────
TITLE_WEIGHT = 0.70
DESCRIPTION_WEIGHT = 0.30

STRONG_HIT_SCORE = 0.25
MEDIUM_HIT_SCORE = 0.10
NEGATIVE_HIT_PENALTY = 0.15

MAX_RAW_SCORE = 1.0  # normalisation ceiling (lowered to bump up final scores)


def _count_keyword_hits(text: str, keywords: list[str]) -> int:
    """Return how many distinct keywords appear in *text*."""
    hits = 0
    for kw in keywords:
        if re.search(r"\b" + re.escape(kw) + r"\b", text):
            hits += 1
    return hits


def _score_text(text: str) -> float:
    """Score a single block of text (title or description)."""
    if not text:
        return 0.0

    text_lower = text.lower()

    strong_hits = _count_keyword_hits(text_lower, STRONG_POSITIVE)
    medium_hits = _count_keyword_hits(text_lower, MEDIUM_POSITIVE)
    negative_hits = _count_keyword_hits(text_lower, NEGATIVE)

    raw = (
        strong_hits * STRONG_HIT_SCORE
        + medium_hits * MEDIUM_HIT_SCORE
        - negative_hits * NEGATIVE_HIT_PENALTY
    )

    return max(raw, 0.0)


def score_job(job: dict[str, Any]) -> float:
    """
    Compute a relevance score for a job dict.

    Returns a float in [0.0, 1.0].
    """
    title = (job.get("title") or "").strip()
    description = (job.get("description") or "").strip()

    title_score = _score_text(title)
    desc_score = _score_text(description)

    combined = title_score * TITLE_WEIGHT + desc_score * DESCRIPTION_WEIGHT

    # Normalise to [0, 1]
    normalised = min(combined / MAX_RAW_SCORE, 1.0)

    return round(normalised, 4)
