import json
import logging
import math
import re
import time
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from db.database import get_db
from scrapers.adzuna import fetch_jobs
from scrapers.career_page import scrape_company, ScrapedJob
from ai.skill_extractor import extract_skills, extract_skills_and_category, extract_skills_batch, GeminiRateLimitError
from ai.fit_calculator import calculate_fit, calculate_company_fit, skill_gap
from ai.insights import generate_nudge, generate_summary, generate_skill_tips

log = logging.getLogger(__name__)
router = APIRouter()

# ── palette & helpers ────────────────────────────────────────────────────────

_COLORS = [
    "#15604a", "#2563a6", "#6b4f9e", "#2f6f4e",
    "#b0792a", "#2a8a86", "#b1493a", "#3a6ea5",
]

_SKILL_EXTRACTION_BATCH = 30   # jobs per Gemini call (token budget)


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _pick_color(name: str) -> str:
    return _COLORS[sum(ord(c) for c in name) % len(_COLORS)]


def _initials(name: str) -> str:
    parts = [w for w in name.split() if w]
    if len(parts) >= 2:
        return (parts[0][0] + parts[-1][0]).upper()
    return name[:2].upper()


def _fit_color(v: int) -> str:
    if v >= 70:
        return "#15604a"
    if v >= 45:
        return "#b9791f"
    return "#b1493a"


def _vel_pct(weekly: list[int]) -> int:
    if len(weekly) < 2 or weekly[0] == 0:
        return 0
    return round((weekly[-1] - weekly[0]) / weekly[0] * 100)


def _vel_label(pct: int) -> str:
    return ("+" if pct >= 0 else "") + str(pct) + "%"


def _vel_color(pct: int) -> str:
    return "#15604a" if pct >= 0 else "#b1493a"


def _spark_points(weekly: list[int]) -> str:
    if not weekly:
        return ""
    n = len(weekly)
    W, H = 100, 28
    mn, mx = min(weekly), max(weekly)
    span = mx - mn or 1
    pts = []
    for i, v in enumerate(weekly):
        x = (i / (n - 1)) * W if n > 1 else 0.0
        y = H - ((v - mn) / span) * H + 2
        pts.append(f"{x:.1f},{y:.1f}")
    return " ".join(pts)


def _current_week() -> str:
    d = datetime.utcnow()
    return f"{d.year}-W{d.isocalendar()[1]:02d}"


# ── DB helpers ───────────────────────────────────────────────────────────────

def _user_skills(conn) -> list[dict]:
    row = conn.execute("SELECT skills FROM user_profile WHERE id = 1").fetchone()
    if not row:
        return []
    try:
        return json.loads(row["skills"]) or []
    except Exception:
        return []


def _user_target_role(conn) -> str:
    """Return the user's career focus category, or empty string if not set."""
    row = conn.execute("SELECT target_role FROM user_profile WHERE id = 1").fetchone()
    if not row:
        return ""
    return row["target_role"] or ""


def _job_skills_by_job(company_id: int, conn, target_category: str = "") -> list[list[str]]:
    """Return one skill-list per extracted job for this company, filtered by category if set."""
    if target_category:
        jobs = conn.execute(
            "SELECT id FROM jobs WHERE company_id = ? AND skills_extracted = 1 AND job_category = ?",
            (company_id, target_category),
        ).fetchall()
    else:
        jobs = conn.execute(
            "SELECT id FROM jobs WHERE company_id = ? AND skills_extracted = 1",
            (company_id,),
        ).fetchall()
    result = []
    for job in jobs:
        skills = conn.execute(
            "SELECT skill FROM job_skills WHERE job_id = ?", (job["id"],)
        ).fetchall()
        if skills:
            result.append([s["skill"] for s in skills])
    return result


def _hiring_history(company_id: int, conn, weeks: int = 12) -> list[int]:
    rows = conn.execute(
        "SELECT job_count FROM hiring_history WHERE company_id = ? ORDER BY week",
        (company_id,),
    ).fetchall()
    weekly = [r["job_count"] for r in rows][-weeks:]
    while len(weekly) < weeks:
        weekly.insert(0, 0)
    return weekly


