import io
import json
import logging
from typing import Optional

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from db.database import get_db
from ai.skill_extractor import extract_skills

log = logging.getLogger(__name__)
router = APIRouter()


# ── GET /api/profile ─────────────────────────────────────────────────────────

@router.get("/profile")
def get_profile():
    with get_db() as conn:
        row = conn.execute("SELECT * FROM user_profile WHERE id = 1").fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Profile not found")

        skills = _parse_skills(row["skills"])
        return _profile_dict(row, skills)


# ── PUT /api/profile ─────────────────────────────────────────────────────────

class UpdateProfileRequest(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    skills: Optional[list[dict]] = None


@router.put("/profile")
def update_profile(payload: UpdateProfileRequest):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM user_profile WHERE id = 1").fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Profile not found")

        name = payload.name if payload.name is not None else row["name"]
        role = payload.role if payload.role is not None else row["role"]

        if payload.skills is not None:
            # Validate each skill has name + level
            validated = []
            for s in payload.skills:
                if not isinstance(s.get("name"), str) or not s["name"].strip():
                    continue
                level = max(0, min(100, int(s.get("level", 50))))
                validated.append({"name": s["name"].strip(), "level": level})
            skills_json = json.dumps(validated)
        else:
            skills_json = row["skills"]

        conn.execute(
            "UPDATE user_profile SET name = ?, role = ?, skills = ? WHERE id = 1",
            (name, role, skills_json),
        )
        skills = _parse_skills(skills_json)
        return _profile_dict({"name": name, "role": role, "id": 1}, skills)


# ── POST /api/profile/skill ──────────────────────────────────────────────────

class SkillAction(BaseModel):
    name: str
    level: Optional[int] = 50


@router.post("/profile/skill", status_code=201)
def add_skill(payload: SkillAction):
    """Add or update a single skill."""
    with get_db() as conn:
        row = conn.execute("SELECT skills FROM user_profile WHERE id = 1").fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Profile not found")

        skills = _parse_skills(row["skills"])
        name = payload.name.strip()
        level = max(0, min(100, payload.level or 50))

        # Upsert
        existing = next((i for i, s in enumerate(skills) if s["name"].lower() == name.lower()), None)
        if existing is not None:
            skills[existing]["level"] = level
        else:
            skills.append({"name": name, "level": level})

        conn.execute(
            "UPDATE user_profile SET skills = ? WHERE id = 1",
            (json.dumps(skills),),
        )
        return {"name": name, "level": level}


@router.delete("/profile/skill/{skill_name}", status_code=204)
def remove_skill(skill_name: str):
    """Remove a skill by name."""
    with get_db() as conn:
        row = conn.execute("SELECT skills FROM user_profile WHERE id = 1").fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Profile not found")

        skills = _parse_skills(row["skills"])
        skills = [s for s in skills if s["name"].lower() != skill_name.lower()]
        conn.execute(
            "UPDATE user_profile SET skills = ? WHERE id = 1",
            (json.dumps(skills),),
        )


# ── GET /api/profile/suggestions ─────────────────────────────────────────────

@router.get("/profile/suggestions")
def get_suggestions(limit: int = 10):
    """
    Return the top skills demanded by watchlist companies that the user doesn't have.
    Ranked by frequency across jobs. Falls back to a curated data-science list
    if no jobs have been synced yet.
    """
    _FALLBACK = [
        "Python", "SQL", "dbt", "Airflow", "Spark", "Kafka", "MLOps",
        "Docker", "Kubernetes", "PyTorch", "scikit-learn", "Tableau",
        "Power BI", "Snowflake", "AWS", "A/B Testing", "Statistics",
        "Looker", "Pandas", "R",
    ]

    with get_db() as conn:
        profile_row = conn.execute("SELECT skills FROM user_profile WHERE id = 1").fetchone()
        user_skills = _parse_skills(profile_row["skills"] if profile_row else "[]")
        user_names = {s["name"].lower() for s in user_skills}

        # Count skill frequency across all synced jobs
        rows = conn.execute(
            "SELECT skill, COUNT(*) as cnt FROM job_skills GROUP BY skill ORDER BY cnt DESC"
        ).fetchall()

        if rows:
            suggestions = [
                r["skill"] for r in rows
                if r["skill"].lower() not in user_names
            ][:limit]
        else:
            # No jobs synced yet — use the curated fallback list
            suggestions = [s for s in _FALLBACK if s.lower() not in user_names][:limit]

    return {"suggestions": suggestions}


