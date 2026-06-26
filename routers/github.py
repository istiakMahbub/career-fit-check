"""
GitHub integration — public REST API, no auth required for public repos.
Optional GITHUB_TOKEN env var raises rate limit from 60 → 5000 req/hour.
"""

import json
import logging
import os
import re
import time

import requests
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from db.database import get_db
from ai.fit_calculator import calculate_fit
from ai.insights import generate_repo_feedback, generate_build_next

log = logging.getLogger(__name__)
router = APIRouter()

GITHUB_API = "https://api.github.com"

# ── language → skills + hex color ────────────────────────────────────────────

_LANG_SKILLS: dict[str, list[str]] = {
    "Python": ["Python"],
    "Jupyter Notebook": ["Python", "Jupyter"],
    "R": ["R"],
    "JavaScript": ["JavaScript"],
    "TypeScript": ["TypeScript", "JavaScript"],
    "SQL": ["SQL"],
    "Scala": ["Scala", "Spark"],
    "Java": ["Java"],
    "Go": ["Go"],
    "Rust": ["Rust"],
    "Shell": ["Bash"],
    "Dockerfile": ["Docker"],
    "HCL": ["Terraform"],
    "C++": ["C++"],
}

_LANG_COLORS: dict[str, str] = {
    "Python": "#3572A5",
    "Jupyter Notebook": "#DA5B0B",
    "R": "#198CE7",
    "JavaScript": "#f1e05a",
    "TypeScript": "#2b7489",
    "SQL": "#e38c00",
    "Scala": "#c22d40",
    "Java": "#b07219",
    "Go": "#00ADD8",
    "Rust": "#dea584",
    "Shell": "#89e051",
    "Dockerfile": "#384d54",
    "HCL": "#844FBA",
    "C++": "#f34b7d",
}

# ── GitHub API helpers ────────────────────────────────────────────────────────

def _gh_headers() -> dict:
    token = os.getenv("GITHUB_TOKEN")
    h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _gh_get(path: str) -> dict | list | None:
    url = path if path.startswith("http") else GITHUB_API + path
    try:
        r = requests.get(url, headers=_gh_headers(), timeout=15)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log.warning("GitHub API error for %s: %s", path, e)
        return None


def _slugify_topic(t: str) -> str:
    """'machine-learning' → 'Machine Learning'"""
    return " ".join(w.capitalize() for w in t.replace("-", " ").split())


def _detect_skills(repo: dict) -> list[str]:
    skills: list[str] = []
    lang = repo.get("language") or ""
    if lang in _LANG_SKILLS:
        skills.extend(_LANG_SKILLS[lang])
    for topic in (repo.get("topics") or []):
        skills.append(_slugify_topic(topic))
    # deduplicate preserving order
    seen: set[str] = set()
    result: list[str] = []
    for s in skills:
        key = s.lower()
        if key not in seen:
            seen.add(key)
            result.append(s)
    return result


# ── market fit helpers ────────────────────────────────────────────────────────

def _all_job_skill_lists(conn) -> list[list[str]]:
    """Return one skill-list per extracted job across all companies."""
    jobs = conn.execute(
        "SELECT id FROM jobs WHERE skills_extracted = 1"
    ).fetchall()
    result = []
    for j in jobs:
        sl = [
            s["skill"]
            for s in conn.execute(
                "SELECT skill FROM job_skills WHERE job_id = ?", (j["id"],)
            ).fetchall()
        ]
        if sl:
            result.append(sl)
    return result


def _fit_color(v: int) -> str:
    return "#15604a" if v >= 70 else "#b9791f" if v >= 45 else "#b1493a"


def _repo_fit(repo_skills: list[str], all_job_lists: list[list[str]]) -> int:
    if not repo_skills or not all_job_lists:
        return 0
    # Treat repo skills as "user skills" with level 80
    user_skills = [{"name": s, "level": 80} for s in repo_skills]
    fits = [calculate_fit(user_skills, jl) for jl in all_job_lists]
    return round(sum(fits) / len(fits)) if fits else 0


