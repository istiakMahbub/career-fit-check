# Career Fit Check — Project Brief for Claude Code

## What This Is

A personal job-market intelligence dashboard. The user adds companies they want to work at. The app scrapes those companies' public job postings, extracts required skills using Gemini AI, computes a fit score against the user's skill profile, and surfaces insights — which roles match, what skills are gaps, how fast each company is hiring, and what to learn next.

**This is an OSINT pipeline**: it aggregates publicly available job data from multiple heterogeneous sources, runs AI analysis on it, and produces actionable career intelligence.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | **FastAPI** (Python) |
| Frontend | **Vanilla HTML/CSS/JS** — adapt the prototype directly |
| AI | **Google Gemini API** (gemini-2.5-flash as default; gemini-2.5-pro for resume tailoring + learning plan) |
| Scraping | **Selenium** + **BeautifulSoup** + **requests** |
| Job data fallback | **Adzuna API** (free tier, no key friction) |
| Storage | **SQLite** via `sqlite3` (no ORM needed) |
| GitHub integration | **GitHub REST API** (public, no auth for public repos) |
| Fonts | IBM Plex Sans + IBM Plex Mono (Google Fonts, already in prototype) |

Do NOT use Streamlit. The prototype is pixel-perfect HTML/CSS — serve it directly via FastAPI's StaticFiles + Jinja2 templates.

---

## Design System (from prototype)

Match these exactly. Do not deviate.

```
Background page:    #f6f4ef  (warm cream)
Background sidebar: #fbfaf6
Background card:    #ffffff
Border:             #e7e3da
Border subtle:      #f0ece3

Primary green:      #15604a  (buttons, active states, fit scores)
Green light:        #e7f0ea  (green tint backgrounds)
Green border:       #cfe2d6

Amber:              #b9791f  (AI nudges, learning panel)
Amber light:        #f7edda
Amber border:       #ecddc0

Red/gap:            #b1493a  (new role badges, skill gaps)
Red light:          #f5e5e1

Text primary:       #1b1a17
Text secondary:     #7a756a
Text muted:         #9a9488

Font body:          'IBM Plex Sans', sans-serif
Font mono:          'IBM Plex Mono', monospace  (numbers, badges, labels)
```

---

## Project Structure

```
career-fit-check/
├── CLAUDE.md                  ← this file
├── main.py                    ← FastAPI app entry point
├── requirements.txt
├── .env                       ← GEMINI_API_KEY, ADZUNA_APP_ID, ADZUNA_API_KEY
├── db/
│   ├── schema.sql             ← table definitions
│   └── database.py            ← connection helpers
├── scrapers/
│   ├── career_page.py         ← Selenium + BS4 scraper
│   └── adzuna.py              ← Adzuna API fallback
├── ai/
│   ├── skill_extractor.py     ← Gemini: extract skills from job description
│   ├── fit_calculator.py      ← overlap % between user skills and job skills
│   ├── insights.py            ← Gemini: nudges, summaries, learning plan
│   └── resume_tailor.py       ← Gemini: tailor resume/cover letter per role
├── routers/
│   ├── companies.py           ← /api/companies endpoints
│   ├── jobs.py                ← /api/jobs endpoints
│   ├── profile.py             ← /api/profile endpoints
│   ├── compare.py             ← /api/compare endpoint
│   └── learn.py               ← /api/learn endpoint
├── static/
│   ├── app.js                 ← frontend JS (fetch API calls, render logic)
│   ├── style.css              ← any extra CSS beyond inline styles
│   └── support.js             ← copy from prototype/support.js
└── templates/
    └── index.html             ← single-page app shell (adapted from prototype)
```

---

## Database Schema

