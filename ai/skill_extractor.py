"""
Skill extractor — extracts required technical skills and job category from a posting.

Two backends, chosen by environment variable:
  - LOCAL (if LOCAL_MODEL_NAME is set): any OpenAI-compatible local server.
    Works with Ollama (default port 11434) and LM Studio (default port 1234).
    No quota, no API key needed.
  - GEMINI (fallback): Google Gemini API.
    Requires GEMINI_API_KEY. Free tier: ~20 req/day for gemini-2.5-flash.

LM Studio setup:
    1. Download "Llama-3.2-3B-Instruct" GGUF (Q4_K_M) from lmstudio-community
    2. Load it, go to "Local Server" tab and start the server
    3. Set in .env:  LOCAL_MODEL_NAME=local-model
                     LOCAL_AI_URL=http://localhost:1234

Ollama setup:
    1. Install from ollama.ai, then: ollama pull llama3.2:3b
    2. Set in .env:  LOCAL_MODEL_NAME=llama3.2:3b
                     LOCAL_AI_URL=http://localhost:11434   (default, can omit)
"""

import json
import logging
import os
import re

import requests as _http
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

GEMINI_MODEL_DEFAULT = "gemini-2.5-flash"
GEMINI_MODEL_FALLBACK = "gemini-2.0-flash"

LOCAL_MODEL_NAME: str = os.getenv("LOCAL_MODEL_NAME", "").strip()
# LOCAL_AI_URL works with any OpenAI-compatible server (Ollama or LM Studio)
LOCAL_AI_URL: str = (
    os.getenv("LOCAL_AI_URL", "")
    or os.getenv("OLLAMA_URL", "http://localhost:11434")  # backward compat
).rstrip("/")

JOB_CATEGORIES = [
    "Data & ML",
    "Software Engineering",
    "Product",
    "Design",
    "Operations",
    "Finance",
    "Marketing & Growth",
    "People & HR",
    "Other",
]


class GeminiRateLimitError(RuntimeError):
    """Raised when Gemini returns 429 / RESOURCE_EXHAUSTED."""
    pass


# ── Gemini client (lazy) ──────────────────────────────────────────────────────

_gemini_client = None


def _get_gemini_client():
    global _gemini_client
    if _gemini_client is not None:
        return _gemini_client
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY must be set in .env (or set LOCAL_MODEL_NAME to use Ollama)")
    from google import genai
    _gemini_client = genai.Client(api_key=api_key)
    return _gemini_client


# ── Ollama backend ────────────────────────────────────────────────────────────

_OLLAMA_PROMPT = """Analyse this job posting. Extract technical skills split into required and preferred, then classify the role.

Return a JSON object with exactly three keys:
- "required": array of MUST-HAVE technical skill strings (explicitly essential, core to the role, or stated as requirements)
- "preferred": array of NICE-TO-HAVE skill strings (desired, bonus, or mentioned but not mandatory)
- "category": exactly one of {categories}

If the description doesn't distinguish, put all technical skills under "required" and leave "preferred" empty.
Infer skills from the job title if the description is absent.

Job posting:
{text}"""


