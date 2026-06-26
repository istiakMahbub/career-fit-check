"""
Career page scraper — fallback when Adzuna returns zero results.

Strategy (in priority order):
  1. Greenhouse JSON API  (boards-api.greenhouse.io)
  2. Lever JSON API       (api.lever.co)
  3. Static HTML          (requests + BeautifulSoup)
  4. Selenium             (headless Chrome for JS-rendered pages)

Greenhouse and Lever together cover the majority of tech-company ATS pages and
expose clean JSON endpoints — no HTML parsing needed.  The HTML / Selenium path
is a best-effort fallback for companies that host their own career pages.
"""

import logging
import re
import time
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

_SESSION = requests.Session()
_SESSION.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
})

REQUEST_TIMEOUT = 15
SELENIUM_TIMEOUT = 20


@dataclass
class ScrapedJob:
    title: str
    location: str = ""
    description: str = ""
    url: str = ""
    posted_date: str = ""


# ── slug helpers ──────────────────────────────────────────────────────────────

def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _extract_gh_slug(career_url: str) -> str:
    """boards.greenhouse.io/{slug} → slug"""
    m = re.search(r"greenhouse\.io/(?:boards/|embed/job_board\?for=)?([a-z0-9_-]+)", career_url, re.I)
    return m.group(1) if m else ""


def _extract_lever_slug(career_url: str) -> str:
    """jobs.lever.co/{slug} → slug"""
    m = re.search(r"lever\.co/([a-z0-9_-]+)", career_url, re.I)
    return m.group(1) if m else ""


# ── Greenhouse ────────────────────────────────────────────────────────────────

def _try_greenhouse(slug: str) -> list[ScrapedJob]:
    url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
    try:
        r = _SESSION.get(url, timeout=REQUEST_TIMEOUT)
        if r.status_code == 404:
            return []
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        log.debug("Greenhouse API miss for %s: %s", slug, e)
        return []

    jobs = []
    for j in data.get("jobs", []):
        jobs.append(ScrapedJob(
            title=j.get("title", "").strip(),
            location=(j.get("location") or {}).get("name", ""),
            description=_strip_html(j.get("content", "")),
            url=j.get("absolute_url", ""),
            posted_date=_parse_gh_date(j.get("updated_at", "")),
        ))
    log.info("Greenhouse: %d jobs for slug=%s", len(jobs), slug)
    return jobs


def _parse_gh_date(s: str) -> str:
    if not s:
        return ""
    try:
        from datetime import datetime
        return datetime.fromisoformat(s.rstrip("Z")).strftime("%Y-%m-%d")
    except Exception:
        return s[:10]


# ── Lever ─────────────────────────────────────────────────────────────────────

def _try_lever(slug: str) -> list[ScrapedJob]:
    url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
    try:
        r = _SESSION.get(url, timeout=REQUEST_TIMEOUT)
        if r.status_code in (404, 400):
            return []
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        log.debug("Lever API miss for %s: %s", slug, e)
        return []

    if not isinstance(data, list):
        return []

    jobs = []
    for j in data:
        cats = j.get("categories") or {}
        jobs.append(ScrapedJob(
            title=j.get("text", "").strip(),
            location=cats.get("location", "") or cats.get("allLocations", [""])[0] if cats.get("allLocations") else cats.get("location", ""),
            description=j.get("descriptionPlain", "").strip(),
            url=j.get("hostedUrl", ""),
            posted_date="",
        ))
    log.info("Lever: %d jobs for slug=%s", len(jobs), slug)
    return jobs


# ── Static HTML scraper ───────────────────────────────────────────────────────

_JOB_LINK_RE = re.compile(
    r"/jobs?/|/careers?/|/positions?|/openings?|/vacancies?|/roles?",
    re.I,
)
_JOB_TITLE_CLASSES = re.compile(
    r"job.?title|position.?title|role.?title|listing.?title|vacancy.?title|"
    r"opening.?title|job.?name|posting.?title",
    re.I,
)
_LOCATION_CLASSES = re.compile(
    r"location|city|workplace|office|place",
    re.I,
)


