import json
import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from db.database import get_db, init_db
from ai.fit_calculator import calculate_company_fit
from ai.insights import generate_learn_headline
from routers import companies, jobs, profile, github

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
            "SELECT skills FROM user_profile WHERE id = 1"
        ).fetchone()
        user_skills = (
            json.loads(profile_row["skills"])
            if profile_row and profile_row["skills"]
            else []
        )

        fits = []
        for c in company_rows:
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
        }


# ── GET /api/compare ──────────────────────────────────────────────────────────

@app.get("/api/compare")
def compare(ids: str = ""):
    """
    Compare skill demand across multiple companies.
    ?ids=1,2,3
    """
    if not ids.strip():
        return {"companies": [], "rows": [], "verdict": "Select companies to compare."}

    try:
        company_ids = [int(x) for x in ids.split(",") if x.strip()]
    except ValueError:
        return {"companies": [], "rows": [], "verdict": "Invalid ids parameter."}

    with get_db() as conn:
        profile_row = conn.execute(
            "SELECT skills FROM user_profile WHERE id = 1"
        ).fetchone()
        user_skills = (
            json.loads(profile_row["skills"])
            if profile_row and profile_row["skills"]
            else []
        )
        user_map = {s["name"].lower(): s["level"] for s in user_skills}

        companies_data = []
        all_skill_sets: dict[str, dict[int, int]] = {}  # skill → {company_id: req_level}

        for cid in company_ids:
            row = conn.execute("SELECT * FROM companies WHERE id = ?", (cid,)).fetchone()
            if not row:
                continue

            jobs = conn.execute(
                "SELECT id FROM jobs WHERE company_id = ?", (cid,)
            ).fetchall()
            total = len(jobs)
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
            open_roles = conn.execute(
                "SELECT COUNT(*) as c FROM jobs WHERE company_id = ?", (cid,)
            ).fetchone()["c"]

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

            # Build skill demand map for matrix
            for skill, count in skill_counts.items():
                freq = count / total if total else 0
                req_level = min(100, round(freq * 120))
                if skill not in all_skill_sets:
                    all_skill_sets[skill] = {}
                all_skill_sets[skill][cid] = req_level

        # Build comparison matrix rows (only skills demanded by ≥1 company)
        rows = []
        for skill, company_reqs in sorted(
            all_skill_sets.items(), key=lambda x: -sum(x[1].values())
        )[:15]:
            my_level = user_map.get(skill.lower(), 0)
            cells = []
            for cid in company_ids:
                req = company_reqs.get(cid, 0)
                if not req:
                    cells.append(
                        {"txt": "—", "color": "#bcb6aa", "bg": "transparent",
                         "dot": "transparent", "dot_op": 0}
                    )
                    continue
                ratio = my_level / req if req else 0
                if ratio >= 1.0:
                    st, dot, bg, color = "meet", "#15604a", "#e7f0ea", "#15604a"
                elif ratio >= 0.6:
                    st, dot, bg, color = "close", "#b9791f", "#f7edda", "#9a7c33"
                else:
                    st, dot, bg, color = "gap", "#b1493a", "#f5e5e1", "#b1493a"
                cells.append(
                    {"txt": str(req), "color": color, "bg": bg, "dot": dot, "dot_op": 1}
                )
            rows.append(
                {"skill": skill, "my": my_level, "my_w": min(100, my_level), "cells": cells}
            )

        # Verdict
        best = max(companies_data, key=lambda c: c["fit"]) if companies_data else None
        verdict = (
            f"Your strongest match is {best['name']} at {best['fit']}%."
            if best
            else "Select companies to compare."
        )

        return {"companies": companies_data, "rows": rows, "verdict": verdict}


# ── GET /api/learn ────────────────────────────────────────────────────────────

