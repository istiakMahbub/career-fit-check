import json
import logging
import os
import time
from contextlib import asynccontextmanager

from typing import Optional

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from fastapi import HTTPException
from pydantic import BaseModel

from db.database import get_db, init_db
from ai.fit_calculator import calculate_company_fit, calculate_fit, skill_gap
from ai.insights import generate_learn_headline
from ai.resume_tailor import tailor_resume, write_cover_letter
from routers import companies, jobs, profile, github, applications

# 5-minute in-memory cache for the learn headline (avoids redundant Gemini calls)
_learn_headline_cache: dict = {"text": "", "ts": 0.0, "key": ""}
_LEARN_CACHE_TTL = 300

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
)
log = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs(TEMPLATES_DIR, exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    log.info("Database ready")
    yield


app = FastAPI(title="Career Fit Check", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── API routers ───────────────────────────────────────────────────────────────

app.include_router(companies.router, prefix="/api")
app.include_router(profile.router, prefix="/api")
app.include_router(jobs.router, prefix="/api")
app.include_router(github.router, prefix="/api")
app.include_router(applications.router, prefix="/api")


# ── GET /api/stats ────────────────────────────────────────────────────────────

@app.get("/api/stats")
def get_stats():
    with get_db() as conn:
        company_rows = conn.execute("SELECT id FROM companies").fetchall()
        total_jobs = conn.execute("SELECT COUNT(*) as c FROM jobs").fetchone()["c"]
        new_jobs = conn.execute(
            "SELECT COUNT(*) as c FROM jobs WHERE is_new = 1"
        ).fetchone()["c"]

        profile_row = conn.execute(
            "SELECT skills, target_role FROM user_profile WHERE id = 1"
        ).fetchone()
        user_skills = (
            json.loads(profile_row["skills"])
            if profile_row and profile_row["skills"]
            else []
        )
        target_role = (profile_row["target_role"] or "") if profile_row else ""

        fits = []
        for c in company_rows:
            if target_role:
                job_rows = conn.execute(
                    "SELECT id FROM jobs WHERE company_id = ? AND skills_extracted = 1 AND job_category = ?",
                    (c["id"], target_role),
                ).fetchall()
            else:
                job_rows = conn.execute(
                    "SELECT id FROM jobs WHERE company_id = ? AND skills_extracted = 1",
                    (c["id"],),
                ).fetchall()
            per_job = []
            for j in job_rows:
                skills = [
                    s["skill"]
                    for s in conn.execute(
                        "SELECT skill FROM job_skills WHERE job_id = ?", (j["id"],)
                    ).fetchall()
                ]
                if skills:
                    per_job.append(skills)
            if per_job:
                fits.append(calculate_company_fit(user_skills, per_job))

        avg_fit = round(sum(fits) / len(fits)) if fits else 0

        return {
            "total_jobs": total_jobs,
            "new_jobs": new_jobs,
            "avg_fit": avg_fit,
            "companies_tracked": len(company_rows),
            "target_role": target_role,
        }


# ── GET /api/compare ──────────────────────────────────────────────────────────

@app.get("/api/compare")
def compare(ids: str = "", category: Optional[str] = Query(None)):
    """
    Compare skill demand across multiple companies.
    ?ids=1,2,3&category=Data+%26+ML   (category optional; defaults to profile target_role)
    """
    if not ids.strip():
        return {"companies": [], "rows": [], "verdict": "Select companies to compare.",
                "available_categories": [], "active_category": ""}

    try:
        company_ids = [int(x) for x in ids.split(",") if x.strip()]
    except ValueError:
        return {"companies": [], "rows": [], "verdict": "Invalid ids parameter.",
                "available_categories": [], "active_category": ""}

    with get_db() as conn:
        profile_row = conn.execute(
            "SELECT skills, target_role FROM user_profile WHERE id = 1"
        ).fetchone()
        user_skills = (
            json.loads(profile_row["skills"])
            if profile_row and profile_row["skills"]
            else []
        )
        # category param overrides profile target_role for this request
        effective_category = category if category is not None else (
            (profile_row["target_role"] or "") if profile_row else ""
        )
        user_skill_names = {s["name"].lower() for s in user_skills}

        # Available categories across all selected companies
        if company_ids:
            placeholders = ",".join("?" * len(company_ids))
            cat_rows = conn.execute(
                f"SELECT DISTINCT job_category FROM jobs "
                f"WHERE company_id IN ({placeholders}) AND job_category IS NOT NULL AND job_category != '' "
                f"ORDER BY job_category",
                company_ids,
            ).fetchall()
            available_categories = [r["job_category"] for r in cat_rows]
        else:
            available_categories = []

        companies_data = []
        all_skill_sets: dict[str, set[int]] = {}  # skill → set of company_ids that need it

        for cid in company_ids:
            row = conn.execute("SELECT * FROM companies WHERE id = ?", (cid,)).fetchone()
            if not row:
                continue

            if effective_category:
                jobs = conn.execute(
                    "SELECT id FROM jobs WHERE company_id = ? AND job_category = ?",
                    (cid, effective_category),
                ).fetchall()
            else:
                jobs = conn.execute(
                    "SELECT id FROM jobs WHERE company_id = ?", (cid,)
                ).fetchall()

            skill_counts: dict[str, int] = {}
            for job in jobs:
                for s in conn.execute(
                    "SELECT skill FROM job_skills WHERE job_id = ?", (job["id"],)
                ).fetchall():
                    skill_counts[s["skill"]] = skill_counts.get(s["skill"], 0) + 1

            # per-job skill lists for fit calc
            per_job = []
            for job in jobs:
                sl = [
                    s["skill"]
                    for s in conn.execute(
                        "SELECT skill FROM job_skills WHERE job_id = ? ", (job["id"],)
                    ).fetchall()
                ]
                if sl:
                    per_job.append(sl)

            fit = calculate_company_fit(user_skills, per_job)
            open_roles = len(jobs)

            fit_color = "#15604a" if fit >= 70 else "#b9791f" if fit >= 45 else "#b1493a"
            companies_data.append(
                {
                    "id": cid,
                    "name": row["name"],
                    "short": row["name"][:12],
                    "initials": row["name"][:2].upper(),
                    "color": row["color"],
                    "fit": fit,
                    "fit_color": fit_color,
                    "open_roles": open_roles,
                }
            )

            # Track which companies need each skill (presence only — no demand score)
            for skill in skill_counts:
                if skill not in all_skill_sets:
                    all_skill_sets[skill] = set()
                all_skill_sets[skill].add(cid)

        # Build matrix rows — sorted by coverage (most universal first), no cap
        n_selected = len(company_ids)
        rows = []
        for skill, company_set in sorted(
            all_skill_sets.items(), key=lambda x: -len(x[1])
        ):
            coverage = len(company_set)
            i_have = skill.lower() in user_skill_names
            cells = [{"present": cid in company_set} for cid in company_ids]
            rows.append({
                "skill": skill,
                "coverage": coverage,
                "coverage_label": f"{coverage}/{n_selected}",
                "i_have": i_have,
                "cells": cells,
            })

        # Verdict: highlight universal gaps first
        universal_gaps = [
            skill for skill, s in sorted(all_skill_sets.items(), key=lambda x: -len(x[1]))
            if len(s) == n_selected and skill.lower() not in user_skill_names
        ]
        if universal_gaps:
            focus_suffix = f" in {effective_category}" if effective_category else ""
            verdict = (
                f"{universal_gaps[0]} is needed across all {n_selected} selected "
                f"{'company' if n_selected == 1 else 'companies'}{focus_suffix} "
                f"— highest-priority gap to close."
            )
        elif companies_data:
            best = max(companies_data, key=lambda c: c["fit"])
            verdict = f"Your strongest match is {best['name']} at {best['fit']}%."
        else:
            verdict = "Select companies to compare."

        return {
            "companies": companies_data,
            "rows": rows,
            "verdict": verdict,
            "available_categories": available_categories,
            "active_category": effective_category,
        }


# ── GET /api/learn ────────────────────────────────────────────────────────────

@app.get("/api/learn")
def learn(
    company_id: Optional[int] = Query(None),
    category: Optional[str] = Query(None),
):
    """
    Return ranked skill gaps.
    Optionally filtered by company (company_id) and/or job category.
    Category param overrides the profile career-focus setting for this request.
    Returns ALL skills with a gap — no cap.
    """
    with get_db() as conn:
        profile_row = conn.execute(
            "SELECT skills, target_role FROM user_profile WHERE id = 1"
        ).fetchone()
        user_skills = (
            json.loads(profile_row["skills"])
            if profile_row and profile_row["skills"]
            else []
        )
        user_map = {s["name"].lower(): s["level"] for s in user_skills}
        # category param overrides the profile target_role for this request
        effective_category = category if category is not None else (
            (profile_row["target_role"] or "") if profile_row else ""
        )

        all_company_rows = conn.execute("SELECT id, name, color FROM companies ORDER BY name").fetchall()
        if not all_company_rows:
            return {
                "headline": "Add companies to get personalised recommendations.",
                "stats": [], "recs": [],
                "active_company_id": None, "active_category": effective_category,
                "available_companies": [], "available_categories": [],
            }

        available_companies = [
            {"id": c["id"], "name": c["name"], "color": c["color"]}
            for c in all_company_rows
        ]

        # Apply company filter
        filtered_companies = [c for c in all_company_rows if company_id is None or c["id"] == company_id]
        n_companies = len(filtered_companies)

        # Available categories across the filtered company set
        if filtered_companies:
            placeholders = ",".join("?" * len(filtered_companies))
            ids = [c["id"] for c in filtered_companies]
            cat_rows = conn.execute(
                f"SELECT DISTINCT job_category FROM jobs "
                f"WHERE company_id IN ({placeholders}) AND job_category IS NOT NULL AND job_category != '' "
                f"ORDER BY job_category",
                ids,
            ).fetchall()
            available_categories = [r["job_category"] for r in cat_rows]
        else:
            available_categories = []

        # Aggregate skill demand across filtered companies + category
        agg: dict[str, dict] = {}
        for c in filtered_companies:
            if effective_category:
                jobs = conn.execute(
                    "SELECT id FROM jobs WHERE company_id = ? AND job_category = ?",
                    (c["id"], effective_category),
                ).fetchall()
            else:
                jobs = conn.execute(
                    "SELECT id FROM jobs WHERE company_id = ?", (c["id"],)
                ).fetchall()
            total = len(jobs)
            if total == 0:
                continue

            skill_counts: dict[str, int] = {}
            for job in jobs:
                for s in conn.execute(
                    "SELECT skill FROM job_skills WHERE job_id = ?", (job["id"],)
                ).fetchall():
                    skill_counts[s["skill"]] = skill_counts.get(s["skill"], 0) + 1

            for skill, count in skill_counts.items():
                freq = count / total
                req_level = min(100, round(freq * 120))
                if skill not in agg:
                    agg[skill] = {"name": skill, "req_level": req_level, "companies": set(), "gap_weight": 0}
                a = agg[skill]
                a["req_level"] = max(a["req_level"], req_level)
                a["companies"].add(c["id"])
                my_level = user_map.get(skill.lower(), 0)
                a["gap_weight"] += max(0, req_level - my_level) * count

        # Rank by gap_weight × company coverage — no cap, return all gaps
        candidates = [
            v for v in agg.values()
            if (v["req_level"] - user_map.get(v["name"].lower(), 0)) > 5
        ]
        candidates.sort(key=lambda x: -(x["gap_weight"] * len(x["companies"])))

        # Per-job fit stats for gain estimates
        all_per_job = []
        for c in filtered_companies:
            if effective_category:
                jobs = conn.execute(
                    "SELECT id FROM jobs WHERE company_id = ? AND skills_extracted = 1 AND job_category = ?",
                    (c["id"], effective_category),
                ).fetchall()
            else:
                jobs = conn.execute(
                    "SELECT id FROM jobs WHERE company_id = ? AND skills_extracted = 1",
                    (c["id"],),
                ).fetchall()
            for j in jobs:
                sl = [s["skill"] for s in conn.execute(
                    "SELECT skill FROM job_skills WHERE job_id = ?", (j["id"],)
                ).fetchall()]
                if sl:
                    all_per_job.append(sl)

        from ai.fit_calculator import calculate_fit
        fits = [calculate_fit(user_skills, sl) for sl in all_per_job] if all_per_job else []
        avg_fit = round(sum(fits) / len(fits)) if fits else 0

        top = candidates[0] if candidates else None
        gain_from_top = 0
        if top and all_per_job:
            boosted = [{**s, "level": top["req_level"]} if s["name"].lower() == top["name"].lower() else s for s in user_skills]
            if not any(s["name"].lower() == top["name"].lower() for s in user_skills):
                boosted = user_skills + [{"name": top["name"], "level": top["req_level"]}]
            new_avg = round(sum(calculate_fit(boosted, sl) for sl in all_per_job) / len(all_per_job))
            gain_from_top = max(0, new_avg - avg_fit)

        top_gap_names = [c["name"] for c in candidates[:4]]
        cache_key = f"{company_id}:{effective_category}:{','.join(top_gap_names)}:{avg_fit}"
        now = time.time()
        if _learn_headline_cache["key"] == cache_key and now - _learn_headline_cache["ts"] < _LEARN_CACHE_TTL:
            headline = _learn_headline_cache["text"]
        else:
            try:
                headline = generate_learn_headline(top_gap_names, avg_fit, n_companies)
            except Exception:
                headline = (
                    f"Focus on {top_gap_names[0]} next — highest-leverage gap in your watchlist."
                    if top_gap_names else "Keep your core skills sharp across your watchlist."
                )
            _learn_headline_cache.update({"text": headline, "ts": now, "key": cache_key})

        # Fetch cached learning tips for filtered company + category
        tip_map: dict[str, str] = {}
        if company_id is not None:
            tip_rows = conn.execute(
                "SELECT skill, tip FROM skill_learning_tips WHERE company_id = ? AND category = ?",
                (company_id, effective_category or ""),
            ).fetchall()
            tip_map = {r["skill"]: r["tip"] for r in tip_rows}
            # Also pull all-category tips as fallback
            if not tip_map:
                tip_rows = conn.execute(
                    "SELECT skill, tip FROM skill_learning_tips WHERE company_id = ? AND category = ''",
                    (company_id,),
                ).fetchall()
                tip_map = {r["skill"]: r["tip"] for r in tip_rows}

        # Batch-fetch job titles per skill so the frontend can show WHY IN DEMAND
        skill_titles_map: dict[str, list[str]] = {}
        if filtered_companies and candidates:
            skill_names_list = list({a["name"] for a in candidates})
            placeholders_c = ",".join("?" * len(filtered_companies))
            placeholders_s = ",".join("?" * len(skill_names_list))
            fc_ids = [c["id"] for c in filtered_companies]
            if effective_category:
                title_rows = conn.execute(
                    f"SELECT DISTINCT js.skill, j.title FROM jobs j "
                    f"JOIN job_skills js ON js.job_id = j.id "
                    f"WHERE j.company_id IN ({placeholders_c}) AND j.job_category = ? "
                    f"AND js.skill IN ({placeholders_s})",
                    fc_ids + [effective_category] + skill_names_list,
                ).fetchall()
            else:
                title_rows = conn.execute(
                    f"SELECT DISTINCT js.skill, j.title FROM jobs j "
                    f"JOIN job_skills js ON js.job_id = j.id "
                    f"WHERE j.company_id IN ({placeholders_c}) "
                    f"AND js.skill IN ({placeholders_s})",
                    fc_ids + skill_names_list,
                ).fetchall()
            for trow in title_rows:
                sn = trow["skill"]
                if sn not in skill_titles_map:
                    skill_titles_map[sn] = []
                if len(skill_titles_map[sn]) < 5 and trow["title"] not in skill_titles_map[sn]:
                    skill_titles_map[sn].append(trow["title"])

        recs = []
        for i, a in enumerate(candidates):  # no cap — return every gap
            my_level = user_map.get(a["name"].lower(), 0)
            n_cos = len(a["companies"])
            tag = "HIGH LEVERAGE" if n_cos >= max(2, n_companies // 2) else "BROADLY WANTED" if n_cos >= 2 else "TARGETED"
            tag_color = "#b1493a" if tag == "HIGH LEVERAGE" else "#9a7c33"
            tag_bg = "#f5e5e1" if tag == "HIGH LEVERAGE" else "#f7edda"
            if all_per_job:
                boosted = [{**s, "level": a["req_level"]} if s["name"].lower() == a["name"].lower() else s for s in user_skills]
                if not any(s["name"].lower() == a["name"].lower() for s in user_skills):
                    boosted = user_skills + [{"name": a["name"], "level": a["req_level"]}]
                gain = max(1, round(sum(calculate_fit(boosted, sl) for sl in all_per_job) / len(all_per_job)) - avg_fit)
            else:
                gain = 1
            tip = tip_map.get(a["name"]) or ""
            in_profile = my_level > 0
            gap_pts = a["req_level"] - my_level
            jobs_requiring = skill_titles_map.get(a["name"], [])
            recs.append({
                "rank": i + 1,
                "skill": a["name"],
                "level": my_level,
                "target": a["req_level"],
                "level_w": min(100, my_level),
                "target_w": min(100, a["req_level"]),
                "gain": gain,
                "companies": n_cos,
                "tag": tag,
                "tag_color": tag_color,
                "tag_bg": tag_bg,
                "rank_bg": "#15604a" if i == 0 else "#f0ece3",
                "rank_color": "#fff" if i == 0 else "#7a756a",
                "why": f"{n_cos} of {n_companies} tracked {'company' if n_companies == 1 else 'companies'} ask for it",
                "tip": tip,
                "in_profile": in_profile,
                "gap_pts": gap_pts,
                "jobs_requiring": jobs_requiring,
            })

        return {
            "headline": headline,
            "stats": [
                {"value": str(len(candidates)), "label": "skill gaps detected"},
                {"value": f"+{gain_from_top}%", "label": "fit from top pick"},
                {"value": f"{avg_fit}%", "label": "current avg fit"},
            ],
            "recs": recs,
            "active_company_id": company_id,
            "active_category": effective_category,
            "available_companies": available_companies,
            "available_categories": available_categories,
        }


# ── POST /api/ats-score ───────────────────────────────────────────────────────

class ATSScoreRequest(BaseModel):
    job_id: int
    resume_text: str


@app.post("/api/ats-score")
def ats_score(payload: ATSScoreRequest):
    """
    Score a resume against a specific job's extracted keywords.
    Returns score % + matched/missing breakdown by required vs preferred.
    required skills are weighted 2× in the score (mirrors real ATS weighting).
    """
    if not payload.resume_text.strip():
        raise HTTPException(status_code=400, detail="resume_text is required")

    with get_db() as conn:
        job = conn.execute(
            "SELECT title FROM jobs WHERE id = ?", (payload.job_id,)
        ).fetchone()
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        skill_rows = conn.execute(
            "SELECT skill, required FROM job_skills WHERE job_id = ?",
            (payload.job_id,),
        ).fetchall()

    if not skill_rows:
        return {
            "score": 0,
            "required_matched": [], "required_missing": [],
            "preferred_matched": [], "preferred_missing": [],
            "total_required": 0, "total_preferred": 0,
            "resume_keywords_detected": 0,
            "warning": "No skills extracted for this job yet — sync the company first.",
        }

    required_skills = [r["skill"] for r in skill_rows if r["required"] == 1]
    preferred_skills = [r["skill"] for r in skill_rows if r["required"] == 0]

    # Literal keyword search — exactly how real ATS works.
    # No AI needed on the resume side: check if each job keyword appears
    # as a word/phrase in the resume text (case-insensitive).
    resume_lower = payload.resume_text.lower()

    def _keyword_in_resume(kw: str) -> bool:
        kw_l = kw.lower()
        idx = resume_lower.find(kw_l)
        if idx == -1:
            return False
        # Word-boundary guard: char before and after must not be alphanumeric
        before_ok = idx == 0 or not resume_lower[idx - 1].isalnum()
        after_idx = idx + len(kw_l)
        after_ok = after_idx >= len(resume_lower) or not resume_lower[after_idx].isalnum()
        return before_ok and after_ok

    req_matched = [s for s in required_skills if _keyword_in_resume(s)]
    req_missing = [s for s in required_skills if not _keyword_in_resume(s)]
    pref_matched = [s for s in preferred_skills if _keyword_in_resume(s)]
    pref_missing = [s for s in preferred_skills if not _keyword_in_resume(s)]

    # ATS score: required 2×, preferred 1×
    total_weight = len(required_skills) * 2 + len(preferred_skills)
    matched_weight = len(req_matched) * 2 + len(pref_matched)
    score = round((matched_weight / total_weight) * 100) if total_weight > 0 else 0

    all_job_skills = required_skills + preferred_skills
    resume_keywords_detected = sum(1 for s in all_job_skills if _keyword_in_resume(s))

    return {
        "score": score,
        "required_matched": sorted(req_matched),
        "required_missing": sorted(req_missing),
        "preferred_matched": sorted(pref_matched),
        "preferred_missing": sorted(pref_missing),
        "total_required": len(required_skills),
        "total_preferred": len(preferred_skills),
        "resume_keywords_detected": resume_keywords_detected,
    }


# ── POST /api/tailor ──────────────────────────────────────────────────────────

class TailorRequest(BaseModel):
    job_id: int
    tone: str = "Professional"
    length: str = "Standard"
    lead_with: list[str] = []


@app.post("/api/tailor")
def tailor(payload: TailorRequest):
    with get_db() as conn:
        job = conn.execute(
            "SELECT j.*, c.name as company_name, c.color as company_color "
            "FROM jobs j JOIN companies c ON c.id = j.company_id WHERE j.id = ?",
            (payload.job_id,),
        ).fetchone()
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        profile_row = conn.execute(
            "SELECT name, role, skills FROM user_profile WHERE id = 1"
        ).fetchone()
        user_skills = json.loads(profile_row["skills"] or "[]") if profile_row else []

        required_skills = [
            r["skill"]
            for r in conn.execute(
                "SELECT skill FROM job_skills WHERE job_id = ?", (payload.job_id,)
            ).fetchall()
        ]

        fit = calculate_fit(user_skills, required_skills) if required_skills else 0

        # Default lead_with: user skills that overlap with job requirements
        if payload.lead_with:
            lead_with = payload.lead_with
        else:
            user_names = {s["name"].lower() for s in user_skills}
            lead_with = [s for s in required_skills if s.lower() in user_names][:6]
            if not lead_with:
                lead_with = [s["name"] for s in sorted(user_skills, key=lambda x: -x["level"])[:4]]

    role_title = job["title"]
    company_name = job["company_name"]
    user_name = profile_row["name"] if profile_row else "Candidate"
    user_role = profile_row["role"] if profile_row else "Professional"

    tone = payload.tone if payload.tone in ("Professional", "Confident", "Concise") else "Professional"
    length = payload.length if payload.length in ("Brief", "Standard", "Detailed") else "Standard"

    resume_text = tailor_resume(
        role_title=role_title,
        company_name=company_name,
        required_skills=required_skills,
        user_name=user_name,
        user_role=user_role,
        user_skills=user_skills,
        lead_with=lead_with,
        tone=tone,
        length=length,
    )
    cover_text = write_cover_letter(
        role_title=role_title,
        company_name=company_name,
        required_skills=required_skills,
        user_name=user_name,
        user_role=user_role,
        user_skills=user_skills,
        fit=fit,
        tone=tone,
        length=length,
    )

    return {
        "job_id": payload.job_id,
        "job_title": role_title,
        "company_name": company_name,
        "company_color": job["company_color"],
        "fit": fit,
        "required_skills": required_skills,
        "lead_with": lead_with,
        "resume": resume_text,
        "cover_letter": cover_text,
    }


# ── Static files & SPA fallback ───────────────────────────────────────────────

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def serve_index():
    index = os.path.join(TEMPLATES_DIR, "index.html")
    if os.path.exists(index):
        return FileResponse(index)
    return {"message": "Career Fit Check API", "docs": "/docs"}
