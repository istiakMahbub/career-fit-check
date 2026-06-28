"""
AI-powered insights:
  - one-line nudge (hiring trend signal, ≤20 words)
  - 2-3 sentence company summary for Deep Dive
  - learn-next hero headline across the full watchlist

Uses Gemini first (better quality); falls back to local AI (Ollama / LM Studio)
when Gemini is rate-limited or unavailable.
"""

import logging
import os

import requests as _http
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger(__name__)

MODEL_DEFAULT = "gemini-2.5-flash"

LOCAL_MODEL_NAME: str = os.getenv("LOCAL_MODEL_NAME", "").strip()
LOCAL_AI_URL: str = (
    os.getenv("LOCAL_AI_URL", "") or "http://localhost:11434"
).rstrip("/")

_client = None


def _get_client():
    global _client
    if _client is not None:
        return _client
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set")
    from google import genai
    _client = genai.Client(api_key=api_key)
    return _client


def _local_call(prompt: str) -> str:
    """Call local AI (Ollama / LM Studio) via OpenAI-compatible chat endpoint."""
    if not LOCAL_MODEL_NAME:
        return ""
    try:
        r = _http.post(
            f"{LOCAL_AI_URL}/v1/chat/completions",
            json={
                "model": LOCAL_MODEL_NAME,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.4,
                "stream": False,
            },
            timeout=120,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        log.warning("Local AI insights call failed: %s", e)
        return ""


def _call(prompt: str) -> str:
    """Try Gemini first; fall back to local AI if Gemini fails or is rate-limited."""
    try:
        client = _get_client()
        response = client.models.generate_content(model=MODEL_DEFAULT, contents=prompt)
        result = (response.text or "").strip()
        if result:
            return result
        log.warning("Gemini returned empty response, trying local AI")
    except Exception as e:
        log.warning("Gemini insights error (falling back to local AI): %s", e)

    return _local_call(prompt)


# ── Prompts ───────────────────────────────────────────────────────────────────

_NUDGE_PROMPT = """\
You are a career intelligence analyst. In one concise sentence (max 20 words), \
describe what this company's recent hiring pattern signals about their strategy.
Company: {company_name}
Recent job titles: {recent_titles}
Top skills in demand: {top_skills}
Return ONLY the sentence. No commentary, no quotes."""

_SUMMARY_PROMPT = """\
You are a career intelligence analyst. Write a 2-3 sentence analysis of this \
company's current hiring strategy and what it means for a job candidate.
Company: {company_name}
Open roles: {open_roles}
Recent job titles: {recent_titles}
Top skills in demand: {top_skills}
Candidate fit score: {fit}%
Be direct and actionable. Return only the analysis text, no headers."""

_LEARN_HEADLINE_PROMPT = """\
You are a career coach. Write a single motivating sentence (max 25 words) \
summarising the most important skill gap to close and why it will move the needle.
Top skill gaps: {top_gaps}
Current average fit across watchlist: {avg_fit}%
Companies tracked: {n_companies}
Return ONLY the sentence. No commentary, no quotes."""


# ── Public API ────────────────────────────────────────────────────────────────

def generate_nudge(
    company_name: str,
    recent_titles: list[str],
    top_skills: list[str],
) -> str:
    prompt = _NUDGE_PROMPT.format(
        company_name=company_name,
        recent_titles=", ".join(recent_titles[:12]) or "N/A",
        top_skills=", ".join(top_skills[:8]) or "N/A",
    )
    result = _call(prompt)
    return result or (
        f"{company_name} is scaling technical capacity — "
        + (f"strong demand for {top_skills[0]}." if top_skills else "broad hiring across engineering.")
    )


def generate_summary(
    company_name: str,
    recent_titles: list[str],
    top_skills: list[str],
    fit: int,
    open_roles: int,
) -> str:
    prompt = _SUMMARY_PROMPT.format(
        company_name=company_name,
        open_roles=open_roles,
        recent_titles=", ".join(recent_titles[:12]) or "N/A",
        top_skills=", ".join(top_skills[:8]) or "N/A",
        fit=fit,
    )
    result = _call(prompt)
    skill_str = ", ".join(top_skills[:3]) or "technical skills"
    return result or (
        f"{company_name} has {open_roles} open roles with strong demand for {skill_str}. "
        f"Your current fit is {fit}%. "
        + ("You're well positioned — apply now." if fit >= 70 else "Closing key gaps would make you very competitive.")
    )


_REPO_FEEDBACK_PROMPT = """\
You are a career coach reviewing a developer's GitHub portfolio for data science / engineering roles.
For each repository below, write ONE actionable sentence (max 15 words) that tells the developer how to increase its relevance to employers.

Repositories (JSON):
{repos_json}

Return ONLY a JSON object mapping repo name → feedback string.
Example: {{"my-repo": "Add a CI pipeline and deployment docs to show production readiness."}}
No commentary, no markdown fences."""

_BUILD_NEXT_PROMPT = """\
You are a career coach. A developer's portfolio already demonstrates: {portfolio_skills}
The most in-demand skills missing from their portfolio (wanted by target companies): {missing_skills}
Target companies: {companies}

Suggest exactly 3 concrete project ideas that would build the missing skills.
Return ONLY a JSON array with this exact shape:
[
  {{"name": "Short project title (3-6 words)", "description": "One sentence what it does and what it builds.", "skills": ["Skill1", "Skill2"]}}
]
No commentary, no markdown fences."""


def generate_repo_feedback(repos: list[dict]) -> dict[str, str]:
    """
    Generate one-line career feedback for up to 5 repos.
    Returns {repo_name: feedback_string}.
    """
    if not repos:
        return {}
    import json as _json
    slim = [{"name": r["name"], "language": r.get("language", ""), "description": r.get("description", ""), "skills": r.get("skills", [])} for r in repos[:5]]
    prompt = _REPO_FEEDBACK_PROMPT.format(repos_json=_json.dumps(slim))
    raw = _call(prompt)
    if not raw:
        return {}
    try:
        cleaned = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        return _json.loads(cleaned)
    except Exception:
        return {}


def generate_build_next(
    portfolio_skills: list[str],
    missing_skills: list[str],
    company_names: list[str],
) -> list[dict]:
    """
    Generate 3 project ideas that build the top missing skills.
    Returns list of {name, description, skills}.
    """
    if not missing_skills:
        return []
    import json as _json
    prompt = _BUILD_NEXT_PROMPT.format(
        portfolio_skills=", ".join(portfolio_skills[:12]) or "general programming",
        missing_skills=", ".join(missing_skills[:8]),
        companies=", ".join(company_names[:5]) or "tech companies",
    )
    raw = _call(prompt)
    if not raw:
        return []
    try:
        cleaned = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        result = _json.loads(cleaned)
        if isinstance(result, list):
            return result[:3]
    except Exception:
        pass
    return []


_SKILL_TIPS_PROMPT = """\
You are a career coach. Based on these job postings from {company_name}{category_label}, \
write ONE sentence per skill: what specifically the candidate should learn and to what depth, \
grounded in what these actual roles require. Be concrete — mention tools, modules, or techniques \
where relevant. Do NOT give generic advice.

Sample job titles and descriptions:
{job_samples}

Return ONLY a JSON object mapping each skill name to its one-sentence tip.
Include every skill listed below.
Skills: {skills_list}"""


def generate_skill_tips(
    skills: list[str],
    company_name: str,
    job_samples: list[str],
    category: str = "",
) -> dict[str, str]:
    """
    Generate one-sentence learning tips for each skill, grounded in the company's job postings.
    Returns {skill_name: tip_string}. Uses Gemini → local AI fallback.
    """
    if not skills:
        return {}
    import json as _json

    category_label = f" ({category} roles)" if category else ""
    samples_text = "\n".join(f"• {s}" for s in job_samples[:12]) or "No descriptions available."
    prompt = _SKILL_TIPS_PROMPT.format(
        company_name=company_name,
        category_label=category_label,
        job_samples=samples_text,
        skills_list=", ".join(skills),
    )
    raw = _call(prompt)
    if not raw:
        return {}

    cleaned = raw.strip()
    # strip markdown fences if present
    import re as _re
    cleaned = _re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=_re.MULTILINE).strip()
    m = _re.search(r"\{.*\}", cleaned, _re.DOTALL)
    if not m:
        return {}
    try:
        result = _json.loads(m.group(0))
        return {k: str(v) for k, v in result.items() if isinstance(v, str)}
    except Exception:
        return {}


def generate_learn_headline(
    top_gaps: list[str],
    avg_fit: int,
    n_companies: int,
) -> str:
    if not top_gaps:
        return "You're well aligned across your watchlist — keep your core skills sharp and stay consistent."
    prompt = _LEARN_HEADLINE_PROMPT.format(
        top_gaps=", ".join(top_gaps[:4]),
        avg_fit=avg_fit,
        n_companies=n_companies,
    )
    result = _call(prompt)
    if result:
        return result
    if len(top_gaps) >= 2:
        return (
            f"Focus on {top_gaps[0]} and {top_gaps[1]} — "
            "they're the highest-leverage gaps across your watchlist."
        )
    return (
        f"Focus on {top_gaps[0]} next — "
        "it's the highest-leverage gap across your watchlist."
    )
