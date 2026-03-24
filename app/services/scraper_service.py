"""
scraper_service.py — Hybrid Job Aggregator for Skillify
=========================================================
Architecture: Dual-Stream Acquisition
  • API Stream   → RapidAPI / JSearch  (structured JSON, fast)
  • Scraper Stream → Internshala + Job Hai (Selenium + BeautifulSoup, public-only)

Both streams emit a Unified Job Schema, then the results are merged
50/50 and de-duplicated before being returned to the caller.

Public entry points
-------------------
  get_jobs(db, user_id, domain, city, max_jobs)  ← call from match_service.py
  scrape_jobs_for_user_task(...)                  ← FastAPI background task wrapper
  sync_jobs_task(...)                             ← legacy sync helper
"""

from __future__ import annotations

import os
import random
import re
import time
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import quote_plus, urljoin, urlencode

import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from sqlalchemy.orm import Session
from webdriver_manager.chrome import ChromeDriverManager

from app.database import SessionLocal
from app.models import UserCompanyRecord, UserProfile, UserSkills


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Paste your RapidAPI key here or, better, set env var RAPIDAPI_KEY.
# The code falls back gracefully if the key is missing / quota is exhausted.
RAPIDAPI_KEY: str = os.getenv("RAPIDAPI_KEY", "YOUR_RAPIDAPI_KEY_HERE")
JSEARCH_HOST: str = "jsearch.p.rapidapi.com"

# How many jobs each stream tries to contribute (merged total ≈ max_jobs).
# The 50/50 split is enforced in `get_jobs`.
_API_SHARE: float = 0.50

_USER_AGENTS: List[str] = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) "
    "Gecko/20100101 Firefox/124.0",
]

DOMAIN_KEYWORDS: Dict[str, str] = {
    "frontend":   "frontend developer",
    "backend":    "backend developer",
    "fullstack":  "full stack developer",
    "android":    "android developer",
    "ios":        "ios developer swift",
    "devops":     "devops cloud engineer",
    "data":       "data science analyst",
    "ml":         "machine learning AI engineer",
    "dataeng":    "data engineer ETL pipeline",
    "cyber":      "cybersecurity information security",
    "uiux":       "UI UX designer",
    "embedded":   "embedded systems IoT firmware",
    "blockchain": "blockchain web3 solidity",
    "qa":         "quality assurance software testing",
    "software":   "software engineer developer",
    "product":    "product manager",
    "marketing":  "digital marketing",
    "finance":    "finance accounting",
    "hr":         "human resources HR recruiter",
    "sales":      "sales business development",
    "operations": "operations supply chain",
    "content":    "content writing copywriting",
    "design":     "graphic design creative",
}


# ===========================================================================
# UNIFIED JOB SCHEMA
# ===========================================================================
# Every job — whether it came from an API or a scraper — must be mapped to:
#
#   {
#       "title":       str,   # job title
#       "company":     str,   # company / employer name
#       "location":    str,   # city / remote label
#       "link":        str,   # canonical apply / detail URL
#       "description": str,   # snippet or full text (may be empty)
#       "source_type": str,   # "API" | "Scraped"
#   }
#
# The helper _make_job() enforces this contract.
# ---------------------------------------------------------------------------

def _make_job(
    title: str,
    company: str,
    location: str,
    link: str,
    description: str = "",
    source_type: str = "Scraped",
) -> Dict[str, str]:
    """Return a validated Unified Job Schema dict."""
    return {
        "title":       (title or "").strip(),
        "company":     (company or "Unknown Company").strip(),
        "location":    (location or "").strip(),
        "link":        (link or "").strip(),
        "description": (description or "").strip(),
        "source_type": source_type,
    }


# ===========================================================================
# STREAM 1 — API ACQUISITION (JSearch via RapidAPI)
# ===========================================================================

