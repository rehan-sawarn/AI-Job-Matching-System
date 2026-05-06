"""
LLM-based relevance scoring (STUB — Phase 3).

This module will use an LLM (e.g. GPT-4o, Gemini) to score jobs
with deeper semantic understanding beyond keyword matching.

NOT integrated into the pipeline yet.
"""

from typing import Any


def llm_score_job(job: dict[str, Any]) -> float:
    """
    Score a job using an LLM for semantic relevance.

    Future implementation will:
      - Send job title + description to an LLM
      - Ask it to rate relevance to "AI/ML engineer fresher in India"
      - Parse the numeric score from the response
      - Cache results to avoid redundant API calls

    Returns a float in [0.0, 1.0].
    """
    raise NotImplementedError(
        "LLM scoring is not yet implemented. "
        "Use scoring.relevance.score_job() for deterministic scoring."
    )