def _local_ai_available() -> bool:
    """Quick check that the local AI server (Ollama or LM Studio) is reachable."""
    try:
        r = _http.get(f"{LOCAL_AI_URL}/v1/models", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


def _extract_one_local(job_text: str) -> tuple[list[str], list[str], str]:
    """
    Call the local AI server via the OpenAI-compatible chat completions endpoint.
    Returns (required_skills, preferred_skills, category).
    Works with both Ollama (:11434) and LM Studio (:1234).
    """
    prompt = _OLLAMA_PROMPT.format(
        categories=JOB_CATEGORIES,
        text=job_text[:3000],
    )
    try:
        r = _http.post(
            f"{LOCAL_AI_URL}/v1/chat/completions",
            json={
                "model": LOCAL_MODEL_NAME,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
                "stream": False,
            },
            timeout=120,
        )
        r.raise_for_status()
        raw = r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        log.warning("Local AI extraction error: %s", e)
        return [], [], "Other"

    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if not m:
            return [], [], "Other"
        try:
            obj = json.loads(m.group(0))
        except Exception:
            return [], [], "Other"

    # Support both new {required, preferred} format and old {skills} format
    required = _parse_skills(json.dumps(obj.get("required", obj.get("skills", []))))
    preferred = _parse_skills(json.dumps(obj.get("preferred", [])))
    cat = obj.get("category", "Other")
    if cat not in JOB_CATEGORIES:
        cat = "Other"
    return required, preferred, cat


def _extract_batch_local(job_texts: list[str]) -> list[tuple[list[str], list[str], str]]:
    """Run local AI extraction per job. No quota — per-job calls are fine."""
    return [_extract_one_local(text) for text in job_texts]


# ── Gemini backend ────────────────────────────────────────────────────────────

_GEMINI_BATCH_PROMPT = (
    "Analyse these {n} job postings. For each, extract required vs preferred technical skills "
    "and assign a category.\n"
    "Return a JSON array with EXACTLY {n} objects (one per job, same order as input):\n"
    '[{{"required": ["skill1", "skill2"], "preferred": ["skill3"], "category": "Data & ML"}}, ...]\n\n'
    "Categories: {categories}\n"
    "- 'required': must-have skills, explicitly stated as essential or core to the role\n"
    "- 'preferred': nice-to-have, desired but not mandatory; leave empty [] if unclear\n"
    "Infer skills from the job title even if the description is absent.\n"
    "Return ONLY the JSON array. No explanation, no markdown.\n\n"
    "{jobs_block}"
)

_GEMINI_SINGLE_PROMPT = (
    "Analyse this job posting and return a single JSON object with three keys:\n"
    '- "required": array of MUST-HAVE technical skill strings\n'
    '- "preferred": array of NICE-TO-HAVE technical skill strings (empty [] if none)\n'
    '- "category": one of {categories}\n\n'
    "Return ONLY the JSON object. No explanation, no markdown.\n\n"
    "Job posting:\n{text}"
)


def _extract_batch_gemini(job_texts: list[str]) -> list[tuple[list[str], list[str], str]]:
    """Send all jobs in ONE Gemini call to conserve daily quota."""
    fallback: list[tuple[list[str], list[str], str]] = [([], [], "Other")] * len(job_texts)

    jobs_block = "\n\n".join(
        f"[JOB {i + 1}]\n{text[:1500]}"
        for i, text in enumerate(job_texts)
    )
    prompt = _GEMINI_BATCH_PROMPT.format(
        n=len(job_texts),
        categories=JOB_CATEGORIES,
        jobs_block=jobs_block,
    )

    client = _get_gemini_client()
    raw = ""
    for model in (GEMINI_MODEL_DEFAULT, GEMINI_MODEL_FALLBACK):
        try:
            response = client.models.generate_content(model=model, contents=prompt)
            raw = response.text
            break
        except Exception as e:
            err = str(e)
            if "429" in err or "RESOURCE_EXHAUSTED" in err or "quota" in err.lower():
                if model == GEMINI_MODEL_FALLBACK:
                    raise GeminiRateLimitError(err)
                log.warning("Rate limit on %s, retrying with %s", model, GEMINI_MODEL_FALLBACK)
                continue
            log.error("Gemini batch error on %s: %s", model, e)
            return fallback

    if not raw:
        return fallback

    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.MULTILINE).strip()
    m = re.search(r"\[.*\]", cleaned, re.DOTALL)
    if not m:
        log.warning("No JSON array in Gemini batch response: %r", raw[:300])
        return fallback

    try:
        arr = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        log.warning("Batch JSON parse error: %s | raw=%r", e, raw[:300])
        return fallback

    if not isinstance(arr, list):
        return fallback

    results: list[tuple[list[str], list[str], str]] = []
    for item in arr:
        if not isinstance(item, dict):
            results.append(([], [], "Other"))
            continue
        # Support both new {required, preferred} format and old {skills} format
        required = _parse_skills(json.dumps(item.get("required", item.get("skills", []))))
        preferred = _parse_skills(json.dumps(item.get("preferred", [])))
        cat = item.get("category", "Other")
        if cat not in JOB_CATEGORIES:
            cat = "Other"
        results.append((required, preferred, cat))

    while len(results) < len(job_texts):
        results.append(([], [], "Other"))
    return results[: len(job_texts)]


