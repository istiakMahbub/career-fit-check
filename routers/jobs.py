import json
import logging

from fastapi import APIRouter, HTTPException

from db.database import get_db
from ai.fit_calculator import calculate_fit

log = logging.getLogger(__name__)
router = APIRouter()


# ── GET /api/jobs?company_id={id} ────────────────────────────────────────────

@router.get("/jobs")
def list_jobs(company_id: int):
    with get_db() as conn:
        if not conn.execute("SELECT id FROM companies WHERE id = ?", (company_id,)).fetchone():
            raise HTTPException(status_code=404, detail="Company not found")

        profile = conn.execute("SELECT skills FROM user_profile WHERE id = 1").fetchone()
        user_skills = json.loads(profile["skills"]) if profile and profile["skills"] else []

        jobs = conn.execute(
            "SELECT * FROM jobs WHERE company_id = ? ORDER BY scraped_date DESC",
            (company_id,),
        ).fetchall()

        result = []
        for job in jobs:
            job_skill_rows = conn.execute(
                "SELECT skill FROM job_skills WHERE job_id = ?", (job["id"],)
            ).fetchall()
            job_skills = [s["skill"] for s in job_skill_rows]
            match = calculate_fit(user_skills, job_skills) if job_skills else 0

            result.append(
                {
                    "id": job["id"],
                    "company_id": job["company_id"],
                    "title": job["title"],
                    "location": job["location"] or "",
                    "posted_date": job["posted_date"] or "",
                    "scraped_date": job["scraped_date"] or "",
                    "is_new": bool(job["is_new"]),
                    "url": job["url"] or "",
                    "skills_extracted": bool(job["skills_extracted"]),
                    "skills": job_skills,
                    "match": match,
                }
            )

        result.sort(key=lambda r: -r["match"])
        return result