def _fetch_jobs_from_api(
    keyword: str,
    city: str,
    max_jobs: int,
) -> List[Dict[str, str]]:
    """
    Fetch jobs from the JSearch RapidAPI endpoint and map the JSON
    response to the Unified Job Schema.

    Returns an empty list on any error so the scraper stream still runs.
    """
    if RAPIDAPI_KEY in ("", "YOUR_RAPIDAPI_KEY_HERE"):
        print("[API Stream] RAPIDAPI_KEY not configured — skipping API stream.")
        return []

    query = f"{keyword} {city}".strip()
    url = "https://jsearch.p.rapidapi.com/search"
    params = {
        "query":         query,
        "page":          "1",
        "num_pages":     "1",
        "date_posted":   "month",
    }
    headers = {
        "X-RapidAPI-Key":  RAPIDAPI_KEY,
        "X-RapidAPI-Host": JSEARCH_HOST,
    }

    try:
        response = requests.get(url, headers=headers, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.Timeout:
        print("[API Stream] Request timed out — returning empty list.")
        return []
    except requests.exceptions.ConnectionError as exc:
        print(f"[API Stream] Connection error: {exc} — returning empty list.")
        return []
    except requests.exceptions.HTTPError as exc:
        print(f"[API Stream] HTTP error {exc.response.status_code} — returning empty list.")
        return []
    except Exception as exc:
        print(f"[API Stream] Unexpected error: {exc} — returning empty list.")
        return []

    # --- Transformation Layer: JSON → Unified Schema ---
    unified: List[Dict[str, str]] = []
    for raw in data.get("data", []):
        job = _make_job(
            title=raw.get("job_title", ""),
            company=raw.get("employer_name", ""),
            location=raw.get("job_city") or raw.get("job_country") or city,
            link=raw.get("job_apply_link") or raw.get("job_google_link", ""),
            description=raw.get("job_description", "")[:500],   # cap snippet
            source_type="API",
        )
        if job["title"] and job["link"]:
            unified.append(job)
        if len(unified) >= max_jobs:
            break

    print(f"[API Stream] Retrieved {len(unified)} jobs.")
    return unified


# ===========================================================================
# STREAM 2 — SCRAPER ACQUISITION (Internshala + Job Hai)
# ===========================================================================

# ---------------------------------------------------------------------------
# Bot-detection defences
# ---------------------------------------------------------------------------

def _sleep_jitter(min_s: float = 3.0, max_s: float = 8.0) -> None:
    """Randomised delay to mimic human browsing cadence."""
    time.sleep(random.uniform(min_s, max_s))


def _init_headless_driver(user_agent: str) -> webdriver.Chrome:
    """
    Instantiate a headless Chrome driver with anti-detection hardening.
    Runs in headless mode — no visible browser window.
    """
    opts = Options()
    opts.add_argument("--headless=new")          # true headless (Chrome ≥ 112)
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument(f"--user-agent={user_agent}")
    # Suppress webdriver automation flags
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=opts)
    driver.set_page_load_timeout(45)
    return driver


def _rotate_user_agent(driver: webdriver.Chrome) -> None:
    """Hot-swap the User-Agent mid-session via Chrome DevTools Protocol."""
    ua = random.choice(_USER_AGENTS)
    try:
        driver.execute_cdp_cmd(
            "Network.setUserAgentOverride",
            {"userAgent": ua},
        )
    except Exception:
        pass   # CDP may be unavailable in some environments; non-fatal


# ---------------------------------------------------------------------------
# URL builders — public search pages only, no login required
# ---------------------------------------------------------------------------

def _build_internshala_url(keyword: str, city: str) -> str:
    """
    Build a public Internshala job/internship search URL.
    Uses urllib.parse.urlencode to safely encode arbitrary query strings.
    """
    query = f"{keyword} {city}".strip()
    params = urlencode({"search": query})
    return f"https://internshala.com/jobs/search/?{params}"


