"""
Gemini-powered skill extractor — parses a job description and returns
a deduplicated list of required technical skills.

Uses the google-genai SDK (successor to the deprecated google-generativeai).
"""

import json
import logging
import os
import re

from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger(__name__)

MODEL_DEFAULT = "gemini-2.5-flash"

_client = None


def _get_client():
    global _client
    if _client is not None:
        return _client
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY must be set in .env")
    from google import genai
    _client = genai.Client(api_key=api_key)
    return _client


_PROMPT_TEMPLATE = """Extract a list of required technical skills from this job description.
Return ONLY a JSON array of skill name strings. No explanation, no markdown, no commentary.
Example: ["Python", "SQL", "dbt", "Airflow"]

Job description:
{description}"""


def extract_skills(description: str, model: str = MODEL_DEFAULT) -> list[str]:
    """
    Call Gemini to extract required skills from a job description.

    Returns a (possibly empty) deduplicated list of skill strings.
    Raises RuntimeError if the API key is missing.
    """
    if not description or not description.strip():
        return []

    client = _get_client()
    prompt = _PROMPT_TEMPLATE.format(description=description[:8000])

    try:
        response = client.models.generate_content(model=model, contents=prompt)
        raw = response.text
    except Exception as e:
        log.error("Gemini API error during skill extraction: %s", e)
        return []

    return _parse_skills(raw)


def _parse_skills(raw: str) -> list[str]:
    """Strip markdown fences and parse JSON array from Gemini response."""
    if not raw:
        return []

    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.MULTILINE)
    cleaned = cleaned.strip()

    match = re.search(r"\[.*?\]", cleaned, re.DOTALL)
    if match:
        cleaned = match.group(0)

    try:
        skills = json.loads(cleaned)
    except json.JSONDecodeError as e:
        log.warning("Could not parse Gemini skill response: %s | raw=%r", e, raw[:200])
        return []

    if not isinstance(skills, list):
        return []

    seen: set[str] = set()
    result: list[str] = []
    for s in skills:
        if not isinstance(s, str):
            continue
        key = s.strip().lower()
        if key and key not in seen:
            seen.add(key)
            result.append(s.strip())

    return result
