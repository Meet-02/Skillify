import random
import re
import time
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import quote_plus

import pandas as pd
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import Skills, TrendingSkills, UserCompanyRecord, UserProfile


_USER_AGENTS: List[str] = [
    # A small curated set to reduce the chance of uniform fingerprinting.
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
]


def _sleep_jitter(min_s: float = 2.0, max_s: float = 4.5) -> None:
    time.sleep(random.uniform(min_s, max_s))


def _init_headless_driver(user_agent: str) -> webdriver.Chrome:
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument(f"--user-agent={user_agent}")

    # Best-effort to reduce automation signals.
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option("useAutomationExtension", False)

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    driver.set_page_load_timeout(45)
    return driver


def _set_user_agent(driver: webdriver.Chrome, user_agent: str) -> None:
    # Rotate fingerprint without restarting the browser.
    try:
        driver.execute_cdp_cmd(
            "Network.setUserAgentOverride",
            {"userAgent": user_agent},
        )
    except Exception:
        # CDP may fail in restricted environments; ignore and continue.
        pass


def _domain_interest_to_keyword(domain_interest: str) -> str:
    kw = (domain_interest or "").strip()
    if not kw:
        return ""
    # Keep a readable keyword but normalize separators.
    kw = re.sub(r"\s+", " ", kw)
    kw = kw.replace("/", " ")
    return kw


def _build_search_urls(portal: str, keyword: str) -> List[str]:
    q = quote_plus(keyword)
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", keyword.strip().lower()).strip("-")
    slug = slug.replace("--", "-")

    if portal == "naukri":
        return [
            # Most common pattern:
            f"https://www.naukri.com/{slug}-jobs",
            # Fallbacks:
            f"https://www.naukri.com/{slug}-jobs?searchType=regular&searchPhrase={q}",
            f"https://www.naukri.com/{q}-jobs",
        ]

    if portal == "iimjobs":
        return [
            f"https://www.iimjobs.com/search-jobs?query={q}",
            f"https://www.iimjobs.com/search-jobs?search={q}",
            f"https://www.iimjobs.com/search-jobs?keyword={q}",
        ]

    return []


def _extract_text_or_empty(el) -> str:
    try:
        return (el.text or "").strip()
    except Exception:
        return ""


def _extract_href_or_empty(el) -> str:
    try:
        href = el.get_attribute("href") or ""
        return href.strip()
    except Exception:
        return ""


def _try_find_first_text(container, selectors: List[Tuple[By, str]]) -> str:
    for by, sel in selectors:
        try:
            el = container.find_element(by, sel)
            txt = _extract_text_or_empty(el)
            if txt:
                return txt
        except Exception:
            continue
    return ""


def _try_find_first_href(container, selectors: List[Tuple[By, str]]) -> str:
    for by, sel in selectors:
        try:
            el = container.find_element(by, sel)
            href = _extract_href_or_empty(el)
            if href:
                return href
        except Exception:
            continue
    return ""


def _job_card_selectors(portal: str) -> List[Tuple[By, str]]:
    # These are best-effort selectors; portal DOMs change frequently.
    if portal == "naukri":
        return [
            (By.CSS_SELECTOR, "div.cust-job-tuple"),
            (By.CSS_SELECTOR, "div.jobTuple"),
            (By.CSS_SELECTOR, "div.row.cust-job-tuple"),
        ]

    if portal == "iimjobs":
        return [
            (By.CSS_SELECTOR, "div.job-card"),
            (By.CSS_SELECTOR, "div.search-results div"),
            (By.CSS_SELECTOR, "div.job-listing"),
        ]

    return []