def _build_jobhai_url(keyword: str, city: str) -> str:
    """
    Build a public Job Hai search URL.
    Falls back to a query-string approach if city slug would be empty.
    """
    query = f"{keyword} {city}".strip()
    params = urlencode({"q": query})
    return f"https://www.jobhai.com/jobs?{params}"


# ---------------------------------------------------------------------------
# BeautifulSoup parsers — Transformation Layer: HTML → Unified Schema
# ---------------------------------------------------------------------------

def _parse_internshala_html(html: str, base_url: str, max_jobs: int) -> List[Dict[str, str]]:
    """Extract job cards from Internshala search results page HTML."""
    soup = BeautifulSoup(html, "html.parser")
    jobs: List[Dict[str, str]] = []
    seen: Set[str] = set()

    # Primary selectors for individual internship/job cards
    cards = soup.select(
        "div.individual_internship, "
        "div.internship_container, "
        "div.internship_meta"
    )

    if not cards:
        # Broad fallback: any link pointing to an internship/job detail page
        for a in soup.select("a[href*='/internship/'], a[href*='/job/']"):
            href = urljoin(base_url, a.get("href", ""))
            title = a.get_text(" ", strip=True)
            if href and title and href not in seen:
                seen.add(href)
                jobs.append(_make_job(
                    title=title, company="", location="", link=href,
                    source_type="Scraped"
                ))
            if len(jobs) >= max_jobs:
                return jobs
        return jobs

    for card in cards:
        a = (
            card.select_one("a[href*='/internship/']")
            or card.select_one("a[href*='/job/']")
        )
        if not a:
            continue

        href = urljoin(base_url, a.get("href", ""))
        if not href or href in seen:
            continue
        seen.add(href)

        title = a.get_text(" ", strip=True)
        company_el = card.select_one(
            "span.company, span.hiring-company, "
            "div.company, a[href*='/companies/']"
        )
        loc_el = card.select_one(
            "span.location, div.location, "
            "span.job-location, span.location_link"
        )
        desc_el = card.select_one("div.internship_other_details, div.job-details")

        jobs.append(_make_job(
            title=title,
            company=company_el.get_text(" ", strip=True) if company_el else "",
            location=loc_el.get_text(" ", strip=True) if loc_el else "",
            link=href,
            description=desc_el.get_text(" ", strip=True)[:300] if desc_el else "",
            source_type="Scraped",
        ))
        if len(jobs) >= max_jobs:
            break

    return jobs


def _parse_jobhai_html(html: str, base_url: str, max_jobs: int) -> List[Dict[str, str]]:
    """Extract job cards from Job Hai search results page HTML."""
    soup = BeautifulSoup(html, "html.parser")
    jobs: List[Dict[str, str]] = []
    seen: Set[str] = set()

    # Attempt structured card selectors first
    cards = soup.select(
        "div.job-card, div.job-card-item, "
        "article.job, div.jobCard, li.job-listing"
    )

    if cards:
        for card in cards:
            a = (
                card.select_one("a[href*='/jobs/']")
                or card.select_one("a[href*='/job/']")
                or card.select_one("a[href]")
            )
            if not a:
                continue
            href = urljoin(base_url, a.get("href", ""))
            if not href or href in seen:
                continue
            seen.add(href)

            title_el = card.select_one("h2, h3, .job-title, .title")
            company_el = card.select_one("span.company, div.company, span.employer")
            loc_el = card.select_one("span.location, span.city, div.location")

            jobs.append(_make_job(
                title=title_el.get_text(" ", strip=True) if title_el
                      else a.get_text(" ", strip=True),
                company=company_el.get_text(" ", strip=True) if company_el else "",
                location=loc_el.get_text(" ", strip=True) if loc_el else "",
                link=href,
                source_type="Scraped",
            ))
            if len(jobs) >= max_jobs:
                return jobs
    else:
        # Heuristic fallback: any anchor containing a job-path pattern
        for a in soup.select("a[href]")[:2000]:
            href = a.get("href", "")
            if "/jobs/" not in href and "/job/" not in href:
                continue
            href = urljoin(base_url, href)
            title = a.get_text(" ", strip=True)
            if len(title) < 4 or href in seen:
                continue
            seen.add(href)
            jobs.append(_make_job(
                title=title, company="", location="", link=href,
                source_type="Scraped"
            ))
            if len(jobs) >= max_jobs:
                break

    return jobs


