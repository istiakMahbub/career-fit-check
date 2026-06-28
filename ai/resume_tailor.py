"""
Resume and cover letter tailoring.
Uses Gemini first (best quality for creative writing); falls back to local AI
(Ollama / LM Studio) when Gemini is rate-limited or unavailable.
"""

import logging
import os

import requests as _http
from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger(__name__)

MODEL = "gemini-2.5-flash"

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
                "temperature": 0.5,
                "stream": False,
            },
            timeout=180,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        log.warning("Local AI tailor call failed: %s", e)
        return ""


def _call(prompt: str) -> str:
    """Try Gemini first; fall back to local AI if Gemini fails or is rate-limited."""
    try:
        client = _get_client()
        resp = client.models.generate_content(model=MODEL, contents=prompt)
        result = (resp.text or "").strip()
        if result:
            return result
        log.warning("Gemini returned empty response, trying local AI")
    except Exception as e:
        log.warning("Gemini tailor error (falling back to local AI): %s", e)

    return _local_call(prompt)


# ── length guidance ───────────────────────────────────────────────────────────

_LENGTH_GUIDE = {
    "Brief":    "Keep it short: 1-sentence summary + 3 bullets / 2 short paragraphs.",
    "Standard": "Standard length: 2-3 sentence summary + 5 bullets / 3 paragraphs.",
    "Detailed": "Thorough: 3-sentence summary + 7 bullets / 4+ paragraphs with specifics.",
}

_TONE_GUIDE = {
    "Professional": "formal, measured, and credentialed",
    "Confident":    "assertive, achievement-focused, and direct",
    "Concise":      "crisp, impactful, and jargon-free",
}


# ── resume tailoring ──────────────────────────────────────────────────────────

_RESUME_PROMPT = """\
You are an expert resume writer specialising in data science and software engineering roles.
Rewrite the candidate's profile into targeted resume content for this specific role.
Keep all facts true — never invent experience or credentials.

ROLE: {role_title}
COMPANY: {company_name}
REQUIRED SKILLS: {required_skills}
SKILLS TO EMPHASISE: {lead_with}

CANDIDATE PROFILE:
  Name: {name}
  Current role: {current_role}
  Skill set: {skills_summary}

TONE: {tone_guide}
LENGTH: {length_guide}

Output exactly two sections:

PROFESSIONAL SUMMARY
[write here]

KEY EXPERIENCE HIGHLIGHTS
[bullet points — start each with •]

Return plain text only. No headers in markdown. No commentary. No invented facts."""


def tailor_resume(
    role_title: str,
    company_name: str,
    required_skills: list[str],
    user_name: str,
    user_role: str,
    user_skills: list[dict],
    lead_with: list[str],
    tone: str = "Professional",
    length: str = "Standard",
) -> str:
    skills_summary = ", ".join(
        f"{s['name']} ({s['level']}%)" for s in sorted(user_skills, key=lambda x: -x["level"])[:12]
    )
    prompt = _RESUME_PROMPT.format(
        role_title=role_title,
        company_name=company_name,
        required_skills=", ".join(required_skills[:15]) or "general technical skills",
        lead_with=", ".join(lead_with[:8]) or skills_summary.split(",")[0],
        name=user_name,
        current_role=user_role,
        skills_summary=skills_summary,
        tone_guide=_TONE_GUIDE.get(tone, _TONE_GUIDE["Professional"]),
        length_guide=_LENGTH_GUIDE.get(length, _LENGTH_GUIDE["Standard"]),
    )
    result = _call(prompt)
    if not result:
        return _fallback_resume(user_name, user_role, role_title, company_name, required_skills, lead_with)
    return result


# ── cover letter ──────────────────────────────────────────────────────────────

_COVER_PROMPT = """\
You are an expert cover letter writer for data science and software engineering roles.
Write a targeted, authentic cover letter for this candidate.
Keep all facts true — never invent experience or credentials.

ROLE: {role_title}
COMPANY: {company_name}
REQUIRED SKILLS: {required_skills}
FIT SCORE: {fit}%

CANDIDATE PROFILE:
  Name: {name}
  Current role: {current_role}
  Skill set: {skills_summary}

TONE: {tone_guide}
LENGTH: {length_guide}

Structure:
• Opening paragraph — genuine enthusiasm for this company and role, brief strongest fit signal
• Body paragraph(s) — specific skill alignment, implied by the profile above (do not invent projects)
• Closing paragraph — call to action, offer to discuss further

Address it to "Hiring Team". Sign off with the candidate's name.
Return plain text only. No markdown. No commentary."""


def write_cover_letter(
    role_title: str,
    company_name: str,
    required_skills: list[str],
    user_name: str,
    user_role: str,
    user_skills: list[dict],
    fit: int,
    tone: str = "Professional",
    length: str = "Standard",
) -> str:
    skills_summary = ", ".join(
        f"{s['name']} ({s['level']}%)" for s in sorted(user_skills, key=lambda x: -x["level"])[:12]
    )
    prompt = _COVER_PROMPT.format(
        role_title=role_title,
        company_name=company_name,
        required_skills=", ".join(required_skills[:15]) or "general technical skills",
        fit=fit,
        name=user_name,
        current_role=user_role,
        skills_summary=skills_summary,
        tone_guide=_TONE_GUIDE.get(tone, _TONE_GUIDE["Professional"]),
        length_guide=_LENGTH_GUIDE.get(length, _LENGTH_GUIDE["Standard"]),
    )
    result = _call(prompt)
    if not result:
        return _fallback_cover(user_name, role_title, company_name)
    return result


# ── fallbacks ─────────────────────────────────────────────────────────────────

def _fallback_resume(name, current_role, role_title, company_name, required_skills, lead_with):
    top = (lead_with or required_skills)[:3]
    return (
        f"PROFESSIONAL SUMMARY\n"
        f"{name} is a {current_role} with hands-on experience in "
        f"{', '.join(top)}. Seeking to apply these skills as {role_title} at {company_name}.\n\n"
        f"KEY EXPERIENCE HIGHLIGHTS\n"
        + "\n".join(f"• Demonstrated proficiency in {s}" for s in (lead_with or required_skills)[:5])
    )


def _fallback_cover(name, role_title, company_name):
    return (
        f"Dear Hiring Team,\n\n"
        f"I am writing to express my interest in the {role_title} position at {company_name}. "
        f"My background aligns closely with your requirements and I am excited by the opportunity.\n\n"
        f"I look forward to discussing how I can contribute to your team.\n\n"
        f"Kind regards,\n{name}"
    )