# ── Public API ────────────────────────────────────────────────────────────────

def extract_skills_batch(
    job_texts: list[str],
    model: str = GEMINI_MODEL_DEFAULT,
) -> list[tuple[list[str], list[str], str]]:
    """
    Extract required skills, preferred skills, and category for each job text.
    Returns list of (required_skills, preferred_skills, category) tuples.

    Uses local AI (Ollama/LM Studio) when LOCAL_MODEL_NAME is set in .env.
    Falls back to Gemini batch API (1 call for all jobs) otherwise.
    Raises GeminiRateLimitError if Gemini quota is exhausted.
    """
    if not job_texts:
        return []

    if LOCAL_MODEL_NAME:
        log.info("Using local model '%s' at %s for %d jobs", LOCAL_MODEL_NAME, LOCAL_AI_URL, len(job_texts))
        return _extract_batch_local(job_texts)

    return _extract_batch_gemini(job_texts)


def extract_skills_and_category(
    text: str, model: str = GEMINI_MODEL_DEFAULT
) -> tuple[list[str], list[str], str]:
    """Single-job extraction. Returns (required_skills, preferred_skills, category)."""
    if not text or not text.strip():
        return [], [], "Other"

    if LOCAL_MODEL_NAME:
        return _extract_one_local(text)

    # Gemini single-job path
    prompt = _GEMINI_SINGLE_PROMPT.format(
        categories=str(JOB_CATEGORIES),
        text=text[:8000],
    )
    client = _get_gemini_client()
    try:
        response = client.models.generate_content(model=model, contents=prompt)
        raw = response.text
    except Exception as e:
        log.error("Gemini single extraction error: %s", e)
        return [], [], "Other"

    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.MULTILINE).strip()
    m = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not m:
        return [], [], "Other"
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError:
        return [], [], "Other"

    required = _parse_skills(json.dumps(obj.get("required", obj.get("skills", []))))
    preferred = _parse_skills(json.dumps(obj.get("preferred", [])))
    cat = obj.get("category", "Other")
    if cat not in JOB_CATEGORIES:
        cat = "Other"
    return required, preferred, cat


def extract_skills(description: str, model: str = GEMINI_MODEL_DEFAULT) -> list[str]:
    """Extract skills only (no category). Used for resume parsing."""
    if not description or not description.strip():
        return []

    if LOCAL_MODEL_NAME:
        required, preferred, _ = _extract_one_local(description)
        return required + preferred

    client = _get_gemini_client()
    prompt = (
        "Extract required technical skills from this text. "
        "Return ONLY a JSON array of skill name strings. No explanation.\n\n"
        f"{description[:8000]}"
    )
    try:
        response = client.models.generate_content(model=model, contents=prompt)
        raw = response.text
    except Exception as e:
        log.error("Gemini skill extraction error: %s", e)
        return []
    return _parse_skills(raw)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_skills(raw: str) -> list[str]:
    if not raw:
        return []
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.MULTILINE).strip()
    match = re.search(r"\[.*?\]", cleaned, re.DOTALL)
    if match:
        cleaned = match.group(0)
    try:
        skills = json.loads(cleaned)
    except json.JSONDecodeError as e:
        log.warning("Could not parse skill list: %s | raw=%r", e, raw[:200])
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
