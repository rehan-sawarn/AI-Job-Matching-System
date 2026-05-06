# AI Job Matching System

## 1. Project Overview
The **AI Job Matching System** is a backend pipeline and API designed to aggregate job postings from multiple sources, evaluate their relevance to a specific user persona (e.g., AI/ML Engineers), and present the best matches. 

It was built to solve the problem of job discovery fatigue by automating the collection of fresh job listings, bypassing sophisticated bot detection on job boards, and algorithmically scoring the jobs so users only see highly relevant opportunities.

## 2. Features
- **Multi-Source Job Ingestion:** Pulls data from both structured APIs (RemoteOK) and complex, bot-protected web pages (Naukri via `undetected-chromedriver`).
- **Deduplication:** Uses deterministic MD5 hashing of job URLs to ensure idempotent database inserts and prevent duplicate records.
- **Relevance Scoring:** Automatically scores jobs (0.0 to 1.0) using a tiered keyword matching system on the job title and description.
- **Filtering & Ranking API:** RESTful endpoints to filter jobs by minimum score, keywords, source, and to retrieve top-ranked jobs.

## 3. Tech Stack
- **Language:** Python 3.11+
- **Framework:** FastAPI, Uvicorn
- **Database:** PostgreSQL, SQLAlchemy (ORM), psycopg2
- **Scraping:** Requests, Selenium, undetected-chromedriver
- **Infrastructure:** Docker & Docker Compose (for the database)

## 4. Architecture
The system follows a modular, sequential pipeline:
1. **Scraper Engine:** Individual scraper modules (`RemoteOKScraper`, `NaukriScraper`) fetch and parse job data.
2. **Relevance Scoring:** Each parsed job is evaluated against weighted keyword tiers (Strong, Medium, Negative) to generate a normalized `relevance_score`.
3. **Database Layer:** Jobs are inserted into a PostgreSQL database with an `on_conflict_do_nothing` strategy for deduplication.
4. **API Layer:** FastAPI serves the aggregated and scored data to the client.

## 5. API Endpoints

### `POST /run`
Triggers the full ingestion pipeline. Runs all active scrapers, scores the new jobs, saves them to the database, and returns a summary of the run.
- **Response:** `{"scraped": 150, "new_saved": 10, "duplicates": 140, "avg_score": 0.45}`

### `GET /jobs`
Returns all jobs from the database, supporting query parameters for filtering and sorting.
- **Query Params:**
  - `min_score` (float): Minimum relevance score (0.0 to 1.0).
  - `keyword` (string): Search term in title or description.
  - `source` (string): Filter by scraper source (e.g., "remoteok").
  - `limit` (int): Maximum number of results to return.

### `GET /jobs/top`
Convenience endpoint that returns the top 20 jobs with a `relevance_score` > 0.5, sorted by score descending.

## 6. Setup Instructions

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd AI-Job-Matching-System
   ```

2. **Set up the virtual environment**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: .\venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Set up environment variables**
   Copy the example environment file and update the database URL if necessary:
   ```bash
   cp .env.example .env
   ```

5. **Start the Database**
   Ensure Docker is running, then start the PostgreSQL container:
   ```bash
   docker-compose up -d
   ```

6. **Start the API Server**
   ```bash
   uvicorn api.main:app --reload
   ```

## 7. Example Usage

**Run the pipeline to fetch new jobs:**
```bash
curl -X POST "http://127.0.0.1:8000/run"
```

**Get the top-ranked jobs:**
```bash
curl -X GET "http://127.0.0.1:8000/jobs/top"
```

**Filter jobs with a minimum score and specific keyword:**
```bash
curl -X GET "http://127.0.0.1:8000/jobs?min_score=0.3&keyword=python&limit=10"
```
