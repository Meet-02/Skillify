import random
import re
import time
from datetime import datetime
from typing import Dict, List, Set, Tuple
from urllib.parse import quote_plus, urljoin

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
from app.models import UserCompanyRecord, UserProfile, UserSkills


_USER_AGENTS: List[str] = [
    # A small curated set to reduce the chance of uniform fingerprinting.
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
]


def _sleep_jitter(min_s: float = 3.0, max_s: float = 8.0) -> None:
    time.sleep(random.uniform(min_s, max_s))


DOMAIN_KEYWORDS: Dict[str, str] = {
    # Tech — granular role-level
    "frontend": "frontend developer",
    "backend": "backend developer",
    "fullstack": "full stack developer",
    "android": "android developer",
    "ios": "ios developer swift",
    "devops": "devops cloud engineer",
    "data": "data science analyst",
    "ml": "machine learning AI engineer",
    "dataeng": "data engineer ETL pipeline",
    "cyber": "cybersecurity information security",
    "uiux": "UI UX designer",
    "embedded": "embedded systems IoT firmware",
    "blockchain": "blockchain web3 solidity",
    "qa": "quality assurance software testing",
    "software": "software engineer developer",
    "product": "product manager",

    # Non-tech — major domains
    "marketing": "digital marketing",
    "finance": "finance accounting",
    "hr": "human resources HR recruiter",
    "sales": "sales business development",
    "operations": "operations supply chain",
    "content": "content writing copywriting",
    "design": "graphic design creative",
}


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


