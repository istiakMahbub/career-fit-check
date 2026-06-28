# Career Fit Check — v0.1.0-beta

> **An OSINT-inspired job market intelligence dashboard.**
> Add companies to your watchlist → the app scrapes their live job postings → Gemini AI extracts required skills → you see your fit score, skill gaps, ATS keyword match, and exactly what to learn next.

Built as a portfolio project demonstrating an end-to-end OSINT pipeline: open-source data collection → aggregation → AI analysis → decision support.

---

## What it does

### Core intelligence loop
1. You add a company (e.g. Zalando, Trivago, Miele)
2. The app fetches their live job postings via Adzuna API or direct career page scraping
3. Gemini AI (or a local model via Ollama/LM Studio) extracts required and preferred skills from each posting
4. Your profile keywords are matched against those skills — no subjective self-ratings, just keyword presence, exactly how real ATS systems work
5. Every page in the dashboard reflects this live data

### Pages

| Page | What you see |
|------|-------------|
| **Overview** | Watchlist grid — fit %, open roles, hiring velocity sparklines, new role badges |
| **Deep Dive** | Per-company detail: hiring velocity chart, AI nudge, skill chip cloud (green = you have it, red = gap), open roles with match %, your fit ring, what to learn next |
| **Compare** | Side-by-side skill matrix across multiple companies — ✓/— presence per company, coverage count showing how many companies need each skill, dept filter |
| **Learn Next** | Ranked skill gaps across your whole watchlist — WHY IN DEMAND (actual job titles that need it), + Add to profile button, fit gain estimate |
| **ATS Scorer** | Paste your resume against any open role — instant keyword match score with required/preferred split, exact missing keywords to add |
| **Projects** | Connect GitHub — repos scanned, skills detected, market fit computed per project, AI suggests what to build next |
| **Profile** | Keyword-only skill management — add/remove skill chips, resume upload (PDF/DOCX), career focus selector |
| **Applications** | Track your job applications across companies |

---

## ATS Back-Engineering

Modern Applicant Tracking Systems don't score your "level" of Python — they check whether the word "Python" appears in your resume. Career Fit Check mirrors this exactly:

- **Profile skills are keywords** — binary present/absent, no subjective 1–100 ratings
- **Fit score** = keywords you have ÷ keywords the job requires
- **ATS Resume Scorer** — paste your actual resume text against any job posting. The app checks each required keyword as a literal word-boundary match (case-insensitive), the same way ATS software does. Required skills are weighted 2× vs preferred. You get: score %, green ✓ matched chips, red ✗ missing chips, and a "ADD THESE EXACT KEYWORDS" callout
- **Required vs preferred split** — skill extraction now distinguishes must-have from nice-to-have, so the ATS scorer weights them correctly

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | **FastAPI** (Python) |
| Frontend | **Vanilla HTML/CSS/JS** — single-page app, zero framework |
| AI (primary) | **Local model** via Ollama or LM Studio — no quota, no API key |
| AI (fallback) | **Google Gemini API** (`gemini-2.5-flash` / `gemini-2.5-pro`) |
| Job data | **Adzuna API** — free tier, 1000 calls/month |
| Scraping | Greenhouse API · Lever API · BeautifulSoup · Selenium |
| Storage | **SQLite** via `sqlite3` — no ORM |
| GitHub data | GitHub REST API (public repos, no auth required) |
| Resume parsing | pdfplumber · python-docx |
| Fonts | IBM Plex Sans + IBM Plex Mono |

---

## Setup

### 1. Clone and install

```bash
git clone https://github.com/istiakMahbub/career-fit-check.git
cd career-fit-check
pip install -r requirements.txt
```

### 2. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env`:

```env
# Required for AI features (skill extraction, nudges, tailoring)
GEMINI_API_KEY=...        # https://aistudio.google.com — free tier available

# Required for job data
ADZUNA_APP_ID=...         # https://developer.adzuna.com — instant free signup
ADZUNA_API_KEY=...

# Optional — local AI model (no quota, runs offline)
# Works with Ollama (port 11434) or LM Studio (port 1234)
LOCAL_MODEL_NAME=llama3.2:3b       # or: local-model (for LM Studio)
LOCAL_AI_URL=http://localhost:11434 # omit if using default Ollama port

# Optional
DB_PATH=./career_fit.db
GITHUB_TOKEN=...          # raises GitHub rate limit from 60 → 5000 req/hr
```

### 3. (Optional) Set up a local AI model — no Gemini quota needed

**Ollama** (recommended for Mac/Linux):
```bash
# Install from https://ollama.ai then:
ollama pull llama3.2:3b
# Set in .env: LOCAL_MODEL_NAME=llama3.2:3b
```

**LM Studio** (GUI, good for Windows):
1. Download from https://lmstudio.ai
2. Pull "Llama-3.2-3B-Instruct" (Q4_K_M)
3. Start the local server on port 1234
4. Set in `.env`: `LOCAL_MODEL_NAME=local-model` and `LOCAL_AI_URL=http://localhost:1234`

### 4. Initialise the database

```bash
python -c "from db.database import init_db; init_db()"
```

### 5. Run

