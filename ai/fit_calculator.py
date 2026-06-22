"""
Fit calculator — computes how well the user's skill profile matches a job's
required skills, returning an integer percentage 0–100.

Also provides aggregate helpers used by the API routers.
"""

from __future__ import annotations


def calculate_fit(user_skills: list[dict], job_skills: list[str]) -> int:
    """
    Return the percentage of job_skills that appear in user_skills.

    user_skills: [{"name": "Python", "level": 80}, ...]
    job_skills:  ["Python", "SQL", "Tableau"]
    """
    if not job_skills:
        return 0

    user_names = {s["name"].lower() for s in user_skills if isinstance(s.get("name"), str)}
    matched = sum(1 for s in job_skills if s.lower() in user_names)
    return round((matched / len(job_skills)) * 100)


def calculate_company_fit(user_skills: list[dict], all_job_skills: list[list[str]]) -> int:
    """
    Average fit across every job at a company.

    all_job_skills: list of per-job skill lists.
    Returns 0 if there are no jobs with extracted skills.
    """
    scored = [calculate_fit(user_skills, js) for js in all_job_skills if js]
    if not scored:
        return 0
    return round(sum(scored) / len(scored))


def skill_gap(user_skills: list[dict], job_skills: list[str]) -> list[str]:
    """Return skills required by the job that the user does not have."""
    user_names = {s["name"].lower() for s in user_skills if isinstance(s.get("name"), str)}
    return [s for s in job_skills if s.lower() not in user_names]


def top_missing_skills(
    user_skills: list[dict],
    all_job_skills: list[list[str]],
    top_n: int = 10,
) -> list[dict]:
    """
    Rank skills by how often they appear in jobs where the user has a gap.

    Returns a list of {"skill": str, "count": int} dicts, descending by count.
    """
    from collections import Counter

    user_names = {s["name"].lower() for s in user_skills if isinstance(s.get("name"), str)}
    missing: list[str] = []
    for job_skills in all_job_skills:
        for s in job_skills:
            if s.lower() not in user_names:
                missing.append(s)

    counts = Counter(missing)
    return [
        {"skill": skill, "count": count}
        for skill, count in counts.most_common(top_n)
    ]