def _build_search_urls(portal: str, keyword: str, city: str) -> List[str]:
    q = quote_plus(keyword)
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", keyword.strip().lower()).strip("-")
    slug = slug.replace("--", "-")

    if portal == "linkedin":
        # LinkedIn may show sign-in prompts; still best-effort.
        loc = quote_plus(city or "")
        return [
            f"https://www.linkedin.com/jobs/search/?keywords={q}&location={loc}",
            f"https://www.linkedin.com/jobs/search/?keywords={q}",
        ]

    if portal == "internshala":
        # Internshala job search is frequently available via query strings.
        query = quote_plus(f"{keyword} {city}".strip())
        return [
            f"https://internshala.com/jobs/search/?search={query}",
            f"https://internshala.com/jobs/search/?search={q}",
        ]

    if portal == "jobhai":
        # JobHai uses location pages; query parameter support may vary.
        city_slug = re.sub(r"[^a-zA-Z0-9]+", "-", (city or "").strip().lower()).strip("-")
        query = quote_plus(f"{keyword} {city}".strip())
        return [
            f"https://www.jobhai.com/jobs-in-{city_slug}-cty",
            f"http://jobhai.com/jobs-in-{city_slug}-cty",
            f"https://www.jobhai.com/jobs?search={query}",
            f"https://www.jobhai.com/?s={query}",
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
    if portal == "linkedin":
        return [
            (By.CSS_SELECTOR, "li.reusable-search__result-container"),
            (By.CSS_SELECTOR, "div.base-card"),
            (By.CSS_SELECTOR, "ul.scaffold-layout__list-container li"),
        ]

    if portal == "internshala":
        return [
            (By.CSS_SELECTOR, "div.individual_internship"),
            (By.CSS_SELECTOR, "div.internship_container"),
            (By.CSS_SELECTOR, "div.internship_list"),
        ]

    if portal == "jobhai":
        return [
            # Broad job-card-ish containers; if this fails, fallback extraction is used.
            (By.CSS_SELECTOR, "div.job-card, div.job-card-item"),
            (By.CSS_SELECTOR, "article.job, div.job"),
            (By.CSS_SELECTOR, "a[href*='/jobs/'], a[href*='/job/']"),
        ]

    return []


def _within_card_selectors(portal: str) -> Dict[str, List[Tuple[By, str]]]:
    if portal == "linkedin":
        return {
            "title": [
                (By.CSS_SELECTOR, "h3.base-search-card__title"),
                (By.CSS_SELECTOR, "span[dir='ltr'] h3"),
                (By.CSS_SELECTOR, "h3"),
            ],
            "company": [
                (By.CSS_SELECTOR, "h4.base-search-card__subtitle"),
                (By.CSS_SELECTOR, "h4"),
                (By.CSS_SELECTOR, "span.base-search-card__subtitle"),
            ],
            "location": [
                (By.CSS_SELECTOR, "span.job-search-card__location"),
                (By.CSS_SELECTOR, "span.job-card-container__metadata-item"),
                (By.CSS_SELECTOR, "span.location"),
            ],
            "url": [
                (By.CSS_SELECTOR, "a.base-card__full-link"),
                (By.CSS_SELECTOR, "a.job-card-container__link"),
                (By.CSS_SELECTOR, "a[href*='/jobs/view/']"),
            ],
        }

    if portal == "internshala":
        return {
            "title": [
                (By.CSS_SELECTOR, "a[href*='/internship/']"),
                (By.CSS_SELECTOR, "a.job-title"),
                (By.CSS_SELECTOR, "h3"),
            ],
            "company": [
                (By.CSS_SELECTOR, "span.company"),
                (By.CSS_SELECTOR, "span.hiring-company"),
                (By.CSS_SELECTOR, "div.company"),
                (By.CSS_SELECTOR, "a[href*='/companies/']"),
            ],
            "location": [
                (By.CSS_SELECTOR, "span.location"),
                (By.CSS_SELECTOR, "div.location"),
                (By.CSS_SELECTOR, "span.job-location"),
            ],
            "url": [
                (By.CSS_SELECTOR, "a[href*='/internship/']"),
            ],
        }

    if portal == "jobhai":
        return {
            "title": [
                (By.CSS_SELECTOR, "a[href*='/jobs/']"),
                (By.CSS_SELECTOR, "a[href*='/job/']"),
                (By.CSS_SELECTOR, "h3"),
            ],
            "company": [
                (By.CSS_SELECTOR, "span.company"),
                (By.CSS_SELECTOR, "div.company"),
                (By.CSS_SELECTOR, "span.employer"),
            ],
            "location": [
                (By.CSS_SELECTOR, "span.location"),
                (By.CSS_SELECTOR, "span.city"),
            ],
            "url": [
                (By.CSS_SELECTOR, "a[href*='/jobs/']"),
                (By.CSS_SELECTOR, "a[href*='/job/']"),
            ],
        }

    return {"title": [], "company": [], "url": [], "location": []}


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

    stagnant_rounds = 0
    for _round in range(max_scroll_rounds):
        prev_len = len(collected)

        job_cards: List = []
        for by, sel in selectors:
            try:
                job_cards.extend(driver.find_elements(by, sel))
            except Exception:
                continue

        for card in job_cards:
            title = _try_find_first_text(card, within["title"])
            company = _try_find_first_text(card, within["company"])
            location = _try_find_first_text(card, within.get("location", []))
            url = _try_find_first_href(card, within["url"])

            title = title.strip()
            company = company.strip()
            location = (location or "").strip()
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
                    "location": location,
                    "url": url,
                }
            )
            if len(collected) >= max_jobs:
                return collected

        # Stop criteria: we've stopped making progress for a couple rounds.
        if len(collected) == prev_len:
            stagnant_rounds += 1
        else:
            stagnant_rounds = 0

        if stagnant_rounds >= 3:
            break

        # Scroll to trigger lazy loading / infinite scroll.
        try:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        except Exception:
            pass
        _sleep_jitter()

    return collected