def _best_company(repo_skills: list[str], conn) -> tuple[str, str]:
    """Return (company_name, company_color) that best matches the repo skills."""
    companies = conn.execute("SELECT id, name, color FROM companies").fetchall()
    best_name, best_color, best_fit = "", "#15604a", 0
    user_skills = [{"name": s, "level": 80} for s in repo_skills]
    for c in companies:
        jls = [
            [s["skill"] for s in conn.execute("SELECT skill FROM job_skills WHERE job_id = ?", (j["id"],)).fetchall()]
            for j in conn.execute("SELECT id FROM jobs WHERE company_id = ? AND skills_extracted = 1", (c["id"],)).fetchall()
        ]
        jls = [jl for jl in jls if jl]
        if not jls:
            continue
        fits = [calculate_fit(user_skills, jl) for jl in jls]
        avg = round(sum(fits) / len(fits))
        if avg > best_fit:
            best_fit, best_name, best_color = avg, c["name"], c["color"]
    return best_name, best_color


# ── endpoints ─────────────────────────────────────────────────────────────────

class ConnectRequest(BaseModel):
    username: str


@router.post("/github/connect")
def github_connect(payload: ConnectRequest):
    username = payload.username.strip().lstrip("@")
    if not username:
        raise HTTPException(status_code=400, detail="GitHub username required")

    # Verify user exists
    user_data = _gh_get(f"/users/{username}")
    if user_data is None:
        raise HTTPException(status_code=404, detail=f"GitHub user '{username}' not found")

    # Fetch repos (up to 100, sorted by recently updated)
    repos_raw = _gh_get(f"/users/{username}/repos?per_page=100&sort=updated&type=public")
    if not isinstance(repos_raw, list):
        repos_raw = []

    with get_db() as conn:
        all_job_lists = _all_job_skill_lists(conn)
        company_names = [
            r["name"] for r in conn.execute("SELECT name FROM companies").fetchall()
        ]

        # Process each repo
        processed: list[dict] = []
        for r in repos_raw:
            if r.get("fork"):
                continue  # skip forks
            skills = _detect_skills(r)
            fit = _repo_fit(skills, all_job_lists)
            best_co, best_co_color = _best_company(skills, conn)
            processed.append({
                "name": r["name"],
                "url": r.get("html_url", ""),
                "description": (r.get("description") or "")[:200],
                "language": r.get("language") or "",
                "lang_color": _LANG_COLORS.get(r.get("language") or "", "#bcb6aa"),
                "stars": r.get("stargazers_count", 0),
                "topics": r.get("topics") or [],
                "skills": skills,
                "fit": fit,
                "fit_color": _fit_color(fit),
                "best_company": best_co,
                "best_company_color": best_co_color,
                "feedback": "",  # filled in batch below
            })

        # Sort by fit desc, then stars
        processed.sort(key=lambda x: (-x["fit"], -x["stars"]))

        # Aggregate portfolio skills
        all_portfolio_skills: list[str] = []
        seen_ps: set[str] = set()
        for rep in processed:
            for s in rep["skills"]:
                if s.lower() not in seen_ps:
                    seen_ps.add(s.lower())
                    all_portfolio_skills.append(s)

        # Compute missing skills (in demand but not in portfolio)
        all_demanded: dict[str, int] = {}
        for jl in all_job_lists:
            for s in jl:
                all_demanded[s.lower()] = all_demanded.get(s.lower(), 0) + 1
        missing_skills = [
            s for s, _ in sorted(all_demanded.items(), key=lambda x: -x[1])
            if s not in seen_ps
        ][:10]

        # AI: batch repo feedback (top 5 repos)
        try:
            feedback_map = generate_repo_feedback(processed[:5])
            for rep in processed:
                rep["feedback"] = feedback_map.get(rep["name"], "")
        except Exception as e:
            log.warning("Repo feedback generation failed: %s", e)

        # AI: build next suggestions
        build_next: list[dict] = []
        try:
            raw_suggestions = generate_build_next(
                portfolio_skills=all_portfolio_skills,
                missing_skills=missing_skills,
                company_names=company_names,
            )
            for sug in raw_suggestions:
                sug_skills = sug.get("skills") or []
                gain = max(1, len([s for s in sug_skills if s.lower() in {ms.lower() for ms in missing_skills[:8]}]) * 3)
                build_next.append({
                    "name": sug.get("name", ""),
                    "description": sug.get("description", ""),
                    "skills": sug_skills,
                    "gain": gain,
                    "companies": company_names[:3],
                })
        except Exception as e:
            log.warning("Build-next generation failed: %s", e)

        # Count aligned roles (open roles where portfolio adds >30% fit)
        aligned = 0
        _profile_row = conn.execute("SELECT skills FROM user_profile WHERE id=1").fetchone()
        user_skills_from_profile = json.loads(_profile_row["skills"] if _profile_row else "[]")
        portfolio_as_skills = [{"name": s, "level": 80} for s in all_portfolio_skills]
        combined = {s["name"].lower(): s for s in user_skills_from_profile}
        for s in portfolio_as_skills:
            if s["name"].lower() not in combined:
                combined[s["name"].lower()] = s
        combined_list = list(combined.values())
        for jl in all_job_lists:
            if calculate_fit(combined_list, jl) >= 30:
                aligned += 1

        # Persist to cache
        conn.execute(
            """INSERT INTO github_cache (id, username, repos_json, skills_json, build_next_json, last_synced)
               VALUES (1, ?, ?, ?, ?, datetime('now'))
               ON CONFLICT(id) DO UPDATE SET
               username = excluded.username, repos_json = excluded.repos_json,
               skills_json = excluded.skills_json, build_next_json = excluded.build_next_json,
               last_synced = excluded.last_synced""",
            (username, json.dumps(processed), json.dumps(all_portfolio_skills), json.dumps(build_next)),
        )

    return {
        "connected": True,
        "username": username,
        "last_synced": "now",
        "stats": {
            "repos_scanned": len(processed),
            "skills_detected": len(all_portfolio_skills),
            "aligned_roles": aligned,
        },
        "repos": processed,
        "build_next": build_next,
    }


