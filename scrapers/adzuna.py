"""
Adzuna API scraper — fetches job postings for a given company and location.

Free tier: 1000 calls/month. Docs: https://developer.adzuna.com/docs/search
"""

import os
import time
import logging
from dataclasses import dataclass
from datetime import datetime

import requests
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger(__name__)

ADZUNA_BASE = "https://api.adzuna.com/v1/api/jobs"
DEFAULT_COUNTRY = "de"
RESULTS_PER_PAGE = 50


@dataclass
class AdzunaJob:
    title: str
    location: str
    description: str
    url: str
    posted_date: str


def fetch_jobs(
    company_name: str,
    location: str = "Berlin",
    country: str = DEFAULT_COUNTRY,
    max_results: int = 100,
) -> list[AdzunaJob]:
    """
    Fetch job postings for a company from Adzuna.

    Returns a list of AdzunaJob dataclasses. Raises RuntimeError if credentials
    are missing. Returns an empty list if Adzuna finds nothing.
    """
    app_id = os.getenv("ADZUNA_APP_ID")
    api_key = os.getenv("ADZUNA_API_KEY")

    if not app_id or not api_key:
        raise RuntimeError(
            "ADZUNA_APP_ID and ADZUNA_API_KEY must be set in .env"
        )

    jobs: list[AdzunaJob] = []
    page = 1
    results_per_page = min(RESULTS_PER_PAGE, max_results)

    while len(jobs) < max_results:
        url = f"{ADZUNA_BASE}/{country}/search/{page}"
        params = {
            "app_id": app_id,
            "app_key": api_key,
            "results_per_page": results_per_page,
            "company": company_name,
            "where": location,
            "content-type": "application/json",
        }

        try:
            resp = requests.get(url, params=params, timeout=15)
            resp.raise_for_status()
        except requests.HTTPError as e:
            log.error("Adzuna HTTP error %s: %s", e.response.status_code, e)
            break
        except requests.RequestException as e:
            log.error("Adzuna request failed: %s", e)
            break

        data = resp.json()
        results = data.get("results", [])

        if not results:
            break

        for r in results:
            jobs.append(_parse_result(r))
            if len(jobs) >= max_results:
                break

        # Adzuna paginates; stop if we got fewer than a full page
        if len(results) < results_per_page:
            break

        page += 1
        time.sleep(1)  # be polite

    log.info("Adzuna: fetched %d jobs for '%s' in %s", len(jobs), company_name, location)
    return jobs


def _parse_result(r: dict) -> AdzunaJob:
    location_parts = r.get("location", {}).get("display_name", "")
    posted_raw = r.get("created", "")
    posted_date = _parse_date(posted_raw)

    return AdzunaJob(
        title=r.get("title", "").strip(),
        location=location_parts,
        description=r.get("description", "").strip(),
        url=r.get("redirect_url", ""),
        posted_date=posted_date,
    )


def _parse_date(iso_str: str) -> str:
    """Convert Adzuna's ISO 8601 string to YYYY-MM-DD, or return as-is."""
    if not iso_str:
        return ""
    try:
        return datetime.fromisoformat(iso_str.rstrip("Z")).strftime("%Y-%m-%d")
    except ValueError:
        return iso_str