# ---------------------------------------------------------------------------
# Core scraper orchestrator
# ---------------------------------------------------------------------------

_PORTAL_CONFIG: Dict[str, Dict] = {
    "internshala": {
        "label":     "Internshala",
        "url_fn":    _build_internshala_url,
        "parser_fn": _parse_internshala_html,
        "wait_css":  "div.individual_internship, div.internship_container",
    },
    "jobhai": {
        "label":     "Job Hai",
        "url_fn":    _build_jobhai_url,
        "parser_fn": _parse_jobhai_html,
        "wait_css":  "div.job-card, div.job-card-item, article.job",
    },
}


def _fetch_jobs_from_scrapers(
    keyword: str,
    city: str,
    max_jobs: int,
) -> List[Dict[str, str]]:
    """
    Drive Internshala and Job Hai public search pages with Selenium,
    parse HTML with BeautifulSoup, and return Unified Schema dicts.

    Gracefully handles TimeoutException and connection failures so the
    API stream results still reach the user if scraping is blocked.
    """
    all_scraped: List[Dict[str, str]] = []
    seen_links: Set[str] = set()
    driver: Optional[webdriver.Chrome] = None

    try:
        driver = _init_headless_driver(random.choice(_USER_AGENTS))

        for portal_id, cfg in _PORTAL_CONFIG.items():
            if len(all_scraped) >= max_jobs:
                break

            remaining = max_jobs - len(all_scraped)
            search_url = cfg["url_fn"](keyword, city)

            _rotate_user_agent(driver)
            _sleep_jitter(2.0, 5.0)

            print(f"[Scraper Stream] Loading {cfg['label']}: {search_url}")
            try:
                driver.get(search_url)
            except (TimeoutException, WebDriverException) as exc:
                print(f"[Scraper Stream] Page load failed for {cfg['label']}: {exc}")
                continue

            # Wait for the first meaningful card element to appear
            try:
                WebDriverWait(driver, 20).until(
                    EC.presence_of_element_located(
                        (By.CSS_SELECTOR, cfg["wait_css"])
                    )
                )
            except TimeoutException:
                print(
                    f"[Scraper Stream] Wait timed out on {cfg['label']} — "
                    "falling back to raw HTML parse."
                )

            # Scroll once to trigger lazy-loaded content
            try:
                driver.execute_script(
                    "window.scrollTo(0, document.body.scrollHeight);"
                )
            except Exception:
                pass
            _sleep_jitter(2.0, 4.0)

            # --- Transformation Layer: HTML → Unified Schema ---
            page_html = driver.page_source
            base_url = driver.current_url or search_url
            parsed = cfg["parser_fn"](page_html, base_url, remaining)

            for job in parsed:
                if job["link"] and job["link"] not in seen_links:
                    seen_links.add(job["link"])
                    all_scraped.append(job)
                if len(all_scraped) >= max_jobs:
                    break

            print(
                f"[Scraper Stream] {cfg['label']}: collected {len(parsed)} jobs "
                f"(total so far: {len(all_scraped)})"
            )

    except Exception as exc:
        # Any unexpected driver crash must not kill the whole request
        print(f"[Scraper Stream] Fatal driver error: {exc} — returning partial results.")

    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass

    return all_scraped


# ===========================================================================
# DE-DUPLICATION
# ===========================================================================