def _scrape_static(url: str, max_results: int = 50) -> list[ScrapedJob]:
    try:
        r = _SESSION.get(url, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
    except Exception as e:
        log.warning("Static fetch failed for %s: %s", url, e)
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    jobs = _parse_jobs_from_soup(soup, base_url=url)
    log.info("Static scrape: %d jobs from %s", len(jobs), url)
    return jobs[:max_results]


def _parse_jobs_from_soup(soup: BeautifulSoup, base_url: str) -> list[ScrapedJob]:
    jobs: list[ScrapedJob] = []
    seen_titles: set[str] = set()

    # Strategy A: links that look like job postings
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not _JOB_LINK_RE.search(href):
            continue
        title = a.get_text(separator=" ", strip=True)
        if not title or len(title) < 4 or len(title) > 120:
            continue
        title_key = title.lower()
        if title_key in seen_titles:
            continue
        seen_titles.add(title_key)

        abs_url = urljoin(base_url, href)
        location = _extract_nearby_location(a)
        jobs.append(ScrapedJob(title=title, location=location, url=abs_url))

    if jobs:
        return jobs

    # Strategy B: elements with job-title-like class/id names
    for el in soup.find_all(True):
        cls = " ".join(el.get("class", []))
        el_id = el.get("id", "")
        if not (_JOB_TITLE_CLASSES.search(cls) or _JOB_TITLE_CLASSES.search(el_id)):
            continue
        title = el.get_text(separator=" ", strip=True)
        if not title or len(title) < 4 or len(title) > 120:
            continue
        title_key = title.lower()
        if title_key in seen_titles:
            continue
        seen_titles.add(title_key)

        parent = el.parent
        link = parent.find("a", href=True) if parent else None
        url_out = urljoin(base_url, link["href"]) if link else ""
        location = _extract_nearby_location(el)
        jobs.append(ScrapedJob(title=title, location=location, url=url_out))

    return jobs


def _extract_nearby_location(el) -> str:
    """Look for location text in sibling/parent elements."""
    for candidate in (el.parent, el.find_next_sibling(), el.find_previous_sibling()):
        if candidate is None:
            continue
        cls = " ".join(getattr(candidate, "get", lambda k, d=None: d)("class", []))
        if _LOCATION_CLASSES.search(cls):
            txt = candidate.get_text(separator=" ", strip=True)
            if txt and len(txt) < 60:
                return txt
    return ""


def _strip_html(html: str) -> str:
    if not html:
        return ""
    return BeautifulSoup(html, "html.parser").get_text(separator=" ", strip=True)[:4000]


# ── Selenium fallback ─────────────────────────────────────────────────────────

def _scrape_selenium(url: str, max_results: int = 50) -> list[ScrapedJob]:
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        from webdriver_manager.chrome import ChromeDriverManager
    except ImportError as e:
        log.warning("Selenium/webdriver-manager not installed: %s", e)
        return []

    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--window-size=1280,900")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])

    driver = None
    try:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=opts)
        driver.set_page_load_timeout(SELENIUM_TIMEOUT)
        driver.get(url)

        # Wait for *any* link to appear (page loaded)
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.TAG_NAME, "a"))
        )
        time.sleep(2)  # let JS finish rendering job cards

        html = driver.page_source
        soup = BeautifulSoup(html, "html.parser")
        jobs = _parse_jobs_from_soup(soup, base_url=url)
        log.info("Selenium scrape: %d jobs from %s", len(jobs), url)
        return jobs[:max_results]

    except Exception as e:
        log.warning("Selenium scrape failed for %s: %s", url, e)
        return []
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass


# ── Career URL guesser ────────────────────────────────────────────────────────

def _guess_career_urls(website: str, company_name: str) -> list[str]:
    """Return candidate career page URLs to try, in preference order."""
    if not website:
        return []

    parsed = urlparse(website if "://" in website else "https://" + website)
    base = f"{parsed.scheme}://{parsed.netloc}"
    slug = _slugify(company_name)
    return [
        f"{base}/careers",
        f"{base}/jobs",
        f"{base}/en/careers",
        f"{base}/en/jobs",
        f"{base}/about/careers",
        f"https://jobs.lever.co/{slug}",
        f"https://boards.greenhouse.io/{slug}",
    ]


# ── Public entry point ────────────────────────────────────────────────────────

def scrape_company(
    company_name: str,
    career_url: str = "",
    website: str = "",
    max_results: int = 50,
) -> list[ScrapedJob]:
    """
    Scrape job postings for a company.

    Tries Greenhouse → Lever → static HTML → Selenium, in that order.
    Returns a (possibly empty) list of ScrapedJob objects.
    """
    slug = _slugify(company_name)

    # If career_url hints at a known ATS, try that ATS first with the real slug
    if career_url:
        if "greenhouse.io" in career_url:
            gh_slug = _extract_gh_slug(career_url) or slug
            jobs = _try_greenhouse(gh_slug)
            if jobs:
                return jobs[:max_results]

        if "lever.co" in career_url:
            lv_slug = _extract_lever_slug(career_url) or slug
            jobs = _try_lever(lv_slug)
            if jobs:
                return jobs[:max_results]

    # Try Greenhouse with company slug
    jobs = _try_greenhouse(slug)
    if jobs:
        return jobs[:max_results]

    # Try Lever with company slug
    jobs = _try_lever(slug)
    if jobs:
        return jobs[:max_results]

    # Build list of URLs to attempt HTML scraping
    urls_to_try: list[str] = []
    if career_url:
        urls_to_try.append(career_url)
    urls_to_try.extend(_guess_career_urls(website, company_name))

    for try_url in urls_to_try:
        jobs = _scrape_static(try_url, max_results)
        if jobs:
            return jobs
        time.sleep(1)

    # Selenium fallback on the most promising URL
    selenium_url = career_url or (urls_to_try[0] if urls_to_try else "")
    if selenium_url:
        jobs = _scrape_selenium(selenium_url, max_results)
        if jobs:
            return jobs

    log.info("Career page scraper: no jobs found for '%s'", company_name)
    return []
