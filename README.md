# AI Job Matching System

## 1. Project Overview
The **AI Job Matching System** is a full-stack application designed to aggregate job postings from multiple sources, evaluate their relevance to a specific user persona (e.g., AI/ML Engineers), and present the best matches through a modern web interface.

It solves the problem of job discovery fatigue by automating the collection of fresh job listings, bypassing sophisticated bot detection on job boards, algorithmically scoring the jobs, and presenting them in a clean, responsive dashboard so users only see highly relevant opportunities.

## 2. Features
- **Full-Stack Web UI:** A fast, responsive dashboard built with FastAPI, Jinja2 templates, and TailwindCSS for filtering, ranking, and viewing detailed job listings.
- **Multi-Source Job Ingestion:** Pulls data from both structured APIs (RemoteOK) and complex, bot-protected web pages (Naukri via `undetected-chromedriver`).
- **Deep Metadata Extraction:** Uses `BeautifulSoup` to accurately parse nested DOM elements and extract rich metadata, including skills, required experience, salary, and detailed descriptions.
- **Deduplication:** Uses deterministic MD5 hashing of job URLs to ensure idempotent database inserts and prevent duplicate records.
- **Relevance Scoring:** Automatically scores jobs (0.0 to 1.0) using a hybrid semantic scoring engine powered by keyword matching and the Gemini API.

## 3. Tech Stack
- **Language:** Python 3.11+
- **Backend Framework:** FastAPI, Uvicorn
- **Frontend UI:** Jinja2 Templates, TailwindCSS
- **Database:** PostgreSQL, SQLAlchemy (ORM), psycopg2
- **Scraping:** Requests, Selenium, `undetected-chromedriver`, `BeautifulSoup4`
- **AI/LLM:** Google Gemini API
- **Infrastructure:** Docker & Docker Compose (for the database)

## 4. Architecture
The system follows a modular pipeline:
1. **Scraper Engine:** Individual scraper modules fetch data and parse nested elements.
2. **Relevance Scoring:** Each parsed job is evaluated against a semantic scoring engine to generate a normalized `relevance_score`.
3. **Database Layer:** Jobs and their rich metadata (skills, experience, salary) are inserted into PostgreSQL.
4. **API & UI Layer:** FastAPI serves RESTful JSON endpoints and renders the Jinja2 HTML dashboard for the user.

## 5. Endpoints & Pages

### Web UI (HTML)
- `GET /` — Dashboard with filters and job listings.
- `GET /top` — Top-ranked jobs (score > 0.3).
- `GET /job/{id}` — Job detail page showing full descriptions, skills, and metadata.

### API Endpoints (JSON)
- `POST /run` — Triggers the full ingestion pipeline. Runs active scrapers, scores jobs, saves them, and returns a summary.
- `GET /api/jobs` — Returns jobs from the database (supports `min_score`, `keyword`, `source`, `limit`).
- `GET /api/jobs/top` — Returns the top 20 jobs with a `relevance_score` > 0.5.

## 6. Setup Instructions

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd AI-Job-Matching-System
   ```

2. **Set up the virtual environment**
   ```bash
   python -m venv venv
   # On Windows:
   .\venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Set up environment variables**
   Copy the example environment file and update your PostgreSQL URL and Gemini API Key:
   ```bash
   cp .env.example .env
   ```

5. **Start the Database**
   Ensure Docker is running, then start the PostgreSQL container:
   ```bash
   docker-compose up -d
   ```

6. **Start the Server**
   ```bash
   python -m uvicorn api.main:app --reload
   ```

## 7. Example Usage

**Run the pipeline to fetch new jobs:**
```bash
curl -X POST "http://127.0.0.1:8000/run"
```

**Get the top-ranked jobs (API):**
```bash
curl -X GET "http://127.0.0.1:8000/api/jobs/top"
```

**Filter jobs via API:**
```bash
curl -X GET "http://127.0.0.1:8000/api/jobs?min_score=0.3&keyword=python&limit=10"
```
