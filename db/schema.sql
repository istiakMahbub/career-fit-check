CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    slug TEXT UNIQUE NOT NULL,
    website TEXT,
    career_url TEXT,
    color TEXT DEFAULT '#15604a',
    sector TEXT,
    hq TEXT,
    added_date TEXT DEFAULT (datetime('now')),
    last_synced TEXT
);

CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER REFERENCES companies(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    location TEXT,
    description TEXT,
    url TEXT,
    posted_date TEXT,
    scraped_date TEXT DEFAULT (datetime('now')),
    is_new INTEGER DEFAULT 1,
    skills_extracted INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS job_skills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER REFERENCES jobs(id) ON DELETE CASCADE,
    skill TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS hiring_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER REFERENCES companies(id) ON DELETE CASCADE,
    week TEXT NOT NULL,
    job_count INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS user_profile (
    id INTEGER PRIMARY KEY DEFAULT 1,
    name TEXT DEFAULT 'Istiak',
    role TEXT DEFAULT 'Data Science Candidate',
    skills TEXT DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS company_insights (
    company_id INTEGER PRIMARY KEY REFERENCES companies(id) ON DELETE CASCADE,
    nudge TEXT,
    ai_summary TEXT,
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS github_cache (
    id INTEGER PRIMARY KEY DEFAULT 1,
    username TEXT,
    repos_json TEXT DEFAULT '[]',
    skills_json TEXT DEFAULT '[]',
    build_next_json TEXT DEFAULT '[]',
    last_synced TEXT
);