def _within_card_selectors(portal: str) -> Dict[str, List[Tuple[By, str]]]:
    if portal == "naukri":
        return {
            "title": [
                (By.CSS_SELECTOR, "a.job-title"),
                (By.CSS_SELECTOR, "a.job_title"),
                (By.CSS_SELECTOR, "a[data-track-label='job_title']"),
                (By.CSS_SELECTOR, "a[href*='/jobs/']"),
            ],
            "company": [
                (By.CSS_SELECTOR, "a.comp-name"),
                (By.CSS_SELECTOR, "span.comp-name"),
                (By.CSS_SELECTOR, "div.comp-name"),
                (By.CSS_SELECTOR, "span.company"),
                (By.CSS_SELECTOR, "a.company"),
            ],
            "url": [
                (By.CSS_SELECTOR, "a.job-title"),
                (By.CSS_SELECTOR, "a.job_title"),
                (By.CSS_SELECTOR, "a[href*='/jobs/']"),
                (By.CSS_SELECTOR, "a[href*='naukri.com/jobs']"),
            ],
        }

    if portal == "iimjobs":
        return {
            "title": [
                (By.CSS_SELECTOR, "a.job-title"),
                (By.CSS_SELECTOR, "a.jobTitle"),
                (By.CSS_SELECTOR, "a[href*='/jobs/']"),
            ],
            "company": [
                (By.CSS_SELECTOR, "span.company"),
                (By.CSS_SELECTOR, "div.company"),
                (By.CSS_SELECTOR, "span.org"),
                (By.CSS_SELECTOR, "div.org"),
            ],
            "url": [
                (By.CSS_SELECTOR, "a[href*='/jobs/']"),
                (By.CSS_SELECTOR, "a[href*='iimjobs.com/jobs']"),
            ],
        }

    return {"title": [], "company": [], "url": []}


def _collect_jobs_on_search_page(
    driver: webdriver.Chrome,
    portal: str,
    max_jobs: int,
    min_jobs: int,
    max_scroll_rounds: int = 12,
) -> List[Dict[str, str]]:
    selectors = _job_card_selectors(portal)
    within = _within_card_selectors(portal)

    collected: List[Dict[str, str]] = []
    seen: Set[str] = set()

    wait = WebDriverWait(driver, 15)
    for by, sel in selectors:
        try:
            wait.until(EC.presence_of_element_located((by, sel)))
            break
        except TimeoutException:
            continue

    for _round in range(max_scroll_rounds):
        job_cards: List = []
        for by, sel in selectors:
            try:
                job_cards.extend(driver.find_elements(by, sel))
            except Exception:
                continue

        for card in job_cards:
            title = _try_find_first_text(card, within["title"])
            company = _try_find_first_text(card, within["company"])
            url = _try_find_first_href(card, within["url"])

            title = title.strip()
            company = company.strip()
            url = url.strip()

            if not url or not title:
                continue

            if url in seen:
                continue

            seen.add(url)
            collected.append(
                {
                    "job_title": title,
                    "company": company,
                    "url": url,
                }
            )
            if len(collected) >= max_jobs:
                return collected

        if len(collected) >= min_jobs:
            # Stop early once we have enough.
            break

        # Scroll to trigger lazy loading.
        try:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        except Exception:
            pass
        _sleep_jitter(1.5, 3.0)

    return collected


def _extract_job_description_text(driver: webdriver.Chrome) -> str:
    soup = BeautifulSoup(driver.page_source, "html.parser")

    candidates = [
        "div#jd_content",
        "div.job-description",
        "div#job-description",
        "section.job-description",
        "div[data-testid='job-description']",
        "article",
        "main",
        "[itemprop='description']",
        "body",
    ]
    for css in candidates:
        el = soup.select_one(css)
        if el:
            txt = el.get_text(" ", strip=True)
            txt = re.sub(r"\s+", " ", txt).strip()
            if len(txt) >= 120:
                return txt

    txt = soup.get_text(" ", strip=True)
    txt = re.sub(r"\s+", " ", txt).strip()
    return txt


def _match_skills_in_text(skills: List[Tuple[int, str]], text: str) -> Set[int]:
    # Simple substring matching; it aligns with the current "skills mentioned in description"
    # requirement without requiring an ML model at scrape-time.
    t = (text or "").lower()
    matched: Set[int] = set()

    # Sort by length desc to reduce partial overlaps (e.g., "AI" vs "Artificial Intelligence").
    for skill_id, skill_name_lower in skills:
        if not skill_name_lower:
            continue
        # A lightweight heuristic: require presence as substring.
        if skill_name_lower in t:
            matched.add(skill_id)
    return matched


