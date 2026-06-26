import json
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from db.database import get_db
from ai.fit_calculator import calculate_fit

log = logging.getLogger(__name__)
router = APIRouter()

_VALID_STATUSES = {"saved", "applied", "interviewing", "offer", "rejected"}


# ── GET /api/applications ─────────────────────────────────────────────────────

@router.get("/applications")
def list_applications():
    with get_db() as conn:
        profile_row = conn.execute(
            "SELECT skills FROM user_profile WHERE id = 1"
        ).fetchone()
        user_skills = (
            json.loads(profile_row["skills"])
            if profile_row and profile_row["skills"]
            else []
        )

        rows = conn.execute(
            """
            SELECT a.id, a.job_id, a.status, a.notes, a.saved_at, a.updated_at,
                   j.title, j.location, j.url, j.posted_date,
                   c.id as company_id, c.name as company_name, c.color as company_color
            FROM applications a
            JOIN jobs j ON j.id = a.job_id
            JOIN companies c ON c.id = j.company_id
            ORDER BY
                CASE a.status
                    WHEN 'interviewing' THEN 1
                    WHEN 'offer'        THEN 2
                    WHEN 'applied'      THEN 3
                    WHEN 'saved'        THEN 4
                    WHEN 'rejected'     THEN 5
                END,
                a.updated_at DESC
            """
        ).fetchall()

        items = []
        for r in rows:
            skills = [
                s["skill"]
                for s in conn.execute(
                    "SELECT skill FROM job_skills WHERE job_id = ?", (r["job_id"],)
                ).fetchall()
            ]
            fit = calculate_fit(user_skills, skills) if skills else 0
            fit_color = "#15604a" if fit >= 70 else "#b9791f" if fit >= 45 else "#b1493a"

            items.append({
                "id": r["id"],
                "job_id": r["job_id"],
                "title": r["title"],
                "location": r["location"] or "",
                "url": r["url"] or "",
                "posted_date": (r["posted_date"] or "")[:10],
                "company_id": r["company_id"],
                "company_name": r["company_name"],
                "company_color": r["company_color"],
                "status": r["status"],
                "notes": r["notes"] or "",
                "saved_at": (r["saved_at"] or "")[:10],
                "updated_at": r["updated_at"] or "",
                "fit": fit,
                "fit_color": fit_color,
                "required_skills": skills,
            })

    return {"applications": items, "total": len(items)}


# ── POST /api/applications ────────────────────────────────────────────────────

class SaveRequest(BaseModel):
    job_id: int
    status: str = "saved"
    notes: str = ""


@router.post("/applications", status_code=201)
def save_application(payload: SaveRequest):
    if payload.status not in _VALID_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid status: {payload.status}")

    with get_db() as conn:
        job = conn.execute("SELECT id FROM jobs WHERE id = ?", (payload.job_id,)).fetchone()
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        conn.execute(
            """
            INSERT INTO applications (job_id, status, notes)
            VALUES (?, ?, ?)
            ON CONFLICT(job_id) DO UPDATE SET
                status     = excluded.status,
                notes      = excluded.notes,
                updated_at = datetime('now')
            """,
            (payload.job_id, payload.status, payload.notes),
        )
        row = conn.execute(
            "SELECT id FROM applications WHERE job_id = ?", (payload.job_id,)
        ).fetchone()

    return {"id": row["id"], "job_id": payload.job_id, "status": payload.status}


# ── PUT /api/applications/{id} ────────────────────────────────────────────────

class UpdateRequest(BaseModel):
    status: Optional[str] = None
    notes: Optional[str] = None


@router.put("/applications/{app_id}")
def update_application(app_id: int, payload: UpdateRequest):
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM applications WHERE id = ?", (app_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Application not found")

        new_status = payload.status if payload.status is not None else row["status"]
        new_notes  = payload.notes  if payload.notes  is not None else row["notes"]

        if new_status not in _VALID_STATUSES:
            raise HTTPException(status_code=400, detail=f"Invalid status: {new_status}")

        conn.execute(
            "UPDATE applications SET status = ?, notes = ?, updated_at = datetime('now') WHERE id = ?",
            (new_status, new_notes, app_id),
        )

    return {"id": app_id, "status": new_status, "notes": new_notes}


# ── DELETE /api/applications/{id} ─────────────────────────────────────────────

@router.delete("/applications/{app_id}", status_code=204)
def delete_application(app_id: int):
    with get_db() as conn:
        row = conn.execute(
            "SELECT id FROM applications WHERE id = ?", (app_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Application not found")
        conn.execute("DELETE FROM applications WHERE id = ?", (app_id,))