```bash
uvicorn main:app --reload --port 8000
```

Open [http://localhost:8000](http://localhost:8000)

---

## Project Structure

```
career-fit-check/
├── main.py                  # FastAPI app — /api/stats, /api/compare, /api/learn, /api/ats-score, /api/tailor
├── requirements.txt
├── .env.example
├── db/
│   ├── schema.sql           # 8 tables with auto-migration on startup
│   └── database.py          # connection helpers, migration runner
├── scrapers/
│   ├── adzuna.py            # Adzuna REST API client
│   └── career_page.py       # Greenhouse · Lever · BS4 · Selenium fallback
├── ai/
│   ├── skill_extractor.py   # Local model (primary) + Gemini (fallback)
│   │                        # Returns {required, preferred, category} per job
│   ├── fit_calculator.py    # Keyword overlap scoring
│   ├── insights.py          # Gemini: AI nudges · summaries · learn headline
│   └── resume_tailor.py     # Gemini: tailored resume bullets + cover letter
├── routers/
│   ├── companies.py         # /api/companies — list · add · delete · sync · detail
│   ├── jobs.py              # /api/jobs
│   ├── profile.py           # /api/profile — keyword skills · resume upload
│   ├── github.py            # /api/github — connect · repos · disconnect
│   └── applications.py      # /api/applications — track job applications
├── static/
│   ├── app.js               # Full SPA (~1800 lines, vanilla JS)
│   └── style.css
└── templates/
    └── index.html           # SPA shell + overlay templates
```

---

## API Reference

```
# Stats
GET  /api/stats                        Overview numbers (jobs, new, avg fit, companies)

# Companies
GET  /api/companies                    Watchlist with fit%, sparkline, velocity
POST /api/companies                    Add company {name, website, career_url?}
DELETE /api/companies/{id}             Remove from watchlist
POST /api/companies/{id}/sync          Scrape + AI extraction
GET  /api/companies/{id}?category=X    Full detail: roles, skills, velocity, fit ring

# Profile
GET  /api/profile                      User profile + keyword skills
PUT  /api/profile                      Update name, role, career focus
POST /api/profile/skill                Add keyword to profile
DELETE /api/profile/skill/{name}       Remove keyword
POST /api/profile/resume               Upload PDF/DOCX, extract and merge skills

# Intelligence
GET  /api/compare?ids=1,2&category=X  Skill presence matrix across companies
GET  /api/learn?company_id=X&category=Y  Ranked skill gaps with fit gain estimates
POST /api/ats-score                    {job_id, resume_text} → ATS keyword match score

# AI features
POST /api/tailor                       Generate tailored resume + cover letter for a role

# GitHub
POST /api/github/connect               {username} → scan repos, detect skills, compute fit
GET  /api/github/repos                 Cached GitHub data
DELETE /api/github/disconnect          Clear GitHub cache

# Applications
GET  /api/applications                 Job application tracker
POST /api/applications                 Log a new application
```

---

## Design System

All colours are tokens — consistent across every page:

```
Background page:    #f6f4ef   warm cream
Background sidebar: #fbfaf6
Background card:    #ffffff
Border:             #e7e3da

Primary green:      #15604a   buttons, fit scores, matched skills
Green light:        #e7f0ea   green tint backgrounds
Amber:              #b9791f   AI nudges, learning panel
Red/gap:            #b1493a   missing skills, new role badges

Font body:          IBM Plex Sans
Font mono:          IBM Plex Mono  (numbers, badges, labels)
```

---

## What's Next (Roadmap — v1.0)

**Resume export**
The Tailor feature currently generates resume bullets and cover letter text you can copy. Next version: export a fully formatted, ready-to-send PDF/DOCX directly from the app.

**Deeper Learn Next explanations**
The WHY IN DEMAND section currently shows job titles that need each skill. Next: a richer AI explanation per skill — what specifically is expected, which technologies or tools it relates to, and a concrete learning path.

**Full profile built from resume**
Profile currently extracts keywords only. Next: upload your resume and populate everything — name, summary, work experience, education, hobbies, certifications. The full picture, not just skills.

**Per-company resume versions**
If you track 5 companies, store 5 tailored versions of your resume — one per company. A toggle (like the company switcher in Deep Dive) lets you flip between them. Each version has its own tailored skills section, summary, and bullet points optimised for that company's job requirements.

**Master profile**
A general, untailored base version of your resume that acts as the source for all company-specific versions. Edit the master → changes propagate. Override per company where needed.

**Projects section redesign**
The current GitHub integration is functional but surface-level. Next: a more meaningful view — project-to-role alignment, skill gap per project, and AI suggestions that are actually actionable.

---

## Project Framing

> **Career Fit Check** — An OSINT-inspired job market intelligence dashboard that aggregates publicly available job postings from target companies, uses AI to extract required skills and hiring trends, scores your resume against real ATS keyword logic, and surfaces prioritised learning recommendations. Built with FastAPI, SQLite, and Google Gemini API.

This project directly demonstrates OSINT thesis work: open-source data collection → aggregation → AI analysis → decision support.

---

*v0.1.0-beta — built with [Claude Code](https://claude.ai/code)*
