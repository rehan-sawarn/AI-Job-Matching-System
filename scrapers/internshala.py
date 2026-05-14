import logging
import random
import time
from typing import Any

import requests
from bs4 import BeautifulSoup

from scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

BASE_URL = "https://internshala.com"

class InternshalaScraper(BaseScraper):
    source = "internshala"

    def scrape(self, keywords: list[dict[str, str]] | None = None) -> list[dict[str, Any]]:
        jobs: list[dict[str, Any]] = []
        
        # Default keywords if none provided
        search_terms = []
        if keywords:
            for item in keywords:
                search_terms.append(item.get("keyword", ""))
        else:
            search_terms = ["AI Engineer", "Machine Learning", "Python Developer"]

        for kw in search_terms:
            logger.info("Scraping Internshala for: %s", kw)
            # Internshala search URL for jobs
            slug = kw.lower().replace(" ", "-")
            url = f"{BASE_URL}/jobs/keywords-{slug}"
            
            try:
                resp = requests.get(url, timeout=15, headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                })
                resp.raise_for_status()
                soup = BeautifulSoup(resp.text, "html.parser")
                
                cards = soup.select(".container-fluid.individual_internship")
                logger.info("Found %d potential jobs for %s", len(cards), kw)
                
                for card in cards:
                    try:
                        job = self._parse_card(card)
                        if job:
                            job["source"] = self.source
                            jobs.append(job)
                    except Exception as e:
                        logger.debug("Error parsing Internshala card: %s", e)
                
                time.sleep(random.uniform(2, 4))
                
            except Exception as e:
                logger.error("Failed to scrape Internshala for %s: %s", kw, e)
        
        # Deduplicate
        seen = set()
        unique = []
        for j in jobs:
            if j["url"] not in seen:
                seen.add(j["url"])
                unique.append(j)
        
        if unique:
            sample = unique[0]
            logger.info(
                "Sample Internshala job - Title: '%s', Company: '%s', Experience: '%s', Skills: %s, Desc: '%s...'",
                sample.get("title"), sample.get("company"), sample.get("experience"), 
                sample.get("skills"), (sample.get("description") or "")[:100]
            )

        return unique

    def enrich_job(self, job: dict[str, Any]) -> dict[str, Any]:
        """Fetch full details from the job page."""
        url = job.get("url")
        if not url:
            return job

        try:
            logger.info("Enriching Internshala job: %s", job.get("title"))
            resp = requests.get(url, timeout=15, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            })
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            # Extract full description/responsibilities
            # In Internshala, description is usually in .text-container
            desc_els = soup.select(".text-container")
            if desc_els:
                full_desc = "\n\n".join([el.get_text(strip=True) for el in desc_els])
                job["detailed_description"] = full_desc
            
            # Enrich skills if possible
            skill_els = soup.select(".skill_tags_container span")
            if skill_els:
                skills = [s.get_text(strip=True) for s in skill_els]
                job["skills"] = list(set((job.get("skills") or []) + skills))

            # Enrich salary/stipend
            salary_el = soup.select_one(".stipend_container_table_cell")
            if salary_el:
                job["salary"] = salary_el.get_text(strip=True)

            job["enriched"] = True
            
        except Exception as e:
            logger.error("Failed to enrich Internshala job: %s", e)
        
        return job


    def _parse_card(self, card: Any) -> dict[str, Any] | None:
        title_el = card.select_one(".job-internship-name a")
        if not title_el:
            return None
        
        title = title_el.get_text(strip=True)
        url = BASE_URL + title_el.get("href", "")
        
        company_el = card.select_one(".company-name")
        company = company_el.get_text(strip=True) if company_el else ""
        
        location_el = card.select_one(".location_link")
        location = location_el.get_text(strip=True) if location_el else ""
        
        # Extract experience/details
        # Internshala has details in .other_detail_item_container
        experience = "Fresher" # Default for jobs section
        
        salary_el = card.select_one(".stipend_container_table_cell")
        salary = salary_el.get_text(strip=True) if salary_el else ""

        # Description summary
        # Internshala usually doesn't have a full desc on list page, 
        # but sometimes has "About the job" or similar tags
        skills = []
        # Skills are sometimes in tags
        tag_els = card.select(".skill_tags_container span")
        skills = [t.get_text(strip=True) for t in tag_els]

        return {
            "title": title,
            "company": company,
            "location": location,
            "url": url,
            "description": f"Skills: {', '.join(skills)}" if skills else "View details on Internshala",
            "experience": experience,
            "salary": salary,
            "skills": skills
        }