def _fallback_extract_jobs_from_html(
    portal: str,
    page_source: str,
    base_url: str,
    max_jobs: int,
) -> List[Dict[str, str]]:
    soup = BeautifulSoup(page_source, "html.parser")
    jobs: List[Dict[str, str]] = []
    seen: Set[str] = set()

    def _add(url: str, title: str, company: str = "", location: str = "") -> None:
        if not url or not title:
            return
        full = urljoin(base_url, url)
        if full in seen:
            return
        seen.add(full)
        jobs.append(
            {
                "job_title": title.strip(),
                "company": (company or "").strip(),
                "location": (location or "").strip(),
                "url": full,
            }
        )

    if portal == "linkedin":
        cards = soup.select("li.reusable-search__result-container, li.scaffold-layout__list-item")
        for c in cards:
            a = c.select_one("a.base-card__full-link") or c.select_one("a[href*='/jobs/view/']")
            if not a or not a.get("href"):
                continue
            title_el = c.select_one("h3.base-search-card__title") or c.select_one("h3")
            company_el = c.select_one("h4.base-search-card__subtitle") or c.select_one("h4")
            loc_el = c.select_one("span.job-search-card__location") or c.select_one("span.location")
            _add(
                a.get("href"),
                title_el.get_text(" ", strip=True) if title_el else "",
                company_el.get_text(" ", strip=True) if company_el else "",
                loc_el.get_text(" ", strip=True) if loc_el else "",
            )
            if len(jobs) >= max_jobs:
                return jobs

    elif portal == "naukri":
        cards = soup.select("div.cust-job-tuple, div.jobTuple")
        for c in cards:
            title_a = c.select_one("a.job-title, a.job_title") or c.select_one("a[href*='/jobs/']")
            if not title_a or not title_a.get("href"):
                continue
            company_el = c.select_one("a.comp-name, span.comp-name, div.comp-name, span.company, a.company")
            loc_el = c.select_one("span.location, span.jd-loc, li.location, span.job-location")
            _add(
                title_a.get("href"),
                title_a.get_text(" ", strip=True),
                company_el.get_text(" ", strip=True) if company_el else "",
                loc_el.get_text(" ", strip=True) if loc_el else "",
            )
            if len(jobs) >= max_jobs:
                return jobs

    elif portal == "internshala":
        cards = soup.select("div.individual_internship, div.internship_container, div.internship_list")
        if not cards:
            cards = []
        if not cards:
            # Fallback: any internship link
            for a in soup.select("a[href*='/internship/']")[:200]:
                _add(
                    a.get("href"),
                    a.get_text(" ", strip=True),
                    "",
                    "",
                )
                if len(jobs) >= max_jobs:
                    return jobs
        else:
            for c in cards:
                a = c.select_one("a[href*='/internship/']")
                if not a or not a.get("href"):
                    continue
                title = a.get_text(" ", strip=True)
                company_el = c.select_one("span.company, span.hiring-company, div.company, a[href*='/companies/']")
                loc_el = c.select_one("span.location, div.location, span.job-location")
                _add(
                    a.get("href"),
                    title,
                    company_el.get_text(" ", strip=True) if company_el else "",
                    loc_el.get_text(" ", strip=True) if loc_el else "",
                )
                if len(jobs) >= max_jobs:
                    return jobs

    elif portal == "jobhai":
        # Heuristic based on likely URL patterns.
        for a in soup.select("a[href]")[:3000]:
            href = a.get("href") or ""
            if "/jobs/" not in href and "/job/" not in href:
                continue
            title = a.get_text(" ", strip=True)
            if len(title) < 4:
                continue
            card = a.find_parent(["div", "article"])  # best-effort context
            company_el = card.select_one("span.company, div.company, span.employer") if card else None
            loc_el = card.select_one("span.location, span.city") if card else None
            _add(
                href,
                title,
                company_el.get_text(" ", strip=True) if company_el else "",
                loc_el.get_text(" ", strip=True) if loc_el else "",
            )
            if len(jobs) >= max_jobs:
                return jobs

    return jobs


def _resolve_search_keyword(db: Session, user_id: int, domain: str) -> str:
    dom = (domain or "").strip().lower()
    if dom in DOMAIN_KEYWORDS:
        return DOMAIN_KEYWORDS[dom]

    prof = db.query(UserProfile).filter(UserProfile.user_id == user_id).first() if user_id else None
    if prof and prof.domain_interest and prof.domain_interest.strip():
        return prof.domain_interest.strip()

    return (domain or "").strip()


def _user_has_profile(db: Session, user_id: int) -> bool:
    if not user_id:
        return False
    return db.query(UserSkills).filter(UserSkills.user_id == user_id).first() is not None