def _upsert_history(company_id: int, job_count: int, conn) -> None:
    week = _current_week()
    exists = conn.execute(
        "SELECT id FROM hiring_history WHERE company_id = ? AND week = ?",
        (company_id, week),
    ).fetchone()
    if exists:
        conn.execute(
            "UPDATE hiring_history SET job_count = ? WHERE company_id = ? AND week = ?",
            (job_count, company_id, week),
        )
    else:
        conn.execute(
            "INSERT INTO hiring_history (company_id, week, job_count) VALUES (?, ?, ?)",
            (company_id, week, job_count),
        )


def _skill_demand(company_id: int, conn, user_skills: list[dict], target_category: str = "") -> list[dict]:
    """Aggregate skill frequency across jobs for a company, filtered by category if set."""
    if target_category:
        jobs = conn.execute(
            "SELECT id FROM jobs WHERE company_id = ? AND job_category = ?",
            (company_id, target_category),
        ).fetchall()
    else:
        jobs = conn.execute(
            "SELECT id FROM jobs WHERE company_id = ?", (company_id,)
        ).fetchall()
    total = len(jobs)
    if total == 0:
        return []

    counts: dict[str, int] = {}
    for job in jobs:
        for s in conn.execute(
            "SELECT skill FROM job_skills WHERE job_id = ?", (job["id"],)
        ).fetchall():
            counts[s["skill"]] = counts.get(s["skill"], 0) + 1

    user_map = {s["name"].lower(): s["level"] for s in user_skills}
    result = []
    for skill, count in sorted(counts.items(), key=lambda x: -x[1]):
        freq = count / total
        req_level = min(100, round(freq * 120))
        my_level = user_map.get(skill.lower(), 0)
        result.append(
            {
                "name": skill,
                "count": count,
                "total": total,
                "freq": freq,
                "demand_pct": round(freq * 100),   # mentions / total jobs (0-100)
                "req_level": req_level,
                "my_level": my_level,
                "you_have": my_level > 0,
            }
        )
    return result


# ── GET /api/companies ───────────────────────────────────────────────────────

@router.get("/companies")
def list_companies():
    with get_db() as conn:
        companies = conn.execute("SELECT * FROM companies ORDER BY name").fetchall()
        user_skills = _user_skills(conn)
        target_category = _user_target_role(conn)

        result = []
        for c in companies:
            cid = c["id"]
            open_roles = conn.execute(
                "SELECT COUNT(*) as cnt FROM jobs WHERE company_id = ?", (cid,)
            ).fetchone()["cnt"]
            new_roles = conn.execute(
                "SELECT COUNT(*) as cnt FROM jobs WHERE company_id = ? AND is_new = 1", (cid,)
            ).fetchone()["cnt"]
            focus_roles = (
                conn.execute(
                    "SELECT COUNT(*) as cnt FROM jobs WHERE company_id = ? AND job_category = ?",
                    (cid, target_category),
                ).fetchone()["cnt"]
                if target_category else open_roles
            )

            all_job_skills = _job_skills_by_job(cid, conn, target_category)
            fit = calculate_company_fit(user_skills, all_job_skills)

            weekly = _hiring_history(cid, conn)
            if open_roles > 0:
                weekly[-1] = open_roles
            vel = _vel_pct(weekly)

            result.append(
                {
                    "id": cid,
                    "name": c["name"],
                    "slug": c["slug"],
                    "sector": c["sector"] or "",
                    "hq": c["hq"] or "",
                    "color": c["color"],
                    "website": c["website"] or "",
                    "career_url": c["career_url"] or "",
                    "open_roles": open_roles,
                    "new_roles": new_roles,
                    "focus_roles": focus_roles,
                    "fit": fit,
                    "fit_color": _fit_color(fit),
                    "spark": _spark_points(weekly),
                    "vel_label": _vel_label(vel),
                    "vel_color": _vel_color(vel),
                    "last_synced": c["last_synced"] or "",
                    "added_date": c["added_date"],
                }
            )

        result.sort(key=lambda x: -x["fit"])
        return result