```sql
-- companies the user is tracking
CREATE TABLE companies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    slug TEXT UNIQUE NOT NULL,       -- e.g. "picnic", "zalando"
    website TEXT,
    career_url TEXT,                 -- direct career page URL if known
    color TEXT DEFAULT '#15604a',    -- hex color for avatar
    sector TEXT,
    hq TEXT,
    added_date TEXT DEFAULT (datetime('now')),
    last_synced TEXT
);

-- individual job postings scraped from companies
CREATE TABLE jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER REFERENCES companies(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    location TEXT,
    description TEXT,
    url TEXT,
    posted_date TEXT,
    scraped_date TEXT DEFAULT (datetime('now')),
    is_new INTEGER DEFAULT 1,        -- 1 = posted since last user visit
    skills_extracted INTEGER DEFAULT 0  -- 0 = not yet processed by AI
);

-- skills extracted from each job by Gemini
CREATE TABLE job_skills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER REFERENCES jobs(id) ON DELETE CASCADE,
    skill TEXT NOT NULL
);

-- weekly snapshot of job counts per company (for velocity chart)
CREATE TABLE hiring_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER REFERENCES companies(id) ON DELETE CASCADE,
    week TEXT NOT NULL,              -- ISO week string e.g. "2026-W24"
    job_count INTEGER DEFAULT 0
);

-- user's own skill profile
CREATE TABLE user_profile (
    id INTEGER PRIMARY KEY DEFAULT 1,  -- single row
    name TEXT DEFAULT 'Istiak',
    role TEXT DEFAULT 'Data Science Candidate',
    skills TEXT DEFAULT '[]'           -- JSON array: [{"name": "Python", "level": 80}, ...]
);

-- cached AI-generated insights per company (invalidated on sync)
CREATE TABLE company_insights (
    company_id INTEGER PRIMARY KEY REFERENCES companies(id) ON DELETE CASCADE,
    nudge TEXT,                      -- one-line AI insight for deep dive page
    ai_summary TEXT,                 -- longer analysis
    updated_at TEXT DEFAULT (datetime('now'))
);
```

---

## API Endpoints

All endpoints return JSON. Frontend fetches via `fetch('/api/...')`.

### Companies
```
GET  /api/companies              → list of companies with fit%, openRoles, newRoles, sparkline
POST /api/companies              → add company {name, website, career_url?}
DELETE /api/companies/{id}       → remove from watchlist
POST /api/companies/{id}/sync    → trigger scrape + AI extraction for this company
GET  /api/companies/{id}         → full detail: stats, skills, roles, fit breakdown, velocity bars
```

### Jobs
```
GET  /api/jobs?company_id={id}   → list of open roles for a company with match%
```

### Profile
```
GET  /api/profile                → user profile with skills array and avgFit
PUT  /api/profile                → update name, role, skills
POST /api/profile/resume         → upload resume PDF/DOCX, extract and merge skills
```

### Compare
```
GET  /api/compare?ids=1,2,3      → comparison matrix: skill × company requirement
```

### Learn
```
GET  /api/learn                  → ranked skill recommendations across all companies
```

### Overview stats
```
GET  /api/stats                  → {totalJobs, newJobs, avgFit, companiesTracked}
```

### GitHub integration
```
POST /api/github/connect         → {username} → list repos + detected skills
GET  /api/github/repos           → cached repo list with skills and market fit
```

---

## Screen-by-Screen Specification

### 1. OVERVIEW (default screen)

**Top stats row (4 cards):**
- Total open roles across watchlist
- New roles this week
- Average fit % across all companies
- Companies tracked count

**Watchlist grid (3 columns):**
Each company card shows:
- Color avatar with initials
- Company name + sector
- "NEW" badge if new roles exist (red)
- Sparkline SVG — 12-week job count trend (use polyline, viewBox="0 0 100 32")
- Open roles count + velocity label (↑ HIRING / → STABLE / ↓ SLOWING)
- Fit % in company's accent color (green ≥70%, amber 40–69%, red <40%)
- Remove button (✕) top right

Clicking a card navigates to Deep Dive for that company.

---

### 2. DEEP DIVE (per-company detail)

**Company switcher:** horizontal scroll of pill chips for each watchlist company, click to switch.

**Hero header:** large avatar, name, sector, HQ, "N NEW SINCE LAST VISIT" badge.

**3 stat cards:** Open roles, Your Fit %, Avg match on new roles.

