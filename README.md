# Career Fit Check

A personal job-market intelligence dashboard. Add companies to your watchlist, and the app automatically scrapes their job postings, extracts required skills with Gemini AI, computes a fit score against your profile, and surfaces what to learn next.

Built as a portfolio project demonstrating OSINT pipeline design: open-source data collection → aggregation → AI analysis → decision support.

---

## What it does

| Feature | Detail |
|---------|--------|
| **Company watchlist** | Track any company — the app scrapes their career page and fetches live job postings |
| **Fit scoring** | Compares your skill profile against extracted job requirements, per-role and per-company |
| **Hiring velocity** | 12-week sparklines and bar charts showing how fast each company is hiring |
| **AI nudges** | One-line Gemini analysis of each company's hiring trend, regenerated on every sync |
| **Compare** | Side-by-side skill-gap matrix across multiple companies |
| **Learn Next** | AI-ranked list of skills to close, ordered by fit impact across your whole watchlist |
| **GitHub portfolio** | Connect your GitHub — repos are scanned, skills detected, market fit computed per project, and AI suggests what to build next |
| **Resume upload** | Upload PDF/DOCX — Gemini extracts skills and merges them into your profile |
| **Resume tailor** | For any open role: one-click AI-generated resume bullets and cover letter, with tone/length controls |

---

## Tech stack

| Layer | Technology |
|-------|-----------|
| Backend | FastAPI (Python) |
| Frontend | Vanilla HTML/CSS/JS — single-page app, no framework |
| AI | Google Gemini API (`gemini-2.5-flash`) |
| Scraping | Greenhouse API · Lever API · BeautifulSoup · Selenium |
| Job data | Adzuna API (free tier, primary source) |
| Storage | SQLite via `sqlite3` |
| GitHub data | GitHub REST API (public repos, no auth required) |
| Resume parsing | pdfplumber · python-docx |

---

## Setup

### 1. Clone and install

```bash
git clone https://github.com/istiakMahbub/career-fit-check.git
cd career-fit-check
pip install -r requirements.txt
```

### 2. Configure environment variables

Copy `.env.example` to `.env` and fill in your keys:

```bash
cp .env.example .env
```

```
GEMINI_API_KEY=...     # https://aistudio.google.com — free tier available
ADZUNA_APP_ID=...      # https://developer.adzuna.com — instant free signup
ADZUNA_API_KEY=...
DB_PATH=./career_fit.db
GITHUB_TOKEN=...       # optional — raises GitHub rate limit from 60 → 5000 req/hr
```

### 3. Initialise the database

```bash
python -c "from db.database import init_db; init_db()"
```

### 4. Run

```bash
uvicorn main:app --reload --port 8000
```

Open [http://localhost:8000](http://localhost:8000).

---

## Scraping strategy

Job data is fetched in priority order:

1. **Adzuna API** — structured, reliable, covers most European companies (1000 free calls/month)
2. **Greenhouse JSON API** — if the company uses Greenhouse ATS, a clean JSON endpoint is available
3. **Lever JSON API** — same for Lever-hosted job boards
4. **Static HTML** — requests + BeautifulSoup for companies that host their own career pages
5. **Selenium** — headless Chrome fallback for JS-rendered pages

Scraping only happens when you click **Sync** — results are cached in SQLite.

---

## Project structure

```
career-fit-check/
├── main.py                  # FastAPI app, /api/stats, /api/compare, /api/learn, /api/tailor
├── requirements.txt
├── .env.example
├── db/
│   ├── schema.sql           # 7 tables
│   └── database.py          # connection helpers
├── scrapers/
│   ├── adzuna.py            # Adzuna REST API client
│   └── career_page.py       # Greenhouse · Lever · BS4 · Selenium
├── ai/
│   ├── skill_extractor.py   # Gemini: extract skills from job descriptions
│   ├── fit_calculator.py    # skill overlap scoring
│   ├── insights.py          # Gemini: nudges · summaries · learn headline · GitHub feedback
│   └── resume_tailor.py     # Gemini: tailor resume + cover letter per role
├── routers/
│   ├── companies.py         # /api/companies — list · add · delete · sync · detail
│   ├── jobs.py              # /api/jobs
│   ├── profile.py           # /api/profile — skills · resume upload
│   └── github.py            # /api/github — connect · repos · disconnect
├── static/
│   ├── app.js               # full SPA (~1200 lines, vanilla JS)
│   └── style.css            # design system CSS
└── templates/
    └── index.html           # SPA shell
```

---

## API reference

```
GET  /api/stats                     overview stats (total jobs, new, avg fit, companies)
GET  /api/companies                 watchlist with fit%, sparkline, velocity
POST /api/companies                 add company
DELETE /api/companies/{id}          remove company
POST /api/companies/{id}/sync       scrape + AI extraction
GET  /api/companies/{id}            full detail: roles, skills, velocity, AI nudge, fit ring
GET  /api/jobs?company_id={id}      open roles for a company
GET  /api/profile                   user profile + skills
PUT  /api/profile                   update profile
POST /api/profile/skill             add or update a skill
DELETE /api/profile/skill/{name}    remove a skill
POST /api/profile/resume            upload PDF/DOCX, extract and merge skills
GET  /api/compare?ids=1,2,3         skill matrix across companies
GET  /api/learn                     ranked skill gaps with AI headline
POST /api/tailor                    generate tailored resume + cover letter for a role
POST /api/github/connect            scan GitHub profile, detect skills, compute repo fit
GET  /api/github/repos              cached GitHub data
DELETE /api/github/disconnect       clear GitHub cache
```

---

## Resume & project framing

> **Career Fit Check** — An OSINT-inspired job market intelligence dashboard. Aggregates publicly available job postings from target companies, uses Gemini AI to extract required skills and hiring trends, computes skill-fit scores against the user's profile, and surfaces prioritised learning recommendations. Built with FastAPI, SQLite, Selenium/BeautifulSoup, and Google Gemini API.