# ── POST /api/companies ──────────────────────────────────────────────────────

class AddCompanyRequest(BaseModel):
    name: str
    website: Optional[str] = None
    career_url: Optional[str] = None
    sector: Optional[str] = None
    hq: Optional[str] = None
    color: Optional[str] = None


@router.post("/companies", status_code=201)
def add_company(payload: AddCompanyRequest):
    slug = _slugify(payload.name)
    color = payload.color or _pick_color(payload.name)

    with get_db() as conn:
        if conn.execute("SELECT id FROM companies WHERE slug = ?", (slug,)).fetchone():
            raise HTTPException(status_code=409, detail=f'Company "{payload.name}" already exists')

        conn.execute(
            "INSERT INTO companies (name, slug, website, career_url, sector, hq, color) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (payload.name, slug, payload.website, payload.career_url,
             payload.sector, payload.hq, color),
        )
        row = conn.execute("SELECT * FROM companies WHERE slug = ?", (slug,)).fetchone()
        return {
            "id": row["id"],
            "name": row["name"],
            "slug": row["slug"],
            "color": row["color"],
            "sector": row["sector"] or "",
            "hq": row["hq"] or "",
            "website": row["website"] or "",
            "career_url": row["career_url"] or "",
        }


# ── DELETE /api/companies/{id} ───────────────────────────────────────────────

@router.delete("/companies/{company_id}", status_code=204)
def remove_company(company_id: int):
    with get_db() as conn:
        if not conn.execute("SELECT id FROM companies WHERE id = ?", (company_id,)).fetchone():
            raise HTTPException(status_code=404, detail="Company not found")
        conn.execute("DELETE FROM companies WHERE id = ?", (company_id,))


# ── POST /api/companies/{id}/sync ────────────────────────────────────────────

