"""
Career page scraper — extracts job postings from company career pages.

Strategy (in priority order):
  1. Greenhouse JSON API    (boards-api.greenhouse.io)
  2. Lever JSON API         (api.lever.co)
  3. SmartRecruiters API    (api.smartrecruiters.com) — with pagination
  4. ATS auto-detection     — fetches the career page HTML and looks for
                              SmartRecruiters or Workday fingerprints.
                              Handles custom domains like karriere.miele.de
                              that are white-labelled SmartRecruiters/Workday.
  5. Static HTML            (requests + BeautifulSoup)
  6. Selenium               (headless Chrome for JS-rendered pages)

ATS detection covers the most common enterprise career platforms, allowing
the app to pull full job listings even when companies use custom domains.
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
SELENIUM_TIMEOUT = 25


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


def _extract_sr_slug(career_url: str) -> str:
    """jobs.smartrecruiters.com/{slug} → slug"""
    m = re.search(r"smartrecruiters\.com/([a-zA-Z0-9_-]+)", career_url, re.I)
    return m.group(1) if m else ""


_CAREER_SUBDOMAIN_RE = re.compile(
    r"^(?:www|careers?|jobs?|apply|work|karriere|stellenangebote|"
    r"vacatures?|emplois?|vacantes?|carriere|werkenbij|joinen|talent|join|recrutement)\.",
    re.I,
)


def _domain_slug_from_url(career_url: str) -> str:
    """
    Extract the company slug from a career page URL's domain.

    karriere.miele.de  → miele
    careers.zalando.com → zalando
    jobs.lever.co → (skip — already handled)
    """
    try:
        from urllib.parse import urlparse
        host = urlparse(career_url).hostname or ""
        host = host.lower()
        # Strip career subdomains iteratively (handles multi-prefix edge cases)
        stripped = _CAREER_SUBDOMAIN_RE.sub("", host)
        parts = stripped.split(".")
        # For ccTLDs (e.g. miele.de) take parts[-2]; single-part fallback
        if len(parts) >= 2:
            return re.sub(r"[^a-z0-9]+", "-", parts[-2]).strip("-")
        return re.sub(r"[^a-z0-9]+", "-", parts[0]).strip("-")
    except Exception:
        return ""


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
        location = (
            cats.get("location", "")
            or (cats.get("allLocations", [""])[0] if cats.get("allLocations") else "")
        )
        jobs.append(ScrapedJob(
            title=j.get("text", "").strip(),
            location=location,
            description=j.get("descriptionPlain", "").strip(),
            url=j.get("hostedUrl", ""),
            posted_date="",
        ))
    log.info("Lever: %d jobs for slug=%s", len(jobs), slug)
    return jobs


# ── SmartRecruiters ───────────────────────────────────────────────────────────

def _try_smartrecruiters(slug: str, max_jobs: int = 500) -> list[ScrapedJob]:
    """Query the public SmartRecruiters API with pagination."""
    jobs: list[ScrapedJob] = []
    limit = 100
    offset = 0

    while True:
        url = (
            f"https://api.smartrecruiters.com/v1/companies/{slug}/postings"
            f"?limit={limit}&offset={offset}"
        )
        try:
            r = _SESSION.get(url, timeout=REQUEST_TIMEOUT)
            if r.status_code in (400, 403, 404):
                return []
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            log.debug("SmartRecruiters API miss for %s: %s", slug, e)
            return jobs  # return what we have so far

        if not isinstance(data, dict):
            break

        page = data.get("content", [])
        if not page:
            break

        for j in page:
            loc = j.get("location") or {}
            location = loc.get("city", "") or loc.get("country", "") or ""
            sections = (j.get("jobAd") or {}).get("sections") or {}
            desc_html = (sections.get("jobDescription") or {}).get("text", "")
            jobs.append(ScrapedJob(
                title=j.get("name", "").strip(),
                location=location,
                description=_strip_html(desc_html),
                url=j.get("ref", ""),
                posted_date=(j.get("releasedDate") or "")[:10],
            ))

        total = data.get("totalFound", 0)
        offset += len(page)
        if offset >= total or offset >= max_jobs:
            break
        time.sleep(0.5)

    log.info("SmartRecruiters: %d jobs for slug=%s", len(jobs), slug)
    return jobs


# ── Workday ───────────────────────────────────────────────────────────────────

def _try_workday(tenant: str, career_site: str = "") -> list[ScrapedJob]:
    """
    Query Workday's internal CXS jobs API.
    tenant = subdomain like 'miele', career_site = e.g. 'Miele_External_Career_Site'
    """
    if not career_site:
        career_site = f"{tenant.capitalize()}_External_Career_Site"

    for wday_ver in ("wd5", "wd3", "wd1"):
        api_url = (
            f"https://{tenant}.{wday_ver}.myworkdayjobs.com/"
            f"wday/cxs/{tenant}/{career_site}/jobs"
        )
        try:
            r = _SESSION.post(
                api_url,
                json={"limit": 100, "offset": 0, "searchText": "", "locations": []},
                headers={"Content-Type": "application/json"},
                timeout=REQUEST_TIMEOUT,
            )
            if r.status_code in (400, 403, 404):
                continue
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            log.debug("Workday API failed %s: %s", api_url, e)
            continue

        postings = data.get("jobPostings") or []
        if not postings:
            continue

        jobs = []
        for j in postings:
            title = j.get("title", "").strip()
            location = (j.get("locationsText") or "").strip()
            ext_path = j.get("externalPath", "")
            job_url = f"https://{tenant}.{wday_ver}.myworkdayjobs.com{ext_path}" if ext_path else ""
            posted = (j.get("postedOn") or "")[:10]
            jobs.append(ScrapedJob(title=title, location=location, url=job_url, posted_date=posted))

        log.info("Workday: %d jobs for tenant=%s site=%s", len(jobs), tenant, career_site)
        return jobs

    return []


# ── my-job-shop.com (Typesense) ──────────────────────────────────────────────

def _try_jobshop(career_url: str) -> list[ScrapedJob]:
    """
    Scrape career pages powered by my-job-shop.com.

    These pages (e.g. karriere.miele.de) are Nuxt.js SPAs that embed a
    Typesense scoped search key in their SSR payload. We extract that key
    from the page HTML and call the Typesense API directly to get all jobs.
    """
    import json as _json

    try:
        r = _SESSION.get(career_url, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        html = r.text
    except Exception as e:
        log.debug("job-shop fetch failed for %s: %s", career_url, e)
        return []

    if "job-shop.com" not in html and "my-job-shop.com" not in html:
        return []

    # The SSR payload is in: <script type="application/json" data-nuxt-data="nuxt-app" id="__NUXT_DATA__">
    # Find it via BeautifulSoup using the id or data attribute.
    soup = BeautifulSoup(html, "html.parser")
    nuxt_tag = (
        soup.find("script", id="__NUXT_DATA__")
        or soup.find("script", attrs={"data-nuxt-data": "nuxt-app"})
    )
    if not nuxt_tag or not nuxt_tag.string:
        log.debug("job-shop: __NUXT_DATA__ script not found in %s", career_url)
        return []

    ts_key = ""
    try:
        arr = _json.loads(nuxt_tag.string)
    except Exception as e:
        log.debug("job-shop: SSR JSON parse error: %s", e)
        return []

    if not isinstance(arr, list) or len(arr) < 10:
        return []

    # Find the state dict that references "typesenseApiKey-{uuid}": <index>
    state = next(
        (x for x in arr if isinstance(x, dict) and "jobShopData" in x),
        None,
    )
    if state:
        for k, v in state.items():
            if "typesenseApiKey" in k and isinstance(v, int) and len(arr) > v:
                candidate = arr[v]
                if isinstance(candidate, str) and len(candidate) > 20:
                    ts_key = candidate
                    break

    if not ts_key:
        log.debug("job-shop: could not extract Typesense key from %s", career_url)
        return []

    log.info("job-shop.com detected — querying Typesense for %s", career_url)
    jobs: list[ScrapedJob] = []
    page = 1

    while True:
        try:
            resp = _SESSION.get(
                "https://api.my-job-shop.com/api/typesense/collections/offers/documents/search",
                params={"q": "*", "per_page": 100, "page": page},
                headers={"X-TYPESENSE-API-KEY": ts_key},
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            log.warning("job-shop Typesense query error: %s", e)
            break

        hits = data.get("hits", [])
        if not hits:
            break

        for hit in hits:
            doc = hit.get("document", {})
            title = (doc.get("title") or "").strip()
            if not title:
                continue
            locs = doc.get("location") or []
            location = ", ".join(locs) if isinstance(locs, list) else str(locs)
            desc_html = doc.get("description") or doc.get("teaser") or ""
            url = doc.get("url") or doc.get("application_url") or ""
            posted = doc.get("start_date") or ""
            # Convert "dd.mm.yyyy" → "yyyy-mm-dd"
            if posted and re.match(r"\d{2}\.\d{2}\.\d{4}", posted):
                try:
                    from datetime import datetime as _dt
                    posted = _dt.strptime(posted, "%d.%m.%Y").strftime("%Y-%m-%d")
                except Exception:
                    pass
            jobs.append(ScrapedJob(
                title=title,
                location=location,
                description=_strip_html(desc_html),
                url=url,
                posted_date=posted,
            ))

        total = data.get("found", 0)
        if page * 100 >= total:
            break
        page += 1
        time.sleep(0.3)

    log.info("job-shop.com: %d jobs from %s", len(jobs), career_url)
    return jobs


# ── ATS auto-detection from page HTML ─────────────────────────────────────────

# Patterns that identify the ATS powering a custom career domain
_SR_SLUG_RE = re.compile(
    r'(?:smartrecruiters\.com/|"companyIdentifier"\s*:\s*"|'
    r'company["\s:]+")([A-Za-z][A-Za-z0-9_-]{2,})',
    re.I,
)
_WD_TENANT_RE = re.compile(
    r'([\w-]+)\.wd\d+\.myworkdayjobs\.com', re.I
)
_WD_SITE_RE = re.compile(
    r'myworkdayjobs\.com/[^/"]+/([^/"?]+)', re.I
)

_SR_SLUG_BLOCKLIST = frozenset({
    "api", "v1", "v2", "jobs", "postings", "search", "content",
    "candidates", "tracking", "apply", "widget", "embed",
})


def _check_ats_in_html(html: str, source_url: str = "") -> list[ScrapedJob]:
    """
    Given page HTML (static or rendered), detect which ATS powers it and
    return jobs via the appropriate API. Works for both requests and Selenium HTML.
    """
    # SmartRecruiters detection
    for m in _SR_SLUG_RE.finditer(html):
        slug = m.group(1).strip().strip('"').strip("'")
        if slug.lower() not in _SR_SLUG_BLOCKLIST and len(slug) >= 3:
            log.info("Detected SmartRecruiters slug=%s from %s", slug, source_url)
            jobs = _try_smartrecruiters(slug)
            if jobs:
                return jobs

    # Workday detection
    wd_m = _WD_TENANT_RE.search(html)
    if wd_m:
        tenant = wd_m.group(1)
        site_m = _WD_SITE_RE.search(html)
        career_site = site_m.group(1) if site_m else ""
        log.info("Detected Workday tenant=%s site=%s from %s", tenant, career_site, source_url)
        jobs = _try_workday(tenant, career_site)
        if jobs:
            return jobs

    return []


def _detect_ats_and_scrape(career_url: str) -> list[ScrapedJob]:
    """
    Auto-detect the ATS powering a custom career domain and scrape via its API.

    Step 1: job-shop.com (Typesense) — e.g. karriere.miele.de
    Step 2: SmartRecruiters / Workday from static HTML
    Step 3: SmartRecruiters / Workday from Selenium-rendered HTML (JS pages)
    """
    # Step 1: job-shop.com (Typesense) — detects from static HTML
    jobs = _try_jobshop(career_url)
    if jobs:
        return jobs

    # Step 2: static fetch for SR/Workday
    try:
        r = _SESSION.get(career_url, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        jobs = _check_ats_in_html(r.text, career_url)
        if jobs:
            return jobs
    except Exception as e:
        log.debug("ATS static fetch failed for %s: %s", career_url, e)

    # Step 2: Selenium-rendered HTML
    log.info("ATS static detection found nothing — trying Selenium render for %s", career_url)
    rendered = _selenium_get_rendered_html(career_url)
    if rendered:
        jobs = _check_ats_in_html(rendered, career_url)
        if jobs:
            return jobs

    return []


# ── noise / quality helpers ───────────────────────────────────────────────────

# Phrases that flag a scraped title as navigation / page-section noise,
# not a real job posting.
_NOISE_PHRASES = frozenset({
    "learn more", "find out more", "read more", "apply now",
    "reasons to join", "application process", "how to apply",
    "faq", "frequently asked", "about us", "contact us",
    "privacy policy", "cookie", "terms of use", "terms and conditions",
    "sign in", "log in", "register", "newsletter", "site map",
    "all jobs", "search jobs", "load more", "show more",
    "view all", "see all", "get started", "back to top",
    "no results", "clear filter", "reset search", "subscribe",
    "accessibility", "imprint", "legal notice", "data protection",
})

# Common words in real job titles
_JOB_TITLE_PATTERN = re.compile(
    r"\b(engineer|developer|scientist|analyst|manager|lead|director|"
    r"specialist|consultant|coordinator|designer|architect|researcher|"
    r"recruiter|administrator|operator|writer|strategist|officer|executive|"
    r"technician|advisor|inspector|trainer|supervisor|planner|"
    r"senior|junior|intern|associate|principal|staff|head of|vp |"
    r"data|software|product|devops|cloud|backend|frontend|"
    r"machine learning|fullstack|full-stack|platform|security|qa|sre)\b",
    re.I,
)


def _is_noise(title: str) -> bool:
    t = title.lower()
    return any(phrase in t for phrase in _NOISE_PHRASES)


def _looks_like_job(title: str) -> bool:
    return bool(_JOB_TITLE_PATTERN.search(title))


def _has_quality_results(jobs: list[ScrapedJob]) -> bool:
    """
    Return True only if the scraped list looks like real job postings.
    Rejects batches that are purely navigation/section links.
    """
    if not jobs:
        return False
    clean = [j for j in jobs if not _is_noise(j.title)]
    if not clean:
        return False
    # At least 1/3 of clean results must look like genuine job titles
    job_like = sum(1 for j in clean if _looks_like_job(j.title))
    return job_like >= max(1, len(clean) // 3)


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
        if not title or len(title) < 5 or len(title) > 120:
            continue
        if _is_noise(title):
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
        if not title or len(title) < 5 or len(title) > 120:
            continue
        if _is_noise(title):
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


# ── Selenium helpers ──────────────────────────────────────────────────────────

# "Load more" button text in various languages
_LOAD_MORE_RE = re.compile(
    r"^(load more|show more|mehr anzeigen|meer laden|voir plus|"
    r"more jobs|more results|next page|weiter|suivant|volgende)$",
    re.I,
)


def _selenium_driver():
    """Create a headless Chrome driver."""
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from webdriver_manager.chrome import ChromeDriverManager

    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--window-size=1280,900")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=opts)
    driver.set_page_load_timeout(SELENIUM_TIMEOUT)
    return driver


def _selenium_get_rendered_html(url: str) -> str:
    """
    Load a page with Selenium and return its fully-rendered HTML.
    Waits for JS to settle and scrolls once to trigger lazy loaders.
    Returns empty string on failure.
    """
    driver = None
    try:
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        driver = _selenium_driver()
        driver.get(url)
        WebDriverWait(driver, 12).until(
            EC.presence_of_element_located((By.TAG_NAME, "a"))
        )
        driver.execute_script("window.scrollBy(0, 600);")
        time.sleep(2)
        return driver.page_source
    except Exception as e:
        log.debug("Selenium render failed for %s: %s", url, e)
        return ""
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass


def _scrape_selenium(url: str, max_results: int = 50) -> list[ScrapedJob]:
    """
    Scrape a JS-rendered career page with Selenium.
    Clicks "Load more" / "Next page" buttons and scrolls to get all jobs.
    Also checks the rendered HTML for SmartRecruiters / Workday identifiers
    before falling back to HTML link extraction.
    """
    try:
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
    except ImportError as e:
        log.warning("Selenium not installed: %s", e)
        return []

    driver = None
    try:
        driver = _selenium_driver()
        driver.get(url)
        WebDriverWait(driver, 12).until(
            EC.presence_of_element_located((By.TAG_NAME, "a"))
        )
        time.sleep(2)

        # Try to detect ATS from fully-rendered HTML first (catches SR/Workday)
        rendered_html = driver.page_source
        ats_jobs = _check_ats_in_html(rendered_html, url)
        if ats_jobs:
            log.info("Selenium: ATS detected from rendered HTML — %d jobs", len(ats_jobs))
            return ats_jobs[:max_results]

        # Pagination loop: scroll + click "Load more" until stable
        prev_count = 0
        for _ in range(20):  # up to 20 load-more clicks
            # Scroll to bottom to trigger infinite scroll
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(1.2)

            # Look for "Load more" type buttons and click the first visible one
            clicked = False
            for btn in driver.find_elements(By.XPATH, "//button | //a[@role='button']"):
                try:
                    txt = btn.text.strip()
                    if _LOAD_MORE_RE.match(txt) and btn.is_displayed():
                        driver.execute_script("arguments[0].click();", btn)
                        time.sleep(1.5)
                        clicked = True
                        break
                except Exception:
                    continue

            # Check if we have more jobs than before
            soup = BeautifulSoup(driver.page_source, "html.parser")
            current_jobs = _parse_jobs_from_soup(soup, base_url=url)
            if len(current_jobs) == prev_count and not clicked:
                break  # nothing new — we've loaded everything
            prev_count = len(current_jobs)
            if len(current_jobs) >= max_results:
                break

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
    max_results: int = 500,
) -> list[ScrapedJob]:
    """
    Scrape job postings for a company.

    Priority order:
    1. Greenhouse / Lever / SmartRecruiters API (if URL hints at known ATS)
    2. Same APIs tried with company-name slug + domain-derived slug
    3. ATS auto-detection: fetch the career page and detect SR/Workday from HTML
       (handles custom domains like karriere.miele.de → SmartRecruiters API)
    4. Static HTML scraping
    5. Selenium (for JS-rendered pages)

    Returns a (possibly empty) list of ScrapedJob objects.
    """
    slug = _slugify(company_name)

    # Also derive a slug from the career URL domain (handles "karriere.miele.de" → "miele")
    domain_slug = _domain_slug_from_url(career_url) if career_url else ""
    # Collect unique slugs to try; company slug first, domain slug as fallback
    slugs_to_try: list[str] = [slug]
    if domain_slug and domain_slug != slug:
        slugs_to_try.append(domain_slug)

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

        if "smartrecruiters.com" in career_url:
            sr_slug = _extract_sr_slug(career_url) or slug
            jobs = _try_smartrecruiters(sr_slug)
            if jobs:
                return jobs[:max_results]

    # Try Greenhouse, Lever, SmartRecruiters with each candidate slug
    for s in slugs_to_try:
        jobs = _try_greenhouse(s)
        if jobs:
            return jobs[:max_results]

    for s in slugs_to_try:
        jobs = _try_lever(s)
        if jobs:
            return jobs[:max_results]

    for s in slugs_to_try:
        jobs = _try_smartrecruiters(s)
        if jobs:
            return jobs[:max_results]

    # ATS auto-detection: fetch the career page and look for SmartRecruiters /
    # Workday fingerprints in the HTML. Catches custom domains like karriere.miele.de.
    if career_url and not any(
        known in career_url
        for known in ("greenhouse.io", "lever.co", "smartrecruiters.com", "workday.com", "myworkdayjobs.com")
    ):
        jobs = _detect_ats_and_scrape(career_url)
        if jobs:
            return jobs[:max_results]

    # Build list of URLs to attempt HTML scraping
    urls_to_try: list[str] = []
    if career_url:
        urls_to_try.append(career_url)
    urls_to_try.extend(_guess_career_urls(website, company_name))

    for try_url in urls_to_try:
        jobs = _scrape_static(try_url, max_results)
        if _has_quality_results(jobs):
            return jobs
        time.sleep(1)

    # Selenium fallback — triggered whenever static HTML returned nothing useful.
    # This covers JS-rendered job boards (Next.js, React, Workday, custom platforms).
    selenium_url = career_url or (urls_to_try[0] if urls_to_try else "")
    if selenium_url:
        jobs = _scrape_selenium(selenium_url, max_results)
        if _has_quality_results(jobs):
            return jobs

    # Nothing useful found — return empty so the Adzuna fallback can run.
    log.info("Career page scraper: no quality jobs found for '%s'", company_name)
    return []