def _dedup_jobs(jobs: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """
    Remove duplicate jobs across both streams.
    Primary key: normalised link.
    Secondary key: normalised (title, company) pair when links differ.
    """
    seen_links: Set[str] = set()
    seen_title_company: Set[Tuple[str, str]] = set()
    unique: List[Dict[str, str]] = []

    for job in jobs:
        link = (job.get("link") or "").strip().lower().rstrip("/")
        title = re.sub(r"\s+", " ", (job.get("title") or "").lower().strip())
        company = re.sub(r"\s+", " ", (job.get("company") or "").lower().strip())
        tc_key = (title, company)

        if link and link in seen_links:
            continue
        if title and tc_key in seen_title_company:
            continue

        if link:
            seen_links.add(link)
        if title:
            seen_title_company.add(tc_key)
        unique.append(job)

    return unique


# ===========================================================================
# DATABASE PERSISTENCE
# ===========================================================================

def _persist_jobs(
    db: Session,
    user_id: int,
    jobs: List[Dict[str, str]],
    has_profile: bool,
    city: str,
) -> List[Dict]:
    """
    Upsert jobs into UserCompanyRecord and enrich each dict with the
    extra fields that match_service.py / the frontend expect.
    """
    enriched: List[Dict] = []

    for job in jobs:
        title = job["title"]
        company = job["company"] or "Unknown Company"
        link = job["link"]

        if not title or not link:
            continue

        existing = (
            db.query(UserCompanyRecord)
            .filter(
                UserCompanyRecord.user_id == user_id,
                UserCompanyRecord.company_name == company,
                UserCompanyRecord.role_title == title,
            )
            .first()
        )

        if existing:
            existing.application_status = "viewed"
            existing.match_score = 0
            existing.gap_severity = "medium"
            existing.created_at = datetime.utcnow()
        else:
            db.add(UserCompanyRecord(
                user_id=user_id,
                company_name=company,
                role_title=title,
                match_score=0,
                gap_severity="medium",
                application_status="viewed",
                created_at=datetime.utcnow(),
            ))

        enriched.append({
            # Unified Schema fields
            "title":       title,
            "company":     company,
            "location":    job.get("location") or city,
            "link":        link,
            "description": job.get("description", ""),
            "source_type": job.get("source_type", "Scraped"),
            # Legacy / frontend compatibility fields
            "employer":          company,
            "employer_logo":     None,
            "apply_link":        link,
            "posted_at":         datetime.utcnow().isoformat(),
            "employment_type":   "Internship",
            "publisher":         job.get("source_type", "Scraped"),
            "qualifications":    [],
            "match_score":       0,
            "gap_severity":      "N/A" if not has_profile else "medium",
            "missing_skills":    {},
            "has_profile":       has_profile,
        })

        if len(enriched) % 10 == 0:
            try:
                db.commit()
            except Exception:
                db.rollback()

    try:
        db.commit()
    except Exception:
        db.rollback()

    return enriched


# ===========================================================================
# PUBLIC ENTRY POINT — get_jobs()
# ===========================================================================

def get_jobs(
    db: Session,
    user_id: int,
    domain: str,
    city: str = "Mumbai",
    max_jobs: int = 40,
) -> List[Dict]:
    """
    Hybrid Job Aggregator — the single function to call from match_service.py.

    Workflow
    --------
    1. Resolve keyword from domain / user profile.
    2. Fire both streams concurrently (sequentially for simplicity; swap to
       ThreadPoolExecutor if latency is critical).
    3. Merge with a 50/50 quota, then de-duplicate.
    4. Persist to UserCompanyRecord and return enriched dicts.

    Parameters
    ----------
    db        : SQLAlchemy session
    user_id   : authenticated user's ID
    domain    : raw domain string ("frontend", "data", etc.)
    city      : location for job search
    max_jobs  : hard cap on total results returned

    Returns
    -------
    List of Unified Job Schema dicts enriched with match_service fields.
    """
    keyword = _resolve_search_keyword(db=db, user_id=user_id, domain=domain)
    has_profile = _user_has_profile(db, user_id)

    api_quota = max(1, int(max_jobs * _API_SHARE))
    scraper_quota = max_jobs - api_quota

    print(f"[get_jobs] keyword='{keyword}' city='{city}' "
          f"api_quota={api_quota} scraper_quota={scraper_quota}")

    # --- Stream 1: API ---
    api_jobs = _fetch_jobs_from_api(keyword=keyword, city=city, max_jobs=api_quota)

    # --- Stream 2: Scrapers (graceful fallback on timeout / block) ---
    try:
        scraped_jobs = _fetch_jobs_from_scrapers(
            keyword=keyword, city=city, max_jobs=scraper_quota
        )
    except (TimeoutException, Exception) as exc:
        print(f"[get_jobs] Scraper stream failed ({exc}); using API results only.")
        scraped_jobs = []

    # --- Merge 50/50 then de-duplicate ---
    # Interleave so neither source is truncated from the front
    merged: List[Dict[str, str]] = []
    for pair in zip(api_jobs, scraped_jobs):
        merged.extend(pair)
    merged += api_jobs[len(scraped_jobs):]
    merged += scraped_jobs[len(api_jobs):]

    unique = _dedup_jobs(merged)[:max_jobs]
    print(f"[get_jobs] After merge + dedup: {len(unique)} unique jobs.")

    # --- Persist & enrich ---
    return _persist_jobs(
        db=db,
        user_id=user_id,
        jobs=unique,
        has_profile=has_profile,
        city=city,
    )


# ===========================================================================
# HELPERS (shared)
# ===========================================================================

def _resolve_search_keyword(db: Session, user_id: int, domain: str) -> str:
    dom = (domain or "").strip().lower()
    if dom in DOMAIN_KEYWORDS:
        return DOMAIN_KEYWORDS[dom]

    if user_id:
        prof = (
            db.query(UserProfile)
            .filter(UserProfile.user_id == user_id)
            .first()
        )
        if prof and prof.domain_interest and prof.domain_interest.strip():
            return prof.domain_interest.strip()

    return (domain or "").strip() or "internship"


def _user_has_profile(db: Session, user_id: int) -> bool:
    if not user_id:
        return False
    return (
        db.query(UserSkills)
        .filter(UserSkills.user_id == user_id)
        .first()
    ) is not None


# ===========================================================================
# FASTAPI / BACKGROUND-TASK WRAPPERS  (backwards compatible)
# ===========================================================================

def scrape_jobs_for_user(
    db: Session,
    user_id: int,
    domain: str,
    city: str,
    has_profile: bool = False,
    max_jobs: int = 40,
) -> List[Dict]:
    """Legacy wrapper — delegates to get_jobs."""
    return get_jobs(db=db, user_id=user_id, domain=domain, city=city, max_jobs=max_jobs)


def scrape_jobs_for_user_task(
    user_id: int,
    domain: str,
    city: str = "Mumbai",
    max_jobs: int = 40,
) -> List[Dict]:
    """Thread-safe wrapper for FastAPI background tasks (creates its own DB session)."""
    db = SessionLocal()
    try:
        return get_jobs(db=db, user_id=user_id, domain=domain, city=city, max_jobs=max_jobs)
    finally:
        db.close()


def sync_jobs(db: Session, user_id: int, domain: str, city: str = "Mumbai") -> Dict[str, int]:
    jobs = get_jobs(db=db, user_id=user_id, domain=domain, city=city, max_jobs=30)
    return {"jobs_processed": len(jobs)}


def sync_jobs_task(user_id: int, domain: str = "", city: str = "Mumbai") -> Dict[str, int]:
    """Helper for FastAPI background tasks."""
    db = SessionLocal()
    try:
        return sync_jobs(db=db, user_id=user_id, domain=domain, city=city)
    finally:
        db.close()