@router.post("/companies/{company_id}/sync")
def sync_company(company_id: int):
    with get_db() as conn:
        company = conn.execute(
            "SELECT * FROM companies WHERE id = ?", (company_id,)
        ).fetchone()
        if not company:
            raise HTTPException(status_code=404, detail="Company not found")

        name = company["name"]
        location = company["hq"] or "Berlin"
        career_url = company["career_url"] or ""
        website = company["website"] or ""

        # Step 1: fetch jobs from Adzuna
        adzuna_jobs = []
        try:
            adzuna_jobs = fetch_jobs(name, location=location)
        except RuntimeError as e:
            log.warning("Adzuna unavailable for %s: %s", name, e)
        except Exception as e:
            log.error("Adzuna error for %s: %s", name, e)

        # Step 1b: ALWAYS try career page scraper for full descriptions.
        # Adzuna truncates descriptions to ~500 chars (marketing blurbs);
        # Greenhouse/Lever APIs return complete job content which Gemini can extract skills from.
        career_page_jobs = []
        try:
            career_page_jobs = scrape_company(
                company_name=name,
                career_url=career_url,
                website=website,
            )
            if career_page_jobs:
                log.info("Career page scraper: %d jobs for %s", len(career_page_jobs), name)
        except Exception as e:
            log.error("Career page scraper error for %s: %s", name, e)

        # Merge: use career page jobs (full descriptions) first; supplement with
        # any Adzuna jobs whose title doesn't appear in the career page results.
        career_title_keys = {j.title.lower().strip() for j in career_page_jobs}
        adzuna_supplement = [
            j for j in adzuna_jobs
            if j.title.lower().strip() not in career_title_keys
        ]
        raw_jobs = career_page_jobs + adzuna_supplement
        if not raw_jobs:
            raw_jobs = list(adzuna_jobs)

        new_count = 0
        for aj in raw_jobs:
            url = aj.url or ""
            desc = aj.description or ""

            # Check by URL first (same source)
            if url:
                existing = conn.execute(
                    "SELECT id, description FROM jobs WHERE url = ?", (url,)
                ).fetchone()
                if existing:
                    if len(desc) > len(existing["description"] or ""):
                        conn.execute(
                            "UPDATE jobs SET description = ?, skills_extracted = 0 WHERE id = ?",
                            (desc, existing["id"]),
                        )
                    continue

            # Check by title (catches cross-source duplicates, e.g. GH + Adzuna same role)
            existing = conn.execute(
                "SELECT id, description FROM jobs WHERE company_id = ? AND title = ?",
                (company_id, aj.title),
            ).fetchone()
            if existing:
                if len(desc) > len(existing["description"] or ""):
                    conn.execute(
                        "UPDATE jobs SET description = ?, skills_extracted = 0 WHERE id = ?",
                        (desc, existing["id"]),
                    )
                continue

            conn.execute(
                "INSERT INTO jobs (company_id, title, location, description, url, "
                "posted_date, is_new, skills_extracted) VALUES (?, ?, ?, ?, ?, ?, 1, 0)",
                (company_id, aj.title, aj.location, desc, url, aj.posted_date),
            )
            new_count += 1

        # Step 2: AI skill extraction (capped to avoid long blocking)
        # Reset the flag for any jobs that previously ran but produced no skills
        # (this happens when descriptions were too short, e.g. Adzuna snippets).
        conn.execute(
            """UPDATE jobs SET skills_extracted = 0
               WHERE company_id = ?
               AND skills_extracted = 1
               AND id NOT IN (SELECT DISTINCT job_id FROM job_skills)""",
            (company_id,),
        )

        unprocessed = conn.execute(
            "SELECT id, title, description FROM jobs "
            "WHERE company_id = ? AND skills_extracted = 0",
            (company_id,),
        ).fetchall()

        extracted_count = 0
        rate_limited = False
        for i, batch_start in enumerate(range(0, len(unprocessed), _SKILL_EXTRACTION_BATCH)):
            if i > 0:
                time.sleep(4)  # avoid Gemini 10 RPM free-tier limit
            batch = unprocessed[batch_start:batch_start + _SKILL_EXTRACTION_BATCH]
            job_texts = [
                f"Job Title: {job['title']}\n\n{job['description'] or ''}".strip()
                for job in batch
            ]
            try:
                batch_results = extract_skills_batch(job_texts)
                for job, (required_skills, preferred_skills, category) in zip(batch, batch_results):
                    if required_skills or preferred_skills:
                        inserts = (
                            [(job["id"], s, 1) for s in required_skills]
                            + [(job["id"], s, 0) for s in preferred_skills]
                        )
                        conn.executemany(
                            "INSERT INTO job_skills (job_id, skill, required) VALUES (?, ?, ?)",
                            inserts,
                        )
                        extracted_count += 1
                    conn.execute(
                        "UPDATE jobs SET skills_extracted = 1, job_category = ? WHERE id = ?",
                        (category, job["id"]),
                    )
            except GeminiRateLimitError as e:
                log.warning(
                    "Gemini rate limit hit for %s — %d/%d jobs extracted, rest retry on next sync: %s",
                    name, extracted_count, len(unprocessed), e,
                )
                rate_limited = True
                break

        # Step 3: update hiring history & last_synced
        total_jobs = conn.execute(
            "SELECT COUNT(*) as cnt FROM jobs WHERE company_id = ?", (company_id,)
        ).fetchone()["cnt"]
        _upsert_history(company_id, total_jobs, conn)

        conn.execute(
            "UPDATE companies SET last_synced = ? WHERE id = ?",
            (datetime.utcnow().isoformat(), company_id),
        )

        # Step 4: generate and cache AI insights
        try:
            user_skills = _user_skills(conn)
            demand = _skill_demand(company_id, conn, user_skills)
            top_skills = [d["name"] for d in demand[:8]]

            recent_titles = [
                r["title"]
                for r in conn.execute(
                    "SELECT title FROM jobs WHERE company_id = ? ORDER BY scraped_date DESC LIMIT 15",
                    (company_id,),
                ).fetchall()
            ]

            all_job_skills = _job_skills_by_job(company_id, conn)
            fit = calculate_company_fit(user_skills, all_job_skills)

            nudge = generate_nudge(name, recent_titles, top_skills)
            summary = generate_summary(name, recent_titles, top_skills, fit, total_jobs)

            conn.execute(
                "INSERT INTO company_insights (company_id, nudge, ai_summary, updated_at) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(company_id) DO UPDATE SET "
                "nudge = excluded.nudge, ai_summary = excluded.ai_summary, "
                "updated_at = excluded.updated_at",
                (company_id, nudge, summary, datetime.utcnow().isoformat()),
            )
        except Exception as e:
            log.warning("Insights generation skipped for %s: %s", name, e)

        # Step 5: generate skill learning tips per category, grounded in job descriptions
        try:
            distinct_cats = conn.execute(
                "SELECT DISTINCT job_category FROM jobs WHERE company_id = ? AND job_category IS NOT NULL AND job_category != ''",
                (company_id,),
            ).fetchall()
            categories_to_tip = [r["job_category"] for r in distinct_cats] + [""]  # "" = all-categories tips

            for cat in categories_to_tip:
                # Compute top 15 skill gaps for this company+category
                if cat:
                    cat_jobs = conn.execute(
                        "SELECT id FROM jobs WHERE company_id = ? AND job_category = ?", (company_id, cat)
                    ).fetchall()
                else:
                    cat_jobs = conn.execute("SELECT id FROM jobs WHERE company_id = ?", (company_id,)).fetchall()

                skill_counts: dict[str, int] = {}
                for j in cat_jobs:
                    for s in conn.execute("SELECT skill FROM job_skills WHERE job_id = ?", (j["id"],)).fetchall():
                        skill_counts[s["skill"]] = skill_counts.get(s["skill"], 0) + 1

                if not skill_counts:
                    continue

                user_map_local = {s["name"].lower(): s["level"] for s in user_skills}
                gap_skills = sorted(
                    [sk for sk in skill_counts if (min(100, round(skill_counts[sk] / len(cat_jobs) * 120)) - user_map_local.get(sk.lower(), 0)) > 5],
                    key=lambda sk: -skill_counts[sk],
                )[:15]

                if not gap_skills:
                    continue

                # Sample job descriptions for context (title + first 300 chars of description)
                sample_jobs = conn.execute(
                    "SELECT title, description FROM jobs WHERE company_id = ? "
                    + ("AND job_category = ? " if cat else "")
                    + "AND description IS NOT NULL AND description != '' LIMIT 8",
                    (company_id, cat) if cat else (company_id,),
                ).fetchall()
                job_samples = [
                    f"{j['title']}: {(j['description'] or '')[:300].strip()}"
                    for j in sample_jobs
                ]

                tips = generate_skill_tips(gap_skills, name, job_samples, cat)
                for skill, tip in tips.items():
                    conn.execute(
                        "INSERT INTO skill_learning_tips (company_id, category, skill, tip, updated_at) "
                        "VALUES (?, ?, ?, ?, ?) "
                        "ON CONFLICT(company_id, category, skill) DO UPDATE SET tip = excluded.tip, updated_at = excluded.updated_at",
                        (company_id, cat, skill, tip, datetime.utcnow().isoformat()),
                    )
                log.info("Generated %d skill tips for %s cat=%r", len(tips), name, cat or "all")
        except Exception as e:
            log.warning("Skill tip generation skipped for %s: %s", name, e)

        source = (
            "career_page+adzuna" if (career_page_jobs and adzuna_jobs)
            else "career_page" if career_page_jobs
            else "adzuna" if adzuna_jobs
            else "none"
        )
        return {
            "jobs_fetched": len(raw_jobs),
            "jobs_new": new_count,
            "jobs_extracted": extracted_count,
            "total_jobs": total_jobs,
            "source": source,
        }