def scrape_jobs_for_user(
    db: Session,
    user_id: int,
    domain: str,
    city: str,
    has_profile: bool = False,
    max_jobs: int = 40,
) -> List[Dict]:
    """
    Scrape LinkedIn, JobHai, Naukri, and Internshala search results.

    Saves each job into `User_Company_Record` with:
      - application_status = 'viewed'
      - match_score = 0
      - gap_severity = 'medium' (frontend may override to 'N/A' when has_profile=False)
    """
    keyword = _resolve_search_keyword(db=db, user_id=user_id, domain=domain) or ""
    keyword = keyword.strip() or "internship"

    portals: List[Tuple[str, str]] = [
        ("linkedin", "LinkedIn"),
        ("jobhai", "Job Hai"),
        ("internshala", "Internshala"),
    ]

    seen_job_urls: Set[str] = set()
    jobs_out: List[Dict] = []

    driver = _init_headless_driver(random.choice(_USER_AGENTS))
    try:
        for portal_id, publisher in portals:
            if len(jobs_out) >= max_jobs:
                break

            remaining = max_jobs - len(jobs_out)
            search_urls = _build_search_urls(portal_id, keyword, city)
            if not search_urls:
                continue

            for search_url in search_urls:
                if len(jobs_out) >= max_jobs:
                    break

                _set_user_agent(driver, random.choice(_USER_AGENTS))
                _sleep_jitter()

                try:
                    driver.get(search_url)
                except Exception:
                    continue

                _sleep_jitter()

                min_jobs = min(5, remaining)
                max_scroll_rounds = 8
                try:
                    portal_jobs = _collect_jobs_on_search_page(
                        driver=driver,
                        portal=portal_id,
                        max_jobs=remaining,
                        min_jobs=min_jobs,
                        max_scroll_rounds=max_scroll_rounds,
                    )
                except Exception:
                    portal_jobs = []

                # If selectors fail (common for LinkedIn/JobHai), fall back to HTML heuristics.
                if len(portal_jobs) < min_jobs:
                    portal_jobs = _fallback_extract_jobs_from_html(
                        portal=portal_id,
                        page_source=driver.page_source,
                        base_url=driver.current_url or search_url,
                        max_jobs=remaining,
                    )

                for job in portal_jobs:
                    if len(jobs_out) >= max_jobs:
                        break

                    job_title = (job.get("job_title") or "").strip()
                    company_name = (job.get("company") or "").strip() or "Unknown Company"
                    job_url = (job.get("url") or "").strip()
                    location = (job.get("location") or "").strip()

                    if not job_title or not job_url:
                        continue

                    if job_url in seen_job_urls:
                        continue
                    seen_job_urls.add(job_url)

                    # Upsert into User_Company_Record.
                    existing = (
                        db.query(UserCompanyRecord)
                        .filter(UserCompanyRecord.user_id == user_id)
                        .filter(UserCompanyRecord.company_name == company_name)
                        .filter(UserCompanyRecord.role_title == job_title)
                        .first()
                    )
                    if existing:
                        existing.application_status = "viewed"
                        existing.match_score = 0
                        existing.gap_severity = "medium"
                        existing.created_at = datetime.utcnow()
                    else:
                        db.add(
                            UserCompanyRecord(
                                user_id=user_id,
                                company_name=company_name,
                                role_title=job_title,
                                match_score=0,
                                gap_severity="medium",
                                application_status="viewed",
                                created_at=datetime.utcnow(),
                            )
                        )

                    jobs_out.append(
                        {
                            "title": job_title,
                            "employer": company_name,
                            "employer_logo": None,
                            "location": location or city,
                            "apply_link": job_url,
                            "posted_at": datetime.utcnow().isoformat(),
                            "employment_type": "Internship",
                            "publisher": publisher,
                            "qualifications": [],
                            "match_score": 0,
                            "gap_severity": "N/A" if not has_profile else "medium",
                            "missing_skills": {},
                            "has_profile": has_profile,
                        }
                    )

                    # Commit in batches to limit transaction overhead.
                    if len(jobs_out) % 10 == 0:
                        db.commit()

                    _sleep_jitter()

                # Stop early if we got enough from this search URL.
                if len(jobs_out) >= max_jobs:
                    break

    finally:
        try:
            driver.quit()
        except Exception:
            pass

    # Final commit for remaining rows.
    try:
        db.commit()
    except Exception:
        db.rollback()

    return jobs_out


def sync_jobs(db: Session, user_id: int, domain: str, city: str = "Mumbai") -> Dict[str, int]:
    jobs = scrape_jobs_for_user(
        db=db,
        user_id=user_id,
        domain=domain,
        city=city,
        has_profile=_user_has_profile(db, user_id),
        max_jobs=30,
    )
    return {"jobs_processed": len(jobs)}

def scrape_jobs_for_user_task(
    user_id: int,
    domain: str,
    city: str = "Mumbai",
    max_jobs: int = 40,
) -> List[Dict]:
    """
    Thread-safe wrapper for FastAPI: creates its own DB session.
    """
    db = SessionLocal()
    try:
        has_profile = _user_has_profile(db, user_id)
        return scrape_jobs_for_user(
            db=db,
            user_id=user_id,
            domain=domain,
            city=city,
            has_profile=has_profile,
            max_jobs=max_jobs,
        )
    finally:
        db.close()


def sync_jobs_task(user_id: int, domain: str = "", city: str = "Mumbai") -> Dict[str, int]:
    """
    Helper for FastAPI background tasks.
    Creates an isolated DB session for the background thread.
    """
    db = SessionLocal()
    try:
        return sync_jobs(db=db, user_id=user_id, domain=domain, city=city)
    finally:
        db.close()

