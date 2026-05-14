import re
from typing import Any

EXPERIENCE_LEVELS = ["internship", "fresher", "junior", "mid-level", "senior"]

def extract_experience_level(job: dict[str, Any]) -> str:
    """
    Extract experience level from job title, experience string, or description.
    Returns one of: internship, fresher, junior, mid-level, senior, or None.
    """
    title = (job.get("title") or "").lower()
    exp_str = (job.get("experience") or "").lower()
    description = (job.get("description") or "").lower()

    # 1. Check for Internship
    if any(kw in title for kw in ["intern", "internship"]):
        return "internship"
    if "intern" in exp_str:
        return "internship"

    # 2. Check for Senior/Lead/Architect
    if any(kw in title for kw in ["senior", "sr.", "lead", "architect", "principal", "staff"]):
        return "senior"
    
    # 3. Parse years from experience string (common in Naukri)
    # e.g. "0-1 years", "2-5 years", "5+ years"
    years_match = re.findall(r"(\d+)", exp_str)
    if years_match:
        years = [int(y) for y in years_match]
        min_years = min(years)
        if min_years == 0:
            return "fresher"
        if min_years <= 2:
            return "junior"
        if min_years <= 6:
            return "mid-level"
        return "senior"

    # 4. Title heuristics
    if any(kw in title for kw in ["fresher", "graduate", "entry level", "trainee"]):
        return "fresher"
    if "junior" in title or "jr." in title:
        return "junior"
    
    # 5. Description heuristics (fallback)
    if "0 years" in description or "fresher" in description:
        return "fresher"
    
    # Default to junior if title contains "engineer" or "developer" and no senior keywords
    if any(kw in title for kw in ["engineer", "developer", "programmer", "analyst"]):
        return "junior"

    return "mid-level" # Safe default