# ── GET /api/companies/{id} ──────────────────────────────────────────────────

@router.get("/companies/{company_id}")
def get_company(company_id: int, category: Optional[str] = None):
    with get_db() as conn:
        company = conn.execute(
            "SELECT * FROM companies WHERE id = ?", (company_id,)
        ).fetchone()
        if not company:
            raise HTTPException(status_code=404, detail="Company not found")

        cid = company["id"]
        color = company["color"]
        user_skills = _user_skills(conn)
        # Per-request category overrides the global profile career focus
        target_category = category if category is not None else _user_target_role(conn)

        # Jobs & fit
        jobs = conn.execute(
            "SELECT * FROM jobs WHERE company_id = ? ORDER BY scraped_date DESC", (cid,)
        ).fetchall()
        all_job_skills = _job_skills_by_job(cid, conn, target_category)
        fit = calculate_company_fit(user_skills, all_job_skills)
        open_roles = len(jobs)
        new_roles = sum(1 for j in jobs if j["is_new"])

        # Velocity bars
        weekly = _hiring_history(cid, conn)
        if open_roles > 0:
            weekly[-1] = open_roles
        vel = _vel_pct(weekly)
        bar_max = max(weekly) or 1
        bars = [
            {
                "value": v,
                "wk": f"w{i + 1}",
                "h": max(6, round(v / bar_max * 116)),
                "fill": color if i == len(weekly) - 1 else "#dfe8e2",
                "label_op": 1 if i == len(weekly) - 1 else 0,
            }
            for i, v in enumerate(weekly)
        ]

        # Skill demand (filtered by career focus)
        demand = _skill_demand(cid, conn, user_skills, target_category)

        skills_in_demand = [
            {
                "name": d["name"],
                "w": d["demand_pct"],          # bar width = mentions / total jobs %
                "demand_pct": d["demand_pct"],
                "fill": color,
                "you_have": d["you_have"],
                "trend": "—",
                "trend_color": "#9a9488",
            }
            for d in demand[:10]
        ]

        # Open roles with per-role match %
        roles_out = []
        for job in jobs:
            job_skill_list = [
                s["skill"]
                for s in conn.execute(
                    "SELECT skill FROM job_skills WHERE job_id = ?", (job["id"],)
                ).fetchall()
            ]
            match = calculate_fit(user_skills, job_skill_list) if job_skill_list else 0
            gaps = skill_gap(user_skills, job_skill_list)
            nudge = f"Closest gap · {gaps[0]}" if gaps and match < 80 else ""
            cat = job["job_category"] or ""
            in_focus = (not target_category) or (cat == target_category)
            roles_out.append(
                {
                    "id": job["id"],
                    "title": job["title"],
                    "location": job["location"] or "",
                    "posted_date": job["posted_date"] or "",
                    "is_new": bool(job["is_new"]),
                    "url": job["url"] or "",
                    "match": match,
                    "match_color": _fit_color(match),
                    "nudge": nudge,
                    "category": cat,
                    "in_focus": in_focus,
                }
            )
        roles_out.sort(key=lambda r: -r["match"])

        # Skill breakdown (top 7 for fit card)
        breakdown = []
        for d in demand[:7]:
            you_have = d["you_have"]
            tag = "you have it" if you_have else "not in profile"
            col = "#15604a" if you_have else "#b1493a"
            bg = "#e7f0ea" if you_have else "#f5e5e1"
            border = "#cfe2d6" if you_have else "#f0cbc5"
            breakdown.append(
                {
                    "name": d["name"],
                    "color": col,
                    "bg": bg,
                    "border": border,
                    "tag": tag,
                    "you_have": you_have,
                    "demand_pct": d["demand_pct"],
                    "demand_w": d["demand_pct"],  # bar width = demand %
                    "bar_color": col,
                }
            )

        # SVG ring params
        C = 2 * math.pi * 52
        ring = {"circ": round(C, 1), "offset": round(C * (1 - fit / 100), 1)}

        # What to learn next (per company, top 3 gaps)
        recs = []
        for d in sorted(demand, key=lambda x: -(x["req_level"] - x["my_level"]) * x["count"])[:5]:
            gap_size = d["req_level"] - d["my_level"]
            if gap_size <= 4:
                continue
            # Estimate fit gain
            boosted = [
                {**s, "level": d["req_level"]} if s["name"].lower() == d["name"].lower() else s
                for s in user_skills
            ]
            if not any(s["name"].lower() == d["name"].lower() for s in user_skills):
                boosted = user_skills + [{"name": d["name"], "level": d["req_level"]}]
            gain = max(1, calculate_company_fit(boosted, all_job_skills) - fit)
            recs.append(
                {
                    "skill": d["name"],
                    "gain": gain,
                    "level_w": min(100, d["my_level"]),
                    "target_w": min(100, d["req_level"]),
                    "detail": f"now {d['my_level']} → target {d['req_level']}",
                }
            )
            if len(recs) == 3:
                break

        # AI nudge + summary (cached or fallback)
        insight_row = conn.execute(
            "SELECT nudge, ai_summary FROM company_insights WHERE company_id = ?", (cid,)
        ).fetchone()
        skill_str = demand[0]["name"] if demand else "technical skills"
        nudge = (
            (insight_row["nudge"] if insight_row and insight_row["nudge"] else None)
            or f"{company['name']} is actively hiring — strong demand for {skill_str}."
        )
        ai_summary = (
            (insight_row["ai_summary"] if insight_row and insight_row["ai_summary"] else None)
            or ""
        )

        fit_label = (
            "Strong match" if fit >= 70
            else "Promising — close some gaps" if fit >= 45
            else "Stretch role"
        )
        fit_note = (
            "You clear most requirements. Apply and lead with your strengths."
            if fit >= 70
            else "A few focused skills would make you very competitive here."
            if fit >= 45
            else "Worth a 6–12 month plan — see what to learn next."
        )

        focus_roles = sum(1 for j in jobs if j["job_category"] == target_category) if target_category else open_roles

        # Available job categories for this company (for the in-page department filter)
        cat_rows = conn.execute(
            "SELECT job_category, COUNT(*) as cnt FROM jobs "
            "WHERE company_id = ? AND job_category IS NOT NULL AND job_category != '' "
            "GROUP BY job_category ORDER BY cnt DESC",
            (cid,),
        ).fetchall()
        available_categories = [{"name": r["job_category"], "count": r["cnt"]} for r in cat_rows]

        return {
            "id": cid,
            "name": company["name"],
            "slug": company["slug"],
            "sector": company["sector"] or "",
            "hq": company["hq"] or "",
            "color": color,
            "website": company["website"] or "",
            "career_url": company["career_url"] or "",
            "last_synced": company["last_synced"] or "",
            "open_roles": open_roles,
            "new_roles": new_roles,
            "focus_roles": focus_roles,
            "focus_active": bool(target_category),
            "target_category": target_category,
            "fit": fit,
            "fit_color": _fit_color(fit),
            "fit_label": fit_label,
            "fit_note": fit_note,
            "nudge": nudge,
            "ai_summary": ai_summary,
            "vel_label": _vel_label(vel),
            "vel_color": _vel_color(vel),
            "spark": _spark_points(weekly),
            "ring": ring,
            "bars": bars,
            "skills": skills_in_demand,
            "roles": roles_out,
            "breakdown": breakdown,
            "recs": recs,
            "stats": [
                {
                    "label": "OPEN ROLES",
                    "value": str(open_roles),
                    "delta": _vel_label(vel) + " / 12w",
                    "delta_color": _vel_color(vel),
                    "sub": "actively hiring",
                    "color": "#1b1a17",
                },
                {
                    "label": "NEW SINCE LAST VISIT",
                    "value": str(new_roles),
                    "delta": "",
                    "delta_color": "#b1493a",
                    "sub": "recently posted",
                    "color": "#b1493a",
                },
                {
                    "label": "YOUR FIT",
                    "value": f"{fit}%",
                    "delta": "",
                    "delta_color": "#7a756a",
                    "sub": fit_label.lower(),
                    "color": _fit_color(fit),
                },
            ],
            "available_categories": available_categories,
            "active_category": target_category,
        }