# ── POST /api/profile/resume ─────────────────────────────────────────────────

@router.post("/profile/resume")
async def upload_resume(file: UploadFile = File(...)):
    """
    Accept a PDF or DOCX resume, extract text, use Gemini to detect skills,
    then merge them into user_profile.skills (upsert — never replaces existing).
    """
    filename = (file.filename or "").lower()
    if not (filename.endswith(".pdf") or filename.endswith(".docx") or filename.endswith(".doc")):
        raise HTTPException(status_code=400, detail="Only PDF and DOCX files are accepted")

    contents = await file.read()
    if len(contents) > 10 * 1024 * 1024:  # 10 MB cap
        raise HTTPException(status_code=400, detail="File too large (max 10 MB)")

    text = _extract_text(contents, filename)
    if not text.strip():
        raise HTTPException(status_code=422, detail="Could not extract text from the file")

    new_skills = extract_skills(text[:8000])

    if not new_skills:
        return {"skills_added": 0, "message": "No new skills detected in the resume"}

    with get_db() as conn:
        row = conn.execute("SELECT skills FROM user_profile WHERE id = 1").fetchone()
        existing = _parse_skills(row["skills"] if row else "[]")
        existing_names = {s["name"].lower() for s in existing}

        added = 0
        for skill_name in new_skills:
            if skill_name.lower() not in existing_names:
                existing.append({"name": skill_name, "level": 60})
                existing_names.add(skill_name.lower())
                added += 1

        conn.execute(
            "UPDATE user_profile SET skills = ? WHERE id = 1",
            (json.dumps(existing),),
        )

    return {
        "skills_added": added,
        "skills_detected": new_skills,
        "message": f"Added {added} new skill{'s' if added != 1 else ''} from your resume",
    }


def _extract_text(contents: bytes, filename: str) -> str:
    if filename.endswith(".pdf"):
        return _extract_pdf(contents)
    return _extract_docx(contents)


def _extract_pdf(contents: bytes) -> str:
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(contents)) as pdf:
            return "\n".join(
                page.extract_text() or "" for page in pdf.pages
            )
    except ImportError:
        pass
    # Fallback: pypdf2 if available
    try:
        import PyPDF2
        reader = PyPDF2.PdfReader(io.BytesIO(contents))
        return "\n".join(
            page.extract_text() or "" for page in reader.pages
        )
    except ImportError:
        pass
    return ""


def _extract_docx(contents: bytes) -> str:
    try:
        from docx import Document
        doc = Document(io.BytesIO(contents))
        return "\n".join(para.text for para in doc.paragraphs)
    except ImportError:
        return ""


# ── helpers ──────────────────────────────────────────────────────────────────

def _parse_skills(raw) -> list[dict]:
    if not raw:
        return []
    try:
        result = json.loads(raw)
        return result if isinstance(result, list) else []
    except Exception:
        return []


def _initials(name: str) -> str:
    parts = [w for w in (name or "").split() if w]
    if len(parts) >= 2:
        return (parts[0][0] + parts[-1][0]).upper()
    return (name or "U")[:2].upper()


def _profile_dict(row, skills: list[dict]) -> dict:
    return {
        "id": row["id"],
        "name": row["name"] or "",
        "role": row["role"] or "",
        "skills": skills,
        "skill_count": len(skills),
        "initials": _initials(row["name"] or ""),
    }