**Left column:**
- **Hiring velocity chart** — vertical bar chart, 12 weeks, bars colored by company color, current week highlighted
- **AI Nudge** — amber callout box, one sentence from Gemini about this company's hiring trend
- **Top skills in demand** — horizontal bar chart rows. Each row: skill name, green dot if user has it, fill bar, trend label (e.g. "+12% ↑")
- **Open roles list** — each role shows: title, location + date, AI nudge line, match % progress bar, "Tailor" button

**Right rail:**
- **Your fit card** — circular SVG ring (r=52, stroke-width=11), fit % in center, skill-by-skill breakdown bars below (user level bar + vertical marker for required level)
- **What to learn next** — dark panel (#1b1a17), 3 skill recommendations each showing: skill name, +X% gain, current→target level bars, estimated effort

---

### 3. COMPARE

Company selector chips at top (multi-select). Shows:
- Fit score cards per company (large number + bar)
- **Skill matrix table**: rows = skills, columns = You + each company. Cells color-coded:
  - Green (#15604a bg) = you meet their requirement
  - Amber (#b9791f bg) = you're close (within 1 level)
  - Red (#b1493a bg) = gap
  - Number in cell = level they require (1–5)
- AI verdict callout at bottom (green background)

---

### 4. PROJECTS

**Disconnected state:** prompt to connect GitHub username or local folder path.

**Scanning state:** spinner + "Scanning username..." text.

**Connected state:**
- Source bar (shows username, repo count, Re-sync + Disconnect buttons)
- 3 stat cards: repos scanned, skills detected, aligned roles
- **Portfolio grid (2 columns):** each repo card shows: repo name, language dot + name, description blurb, market fit % (top right), detected skill tags (colored), best-aligned company, AI feedback callout (amber)
- **"Build next" grid:** AI-suggested projects ranked by skills that appear most in watchlist jobs but are absent from portfolio. Each card: project name, +X% fit gain badge, skills it builds (tags), target company avatars

---

### 5. LEARN NEXT

- Dark hero banner: AI analysis headline + 3 aggregate stats (skills to add, companies tracked, avg fit gap)
- **Ranked skill list:** each skill card shows: rank number, skill name, tag (CRITICAL/HIGH/MEDIUM), reason text, and a progress bar showing current level vs. target level, estimated fit gain

---

### 6. PROFILE

**Left: Skills editor**
- Text input + "Add" button to add skills
- "Suggested" chip row (skills common in watchlist but not in profile)
- 2-column skill grid: each skill has name, level bar, −/+ buttons to adjust level, ✕ to remove

**Right rail:**
- Profile card: avatar initials, name, role, avgFit%, skill count
- AI summary callout (amber)
- Resume upload widget: drag/drop or file picker (PDF/DOCX)

---

### 7. TAILOR OVERLAY (modal)

Triggered by "Tailor" button on an open role.

- Header: company avatar, role title, fit %
- Controls: Tone (Professional / Confident / Concise), Length (Brief / Standard / Detailed), Lead With (skill emphasis chips)
- Tabs: Resume | Cover Letter
- Document preview: white card, formatted text generated by Gemini
- Copy to clipboard button

---

## AI / Gemini Integration

### Skill Extraction (per job)
```python
prompt = """
Extract a list of required technical skills from this job description.
Return ONLY a JSON array of skill name strings. No explanation.
Example: ["Python", "SQL", "dbt", "Airflow"]

Job description:
{description}
"""
```

### Fit Calculation
```python
def calculate_fit(user_skills: list[dict], job_skills: list[str]) -> int:
    # user_skills = [{"name": "Python", "level": 80}, ...]
    # job_skills = ["Python", "SQL", "Tableau"]
    user_skill_names = {s["name"].lower() for s in user_skills}
    matched = sum(1 for s in job_skills if s.lower() in user_skill_names)
    return round((matched / len(job_skills)) * 100) if job_skills else 0
```

### Company AI Nudge
```python
prompt = """
You are a career intelligence analyst. In one concise sentence (max 20 words),
describe what this company's recent hiring pattern signals about their strategy.
Company: {company_name}
Recent job titles: {recent_titles}
Top skills in demand: {top_skills}
"""
```

### Resume Tailoring
```python
prompt = """
Rewrite the following resume summary and bullet points to maximize fit for this role.
Keep all facts true — do not invent experience. Emphasize relevant skills.

Role: {role_title} at {company_name}
Required skills: {required_skills}
User profile: {user_skills}
Tone: {tone}
Length: {length}

Original resume sections:
{resume_text}

Return plain text, ready to copy.
"""
```

---

## Scraping Strategy

1. **First try:** Adzuna API — structured, reliable, covers most European companies
   - Endpoint: `https://api.adzuna.com/v1/api/jobs/de/search/1`
   - Params: `what={role}`, `where={city}`, `company={company_name}`
   - Free tier: 1000 calls/month

2. **Fallback:** Direct career page scraping
   - Use `requests` first (fast, for static pages)
   - If job list is empty, use Selenium (for JS-rendered pages)
   - Parse with BeautifulSoup
   - Store raw HTML in jobs.description for Gemini to extract skills

3. **Rate limiting:** Add 1–2 second delays between requests. Respect robots.txt.

---

## Implementation Order for Claude Code

Build in this order — each step is independently testable:

1. `db/schema.sql` + `db/database.py` — create tables, seed user profile
2. `scrapers/adzuna.py` — Adzuna API integration, test with "Picnic" + "Berlin"
3. `ai/skill_extractor.py` — Gemini skill extraction, test with sample job description
4. `ai/fit_calculator.py` — overlap calculation, unit test with mock data
5. `routers/companies.py` — GET + POST + DELETE + sync endpoint
6. `routers/profile.py` — GET + PUT profile, skills management
7. `main.py` — FastAPI app wiring, serve static files
8. `templates/index.html` + `static/app.js` — adapt prototype into working SPA
9. `routers/compare.py` + `routers/learn.py` — comparison and learning plan
10. `ai/insights.py` — AI nudges, company summaries
11. `scrapers/career_page.py` — Selenium scraper (do last — most fragile)
12. GitHub integration + resume upload
13. `ai/resume_tailor.py` — Tailor overlay

---

## Environment Variables (.env)

```
GEMINI_API_KEY=your_key_here
ADZUNA_APP_ID=your_app_id
ADZUNA_API_KEY=your_api_key
DB_PATH=./career_fit.db
```

Get Gemini key free: https://aistudio.google.com
Get Adzuna key free: https://developer.adzuna.com (instant signup)

---

## Run Commands

```bash
# Install dependencies
pip install fastapi uvicorn sqlite3 requests selenium webdriver-manager \
            beautifulsoup4 google-generativeai python-dotenv python-multipart

# Initialize database
python -c "from db.database import init_db; init_db()"

# Run dev server
uvicorn main:app --reload --port 8000

# App opens at: http://localhost:8000
```

---

## What NOT to Do

- Do NOT use Streamlit — the prototype design cannot be replicated in Streamlit
- Do NOT use an ORM (SQLAlchemy etc.) — plain sqlite3 is sufficient and simpler
- Do NOT hardcode skills — always load from user_profile table
- Do NOT re-scrape on every page load — use the SQLite cache, only re-scrape when user clicks "Sync"
- Do NOT store the Gemini API key in code — use .env
- Do NOT use real user data from LinkedIn scraping — it violates ToS; use Adzuna API instead

---

## Resume / OSINT Framing (for project description)

When this project is listed on resume or GitHub:

> **Career Fit Check** — An OSINT-inspired job market intelligence dashboard. Aggregates publicly available job postings from target companies, uses Gemini AI to extract required skills and hiring trends, computes skill-fit scores against the user's profile, and surfaces prioritized learning recommendations. Built with FastAPI, SQLite, Selenium/BeautifulSoup, and Google Gemini API.

This is a direct demonstration of the OSINT thesis topic: open-source data collection → aggregation → AI analysis → decision support.