@router.get("/github/repos")
def github_repos():
    with get_db() as conn:
        row = conn.execute("SELECT * FROM github_cache WHERE id = 1").fetchone()
        if not row or not row["username"]:
            return {"connected": False}

        all_job_lists = _all_job_skill_lists(conn)

        repos = json.loads(row["repos_json"] or "[]")
        # Refresh fit scores against current job data
        for rep in repos:
            rep["fit"] = _repo_fit(rep.get("skills", []), all_job_lists)
            rep["fit_color"] = _fit_color(rep["fit"])

        all_portfolio_skills = json.loads(row["skills_json"] or "[]")
        build_next = json.loads(row["build_next_json"] or "[]")

        # Recalculate aligned roles
        _profile_row = conn.execute("SELECT skills FROM user_profile WHERE id=1").fetchone()
        user_skills_from_profile = json.loads(_profile_row["skills"] if _profile_row else "[]")
        portfolio_as_skills = [{"name": s, "level": 80} for s in all_portfolio_skills]
        combined = {s["name"].lower(): s for s in user_skills_from_profile}
        for s in portfolio_as_skills:
            if s["name"].lower() not in combined:
                combined[s["name"].lower()] = s
        combined_list = list(combined.values())
        aligned = sum(1 for jl in all_job_lists if calculate_fit(combined_list, jl) >= 30)

        return {
            "connected": True,
            "username": row["username"],
            "last_synced": (row["last_synced"] or "")[:10],
            "stats": {
                "repos_scanned": len(repos),
                "skills_detected": len(all_portfolio_skills),
                "aligned_roles": aligned,
            },
            "repos": repos,
            "build_next": build_next,
        }


@router.delete("/github/disconnect", status_code=204)
def github_disconnect():
    with get_db() as conn:
        conn.execute(
            "UPDATE github_cache SET username = NULL, repos_json = '[]', "
            "skills_json = '[]', build_next_json = '[]', last_synced = NULL WHERE id = 1"
        )