@app.get("/api/learn")
def learn():
    """Return ranked skill gaps across all companies."""
    with get_db() as conn:
        profile_row = conn.execute(
            "SELECT skills FROM user_profile WHERE id = 1"
        ).fetchone()
        user_skills = (
            json.loads(profile_row["skills"])
            if profile_row and profile_row["skills"]
            else []
        )
        user_map = {s["name"].lower(): s["level"] for s in user_skills}

        company_rows = conn.execute("SELECT id, name FROM companies").fetchall()
        if not company_rows:
            return {"headline": "Add companies to get personalised recommendations.", "stats": [], "recs": []}

        # Aggregate skill demand across all companies
        agg: dict[str, dict] = {}
        for c in company_rows:
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
                    agg[skill] = {
                        "name": skill,
                        "req_level": req_level,
                        "company_count": 0,
                        "companies": set(),
                        "gap_weight": 0,
                    }
                a = agg[skill]
                a["req_level"] = max(a["req_level"], req_level)
                a["companies"].add(c["id"])
                my_level = user_map.get(skill.lower(), 0)
                gap = max(0, req_level - my_level)
                a["gap_weight"] += gap * count

        # Filter to skills with actual gap, rank by gap_weight × company coverage
        n_companies = len(company_rows)
        candidates = [
            v for v in agg.values()
            if (v["req_level"] - user_map.get(v["name"].lower(), 0)) > 5
        ]
        candidates.sort(key=lambda x: -(x["gap_weight"] * len(x["companies"])))

        # Global fit stats
        all_per_job = []
        for c in company_rows:
            jobs = conn.execute(
                "SELECT id FROM jobs WHERE company_id = ? AND skills_extracted = 1",
                (c["id"],),
            ).fetchall()
            for j in jobs:
                sl = [
                    s["skill"]
                    for s in conn.execute(
                        "SELECT skill FROM job_skills WHERE job_id = ?", (j["id"],)
                    ).fetchall()
                ]
                if sl:
                    all_per_job.append(sl)

        from ai.fit_calculator import calculate_fit
        fits = [calculate_fit(user_skills, sl) for sl in all_per_job] if all_per_job else []
        avg_fit = round(sum(fits) / len(fits)) if fits else 0

        top = candidates[0] if candidates else None

        top_gap_names = [c["name"] for c in candidates[:4]]
        cache_key = f"{','.join(top_gap_names)}:{avg_fit}:{n_companies}"
        now = time.time()
        if (
            _learn_headline_cache["key"] == cache_key
            and now - _learn_headline_cache["ts"] < _LEARN_CACHE_TTL
        ):
            headline = _learn_headline_cache["text"]
        else:
            try:
                headline = generate_learn_headline(top_gap_names, avg_fit, n_companies)
            except Exception:
                headline = (
                    f"Focus on {top_gap_names[0]} next — highest-leverage gap in your watchlist."
                    if top_gap_names
                    else "Keep your core skills sharp across your watchlist."
                )
            _learn_headline_cache.update({"text": headline, "ts": now, "key": cache_key})

        gain_from_top = 0
        if top and all_per_job:
            boosted = [
                {**s, "level": top["req_level"]}
                if s["name"].lower() == top["name"].lower()
                else s
                for s in user_skills
            ]
            if not any(s["name"].lower() == top["name"].lower() for s in user_skills):
                boosted = user_skills + [{"name": top["name"], "level": top["req_level"]}]
            new_fits = [calculate_fit(boosted, sl) for sl in all_per_job]
            new_avg = round(sum(new_fits) / len(new_fits))
            gain_from_top = max(0, new_avg - avg_fit)

        recs = []
        for i, a in enumerate(candidates[:8]):
            my_level = user_map.get(a["name"].lower(), 0)
            n_cos = len(a["companies"])
            tag = "HIGH LEVERAGE" if n_cos >= max(2, n_companies // 2) else "BROADLY WANTED" if n_cos >= 2 else "TARGETED"
            tag_color = "#b1493a" if tag == "HIGH LEVERAGE" else "#9a7c33"
            tag_bg = "#f5e5e1" if tag == "HIGH LEVERAGE" else "#f7edda"

            # fit gain estimate
            if all_per_job:
                boosted = [
                    {**s, "level": a["req_level"]}
                    if s["name"].lower() == a["name"].lower()
                    else s
                    for s in user_skills
                ]
                if not any(s["name"].lower() == a["name"].lower() for s in user_skills):
                    boosted = user_skills + [{"name": a["name"], "level": a["req_level"]}]
                new_fits = [calculate_fit(boosted, sl) for sl in all_per_job]
                gain = max(1, round(sum(new_fits) / len(new_fits)) - avg_fit)
            else:
                gain = 1

            recs.append(
                {
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
                    "why": f"{n_cos} of your {n_companies} companies ask for it",
                }
            )

        return {
            "headline": headline,
            "stats": [
                {"value": str(len(candidates)), "label": "skill gaps detected"},
                {"value": f"+{gain_from_top}%", "label": "fit from top pick"},
                {"value": f"{avg_fit}%", "label": "current avg fit"},
            ],
            "recs": recs,
        }


# ── Static files & SPA fallback ───────────────────────────────────────────────

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def serve_index():
    index = os.path.join(TEMPLATES_DIR, "index.html")
    if os.path.exists(index):
        return FileResponse(index)
    return {"message": "Career Fit Check API", "docs": "/docs"}