def sync_jobs(db: Session, user_id: int, domain: str) -> Dict[str, int]:
    """
    Scrape job listings from Naukri and IIMJobs and update:
      - `User_Company_Record` for each job (application_status='saved', match_score=0)
      - `Trending_Skills` for each skill matched in the job description.
    """
    # Resolve keyword from the user's profile.
    prof = db.query(UserProfile).filter(UserProfile.user_id == user_id).first()
    domain_interest = _domain_interest_to_keyword(
        (prof.domain_interest if prof else "") or domain or ""
    )
    if not domain_interest:
        return {"jobs_processed": 0, "skills_matched": 0}

    # Load all skills once per session.
    skills_rows: List[Tuple[int, str]] = (
        db.query(Skills.skill_id, Skills.skill_name).all()
    )
    skills_rows = [(sid, (name or "").lower().strip()) for sid, name in skills_rows]
    skills_rows = [(sid, n) for sid, n in skills_rows if n]
    skills_rows.sort(key=lambda x: len(x[1]), reverse=True)

    keyword = domain_interest
    driver_ua = random.choice(_USER_AGENTS)
    driver = _init_headless_driver(driver_ua)

    jobs_target_min = 20
    jobs_target_max = 50

    total_jobs_processed = 0
    total_skills_matched = 0

    portals = ["naukri", "iimjobs"]
    try:
        for portal in portals:
            if total_jobs_processed >= jobs_target_max:
                break

            search_urls = _build_search_urls(portal, keyword)
            portal_jobs: List[Dict[str, str]] = []

            for url in search_urls:
                try:
                    _set_user_agent(driver, random.choice(_USER_AGENTS))
                    _sleep_jitter()
                    driver.get(url)
                    portal_jobs = _collect_jobs_on_search_page(
                        driver=driver,
                        portal=portal,
                        max_jobs=jobs_target_max - total_jobs_processed,
                        min_jobs=max(5, jobs_target_min - total_jobs_processed),
                    )
                    if portal_jobs:
                        break
                except (TimeoutException, WebDriverException):
                    continue
                except Exception:
                    continue

            if not portal_jobs:
                continue

            # Use pandas mainly to match your requested "structured data manipulation" step.
            df = pd.DataFrame(portal_jobs)
            df = df.drop_duplicates(subset=["url"])
            portal_jobs_dedup = df.to_dict(orient="records")

            for job in portal_jobs_dedup:
                if total_jobs_processed >= jobs_target_max:
                    break

                job_title = (job.get("job_title") or "").strip()
                company_name = (job.get("company") or "").strip() or "Unknown Company"
                job_url = (job.get("url") or "").strip()
                if not job_title or not job_url:
                    continue

                # Randomly rotate UA before opening detail.
                _set_user_agent(driver, random.choice(_USER_AGENTS))
                _sleep_jitter(1.5, 3.5)

                try:
                    driver.get(job_url)
                    _sleep_jitter(1.5, 3.0)
                except Exception:
                    continue

                description_text = _extract_job_description_text(driver)
                matched_skill_ids = _match_skills_in_text(skills_rows, description_text)
                total_skills_matched += len(matched_skill_ids)

                # Persist the job -> UserCompanyRecord mapping.
                existing = (
                    db.query(UserCompanyRecord)
                    .filter(UserCompanyRecord.user_id == user_id)
                    .filter(UserCompanyRecord.company_name == company_name)
                    .filter(UserCompanyRecord.role_title == job_title)
                    .first()
                )
                if existing:
                    existing.application_status = "saved"
                    existing.match_score = 0
                    existing.gap_severity = "medium"
                else:
                    db.add(
                        UserCompanyRecord(
                            user_id=user_id,
                            company_name=company_name,
                            role_title=job_title,
                            match_score=0,
                            gap_severity="medium",
                            application_status="saved",
                            created_at=datetime.utcnow(),
                        )
                    )

                # Persist skill demand -> TrendingSkills increments.
                for sid in matched_skill_ids:
                    trend = (
                        db.query(TrendingSkills)
                        .filter(TrendingSkills.skill_id == sid)
                        .first()
                    )
                    if trend:
                        trend.demand_score = int(trend.demand_score or 0) + 1
                        trend.last_updated = datetime.utcnow()
                    else:
                        db.add(
                            TrendingSkills(
                                skill_id=sid,
                                demand_score=1,
                                last_updated=datetime.utcnow(),
                            )
                        )

                db.commit()
                total_jobs_processed += 1

                # Extra jitter between processed jobs.
                _sleep_jitter(1.0, 2.5)

            if total_jobs_processed >= jobs_target_max:
                break

        # If we failed to reach the minimum, we still return counts.
        return {
            "jobs_processed": total_jobs_processed,
            "skills_matched": total_skills_matched,
        }
    finally:
        try:
            driver.quit()
        except Exception:
            pass


def sync_jobs_task(user_id: int, domain: str = "") -> Dict[str, int]:
    """
    Helper for FastAPI background tasks.
    Creates an isolated DB session for the background thread.
    """
    db = SessionLocal()
    try:
        return sync_jobs(db=db, user_id=user_id, domain=domain)
    finally:
        db.close()

