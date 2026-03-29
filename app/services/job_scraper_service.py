"""
app/services/job_scraper_service.py
────────────────────────────────────────────────────────────────────────────────
Parallel job aggregator:
  • Internshala  — Selenium scraper  (internships)
  • Indeed IN    — Selenium scraper  (jobs/internships)
  • JSearch API  — httpx async call  (jobs via RapidAPI)

All three run CONCURRENTLY via asyncio + ThreadPoolExecutor.
Results are:
  1. Scored + ranked with run_matching_pipeline
  2. Saved to CSV  (tmp/jobs_cache/<domain>_<city>_<timestamp>.csv)
  3. Returned sorted by match_score descending
────────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import asyncio
import csv
import os
import pickle
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import undetected_chromedriver as uc
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

load_dotenv()

JSEARCH_API_KEY: str = os.getenv("JSEARCH_API_KEY", "")
INDEED_COOKIES_FILE: str = os.getenv("INDEED_COOKIES_FILE", "indeed_cookies.pkl")

# ── CSV cache directory ──────────────────────────────────────────────────────
_ROOT = Path(__file__).resolve().parent.parent.parent
CACHE_DIR = _ROOT / "tmp" / "jobs_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# ── Thread-pool shared by both Selenium scrapers ─────────────────────────────
_EXECUTOR = ThreadPoolExecutor(max_workers=4)

# ════════════════════════════════════════════════════════════════════════════
# DOMAIN → KEYWORD MAP  (mirrors main.py DOMAIN_KEYWORDS)
# ════════════════════════════════════════════════════════════════════════════
DOMAIN_KEYWORDS: dict[str, str] = {
    "":           "",
    "software":   "Software Engineer",
    "frontend":   "Frontend Developer",
    "backend":    "Backend Developer",
    "fullstack":  "Full Stack Developer",
    "android":    "Android Developer",
    "ios":        "iOS Developer",
    "devops":     "DevOps",
    "data":       "Data Science",
    "ml":         "Machine Learning",
    "dataeng":    "Data Engineer",
    "uiux":       "UI UX Designer",
    "qa":         "QA Testing",
    "cyber":      "Cybersecurity",
    "product":    "Product Manager",
    "embedded":   "Embedded Systems",
    "blockchain": "Blockchain",
    "marketing":  "Marketing",
    "finance":    "Finance",
    "hr":         "Human Resources",
    "sales":      "Sales",
    "operations": "Operations",
    "content":    "Content Writer",
    "design":     "Graphic Designer",
}

# ════════════════════════════════════════════════════════════════════════════
# SKILL EXTRACTION  (fast keyword-only, no spaCy)
# ════════════════════════════════════════════════════════════════════════════
KNOWN_SKILLS = sorted([
    # Languages
    "python","java","javascript","typescript","c++","c#","c","ruby","go","golang",
    "php","swift","kotlin","scala","rust","perl","r","dart","objective-c","bash",
    "shell","powershell","groovy","lua","haskell","elixir","erlang","vba","matlab",
    # Web / Frontend
    "react","angular","vue","html","css","sass","scss","bootstrap","jquery",
    "next.js","nuxt.js","gatsby","remix","astro","svelte","sveltekit","webpack",
    "vite","redux","zustand","tailwind","tailwindcss","material ui","graphql",
    "three.js","d3.js","pwa","webgl","webassembly","rxjs","storybook",
    # Backend / Frameworks
    "node.js","nodejs","express","expressjs","nestjs","fastify","django","flask",
    "fastapi","spring","spring boot","spring mvc","hibernate","rails","laravel",
    "symfony","asp.net",".net",".net core","gin","fiber","phoenix","grpc",
    "microservices","rest api","restful","soap","websocket","oauth","jwt","swagger",
    # Databases
    "sql","mysql","postgresql","postgres","sqlite","mssql","mariadb","oracle",
    "mongodb","redis","elasticsearch","cassandra","dynamodb","firebase","firestore",
    "snowflake","bigquery","redshift","databricks","neo4j","influxdb","room database",
    "prisma","sequelize","sqlalchemy","typeorm","mongoose",
    # Cloud / DevOps
    "aws","azure","gcp","google cloud","ec2","s3","lambda","docker","kubernetes",
    "helm","istio","terraform","pulumi","ansible","puppet","chef","vagrant",
    "jenkins","github actions","gitlab ci","circleci","argocd","prometheus",
    "grafana","datadog","splunk","elk stack","nginx","apache","linux","ubuntu",
    "devops","sre","ci/cd","gitops","devsecops","sonarqube","vault","consul",
    "kafka","rabbitmq","activemq","nats","cdn","vpc","iam",
    # Data / ML / AI
    "machine learning","deep learning","nlp","computer vision","generative ai",
    "llm","tensorflow","pytorch","keras","jax","scikit-learn","xgboost","lightgbm",
    "pandas","numpy","scipy","matplotlib","seaborn","plotly","spark","pyspark",
    "hadoop","hive","flink","airflow","prefect","dagster","dbt","tableau","power bi",
    "looker","data science","data analysis","data engineering","mlops","mlflow",
    "kubeflow","opencv","yolo","hugging face","langchain","openai","anthropic",
    "vector database","pinecone","rag","embeddings","fine-tuning","prompt engineering",
    "a/b testing","statistics","feature engineering",
    # Mobile
    "android","android sdk","android studio","jetpack compose","viewmodel",
    "livedata","room database","retrofit","okhttp","hilt","dagger","koin",
    "mvvm","mvp","mvi","coroutines","rxjava","rxandroid","workmanager",
    "navigation component","firebase","fcm","crashlytics","espresso","gradle",
    "ios","swift","swiftui","uikit","core data","combine","xcode","cocoapods",
    "spm","arkit","healthkit","xctest","fastlane",
    "react native","flutter","dart","expo","ionic",
    # Version Control / Tools
    "git","github","gitlab","bitbucket","jira","confluence","trello","asana",
    "notion","figma","sketch","zeplin","adobe xd","postman","swagger",
    # Testing
    "selenium","appium","cypress","playwright","puppeteer","espresso","xcuitest",
    "junit","testng","pytest","jest","mocha","chai","cucumber","jmeter","gatling",
    "k6","tdd","bdd","sonarqube",
    # Security
    "oauth","jwt","saml","sso","ldap","ssl","tls","encryption","cybersecurity",
    "penetration testing","owasp","devsecops","iam","rbac","zero trust",
    "siem","soar","burp suite","metasploit","kali linux","iso 27001","nist",
    # Architecture
    "microservices","event driven","cqrs","ddd","clean architecture","solid",
    "design patterns","api gateway","serverless","faas","domain driven design",
    # Blockchain
    "blockchain","web3","solidity","ethereum","smart contracts","nft","defi",
    "hardhat","foundry","ethers.js","web3.js","ipfs","chainlink",
    # Embedded / IoT
    "embedded systems","rtos","firmware","microcontroller","arduino","raspberry pi",
    "esp32","stm32","freertos","zephyr","device drivers","uart","spi","i2c",
    "mqtt","bluetooth","ble","lorawan","iot","verilog","vhdl","fpga","plc","scada",
    # Marketing
    "seo","sem","ppc","google ads","meta ads","facebook ads","google analytics",
    "ga4","hubspot","salesforce","marketo","mailchimp","klaviyo","ahrefs","semrush",
    "marketing automation","content marketing","email marketing","crm","growth hacking",
    "conversion rate optimization","influencer marketing","affiliate marketing",
    # Finance
    "financial modeling","financial analysis","accounting","excel","advanced excel",
    "power bi","tableau","erp","sap","oracle financials","tally","quickbooks",
    "financial reporting","budgeting","forecasting","valuation","dcf","ifrs","gaap",
    "investment analysis","risk management","derivatives","treasury","payroll",
    # HR
    "recruitment","talent acquisition","sourcing","onboarding","performance management",
    "hris","hrms","workday","bamboohr","darwinbox","linkedin recruiter","greenhouse",
    "hr analytics","people analytics","learning and development","compensation",
    "organizational development","change management","dei","labor law","compliance",
    # Sales
    "sales","business development","b2b sales","b2c sales","account management",
    "lead generation","crm","salesforce","hubspot","negotiation","solution selling",
    "consultative selling","revenue growth","upselling","cross selling","salesforce",
    "linkedin sales navigator","apollo","outreach", "pipeline management",
    # Operations
    "operations management","lean","six sigma","supply chain","logistics",
    "inventory management","procurement","erp","sap","project management","pmp",
    "scrum","agile","kanban","bpm","sop","quality management","iso 9001","kpi","sla",
    "rpa","uipath","automation anywhere","process improvement",
    # Content / Media
    "content writing","copywriting","content strategy","seo writing","blogging",
    "technical writing","social media","video editing","youtube","premiere pro",
    "davinci resolve","podcast","photography","wordpress","cms","canva",
    "brand voice","proofreading","translation","localization",
    # Graphic Design
    "graphic design","visual design","brand design","logo design","illustration",
    "typography","adobe photoshop","adobe illustrator","adobe indesign",
    "after effects","coreldraw","affinity designer","figma","sketch","canva",
    "motion graphics","animation","blender","cinema 4d","web design","ui design",
    # General
    "agile","scrum","kanban","waterfall","product management","excel",
    "powerpoint","communication","leadership","problem solving",
], key=len, reverse=True)

_seen: set[str] = set()
KNOWN_SKILLS = [s for s in KNOWN_SKILLS if s not in _seen and not _seen.add(s)]  # type: ignore[func-returns-value]


def _extract_skills_fast(text: str) -> list[str]:
    """Keyword-only skill extraction — runs in <1ms per job."""
    if not text:
        return []
    tl = text.lower()
    upper_set = {"sql","html","css","aws","gcp","api","php","nlp","seo","ci/cd",
                 "ios","npm","git","rest api","restful","mssql","devops","xml",
                 "sdk","iot","sap","erp","rpa","crm","kpi","sla","bpm","sop",
                 "tdd","bdd","pmp","okr","dei","ppc","sem","dcf","iam","rbac"}
    found: set[str] = set()
    for skill in KNOWN_SKILLS:
        if re.search(r'\b' + re.escape(skill) + r'\b', tl):
            found.add(skill.upper() if skill in upper_set else skill.title())
    return sorted(found)


# ════════════════════════════════════════════════════════════════════════════
# HELPERS
# ════════════════════════════════════════════════════════════════════════════

def _make_driver() -> uc.Chrome:
    opts = uc.ChromeOptions()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--window-size=1280,800")
    return uc.Chrome(options=opts, version_main=146)


def _safe_sleep(lo: float = 1.0, hi: float = 2.5) -> None:
    time.sleep(random.uniform(lo, hi))


def _score_job(
    job: dict[str, Any],
    user_profile: dict,
    resume_text: str,
) -> dict[str, Any]:
    """Score a single job against the user profile."""
    if not user_profile or not any(user_profile.values()):
        job["match_score"] = 0.0
        job["gap_severity"] = "N/A"
        job["missing_skills"] = {}
        return job

    try:
        from app.services.match_service import run_matching_pipeline  # local import to avoid circular
        text_blob = f"{job.get('title','')} {job.get('description','')[:1500]}"
        job_profile: dict[str, list] = {"technical": [], "tools": [], "soft": []}
        for sk in _extract_skills_fast(text_blob):
            job_profile["technical"].append(sk)

        result = run_matching_pipeline(
            user_profile=user_profile,
            job_profile=job_profile,
            resume_text=resume_text,
            job_text=text_blob,
        )
        job["match_score"] = round(result["final_match_score"], 1)
        job["gap_severity"] = result.get("gap_severity", "N/A")
        job["missing_skills"] = result.get("missing_skills", {})
    except Exception as exc:
        print(f"  ⚠️  Scoring error: {exc}")
        job["match_score"] = 0.0
        job["gap_severity"] = "N/A"
        job["missing_skills"] = {}
    return job


# ════════════════════════════════════════════════════════════════════════════
# SOURCE 1 — INTERNSHALA  (Selenium, blocking → runs in thread)
# ════════════════════════════════════════════════════════════════════════════

def _scrape_internshala(keyword: str, city: str) -> list[dict]:
    """
    Scrapes Internshala search results.
    Returns raw job dicts (no scoring yet).
    """
    jobs: list[dict] = []
    url = f"https://internshala.com/internships/keywords-{keyword.replace(' ', '-')}"
    driver = _make_driver()

    try:
        driver.get(url)
        _safe_sleep(3, 5)
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        _safe_sleep(1.5, 2.5)

        soup = BeautifulSoup(driver.page_source, "html.parser")
        cards = soup.find_all("div", class_=re.compile(r"individual_internship"))

        for card in cards[:20]:
            # Skip ads
            if card.find_parent("a", class_="marketing_ads_card"):
                continue

            title_el   = card.select_one("a.job-title-href") or card.select_one(".job-internship-name a")
            company_el = card.select_one("p.company-name")
            if not title_el or not company_el:
                continue

            stipend_el = card.select_one("span.stipend")
            duration   = "Not specified"
            items      = card.find_all("div", class_="row-1-item")
            if len(items) >= 3:
                duration = items[2].get_text(strip=True)

            status_el = (
                card.select_one(".status-info span") or
                card.select_one(".status-success span") or
                card.select_one(".status span") or
                card.select_one(".status-inactive span")
            )

            href      = title_el.get("href", "")
            detail_url = f"https://internshala.com{href}" if href.startswith("/") else href

            # Fast detail fetch — JSON-LD only (no Selenium for details)
            description = ""
            detail_skills: list[str] = []
            try:
                import requests as _req
                r = _req.get(detail_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=8)
                ds = BeautifulSoup(r.text, "html.parser")
                desc_el = ds.select_one("#internship_description, .internship_details")
                if desc_el:
                    description = desc_el.get_text(" ", strip=True)[:2000]
                jld = ds.find("script", type="application/ld+json")
                if jld:
                    import json as _json
                    jd = _json.loads(jld.string or "{}")
                    raw_sk = jd.get("skills", "")
                    if raw_sk:
                        detail_skills = [s.strip() for s in raw_sk.split(",") if s.strip()]
            except Exception:
                pass

            jobs.append({
                "source":      "Internshala",
                "title":       title_el.get_text(strip=True),
                "employer":    company_el.get_text(strip=True),
                "location":    city,
                "salary":      stipend_el.get_text(strip=True) if stipend_el else "N/A",
                "duration":    duration,
                "status":      status_el.get_text(strip=True) if status_el else "Active",
                "apply_link":  detail_url,
                "description": description,
                "skills":      detail_skills or _extract_skills_fast(description),
                "employment_type": "Internship",
                "posted_at":   "",
                "employer_logo": "",
            })

    except Exception as exc:
        print(f"  ❌ Internshala error: {exc}")
    finally:
        try:
            driver.quit()
        except Exception:
            pass

    print(f"  ✅ Internshala → {len(jobs)} jobs")
    return jobs


# ════════════════════════════════════════════════════════════════════════════
# SOURCE 2 — INDEED IN  (Selenium, blocking → runs in thread)
# ════════════════════════════════════════════════════════════════════════════

def _load_indeed_cookies(driver: uc.Chrome) -> bool:
    if not os.path.exists(INDEED_COOKIES_FILE):
        return False
    try:
        driver.get("https://in.indeed.com")
        time.sleep(2)
        for c in pickle.load(open(INDEED_COOKIES_FILE, "rb")):
            try:
                driver.add_cookie(c)
            except Exception:
                pass
        driver.refresh()
        time.sleep(2)
        return True
    except Exception:
        return False


def _scrape_indeed(keyword: str, city: str) -> list[dict]:
    """
    Scrapes Indeed IN.
    Collects job stubs from the results page, then visits each detail page.
    Uses saved cookies to bypass page-2+ login wall.
    """
    jobs: list[dict] = []
    base_url = (
        f"https://in.indeed.com/jobs"
        f"?q={keyword.replace(' ', '+')}"
        f"&l={city.replace(' ', '+')}"
    )
    driver = _make_driver()

    try:
        # Load session cookies if available
        _load_indeed_cookies(driver)

        driver.get(base_url)
        _safe_sleep(4, 6)

        soup  = BeautifulSoup(driver.page_source, "html.parser")
        cards = soup.select("div.job_seen_beacon")

        stubs: list[dict] = []
        seen_jk: set[str] = set()

        for card in cards[:15]:
            tl = card.select_one("h2.jobTitle a")
            if not tl:
                continue
            jk = tl.get("data-jk", "")
            if not jk or jk in seen_jk:
                continue
            seen_jk.add(jk)

            title_sp  = card.select_one("h2.jobTitle a span")
            title_txt = title_sp.get_text(strip=True) if title_sp else tl.get_text(strip=True)

            comp_el = card.select_one('span[data-testid="company-name"]')
            loc_el  = card.select_one('div[data-testid="text-location"]')
            sal_el  = card.select_one("li.salary-snippet-container span.css-zydy3i")

            all_snip = [s.get_text(strip=True) for s in card.select("span.css-zydy3i")]
            salary   = sal_el.get_text(strip=True) if sal_el else "Not disclosed"
            others   = [m for m in all_snip if m != salary]

            resp_divs = card.select("div.mosaic-provider-jobcards-1f1q1js")
            resp_texts = [d.get_text(strip=True) for d in resp_divs if d.get_text(strip=True) not in all_snip]

            stubs.append({
                "jk":       jk,
                "title":    title_txt,
                "employer": comp_el.get_text(strip=True) if comp_el else "N/A",
                "location": loc_el.get_text(strip=True)  if loc_el  else city,
                "salary":   salary,
                "job_type": others[0] if others else "N/A",
                "status":   resp_texts[0] if resp_texts else "Standard",
            })

        # Visit each job detail page directly (no driver.back())
        for stub in stubs:
            job_url = f"https://in.indeed.com/viewjob?jk={stub['jk']}"
            description = ""
            try:
                driver.get(job_url)
                WebDriverWait(driver, 8).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "#jobDescriptionText"))
                )
                _safe_sleep(0.8, 1.5)
                pane = driver.find_element(By.CSS_SELECTOR, "#jobDescriptionText")
                desc_html = pane.get_attribute("innerHTML")
                description = BeautifulSoup(desc_html, "html.parser").get_text(" ", strip=True)[:2000]
            except Exception:
                pass

            _safe_sleep(1.5, 3.0)

            jobs.append({
                "source":      "Indeed",
                "title":       stub["title"],
                "employer":    stub["employer"],
                "location":    stub["location"],
                "salary":      stub["salary"],
                "duration":    "N/A",
                "status":      stub["status"],
                "apply_link":  f"https://in.indeed.com/viewjob?jk={stub['jk']}",
                "description": description,
                "skills":      _extract_skills_fast(description),
                "employment_type": stub["job_type"],
                "posted_at":   "",
                "employer_logo": "",
            })

    except Exception as exc:
        print(f"  ❌ Indeed error: {exc}")
    finally:
        try:
            driver.quit()
        except Exception:
            pass

    print(f"  ✅ Indeed → {len(jobs)} jobs")
    return jobs


# ════════════════════════════════════════════════════════════════════════════
# SOURCE 3 — JSEARCH API  (async httpx, non-blocking)
# ════════════════════════════════════════════════════════════════════════════

async def _scrape_jsearch(keyword: str, city: str) -> list[dict]:
    """Calls JSearch RapidAPI — pure async, no Selenium."""
    if not JSEARCH_API_KEY:
        print("  ⚠️  JSEARCH_API_KEY not set — skipping JSearch")
        return []

    jobs: list[dict] = []
    queries = [
        f"{keyword} internship in {city}",
        f"{keyword} fresher jobs in {city}",
    ]
    seen_links: set[str] = set()

    async with httpx.AsyncClient(timeout=15) as client:
        tasks = [
            client.get(
                "https://jsearch.p.rapidapi.com/search",
                params={"query": q, "page": "1", "num_pages": "3", "date_posted": "month"},
                headers={
                    "x-rapidapi-key":  JSEARCH_API_KEY,
                    "x-rapidapi-host": "jsearch.p.rapidapi.com",
                },
            )
            for q in queries
        ]
        responses = await asyncio.gather(*tasks, return_exceptions=True)

    for resp in responses:
        if isinstance(resp, Exception):
            print(f"  ❌ JSearch error: {resp}")
            continue
        if resp.status_code != 200:
            continue

        for job in resp.json().get("data", []):
            link = job.get("job_apply_link", "")
            if not link or link in seen_links:
                continue
            seen_links.add(link)

            qualifs = job.get("job_highlights", {}).get("Qualifications") or []
            desc    = job.get("job_description", "") or ""
            text_blob = f"{job.get('job_title','')} {' '.join(str(q) for q in qualifs[:5])} {desc[:1500]}"

            jobs.append({
                "source":        "JSearch",
                "title":         job.get("job_title", ""),
                "employer":      job.get("employer_name", ""),
                "location":      job.get("job_city") or city,
                "salary":        _format_jsearch_salary(job),
                "duration":      "N/A",
                "status":        "Active",
                "apply_link":    link,
                "description":   desc[:2000],
                "skills":        _extract_skills_fast(text_blob),
                "employment_type": job.get("job_employment_type", ""),
                "posted_at":     job.get("job_posted_at_datetime_utc", ""),
                "employer_logo": job.get("employer_logo", ""),
            })

            if len(jobs) >= 20:
                break

    print(f"  ✅ JSearch → {len(jobs)} jobs")
    return jobs


def _format_jsearch_salary(job: dict) -> str:
    lo = job.get("job_min_salary")
    hi = job.get("job_max_salary")
    if lo and hi:
        return f"₹{int(lo):,} – ₹{int(hi):,}"
    if lo:
        return f"₹{int(lo):,}+"
    return "Not disclosed"


# ════════════════════════════════════════════════════════════════════════════
# CSV CACHE
# ════════════════════════════════════════════════════════════════════════════

_CSV_FIELDS = [
    "source","title","employer","location","salary","duration","status",
    "employment_type","skills","match_score","gap_severity","apply_link","posted_at",
]


def _save_to_csv(jobs: list[dict], domain: str, city: str) -> Path:
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = re.sub(r"[^a-z0-9_]", "_", f"{domain or 'all'}_{city}".lower())
    path = CACHE_DIR / f"{slug}_{ts}.csv"

    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=_CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for job in jobs:
            row = dict(job)
            if isinstance(row.get("skills"), list):
                row["skills"] = ", ".join(row["skills"])
            if isinstance(row.get("missing_skills"), dict):
                row.pop("missing_skills", None)
            writer.writerow(row)

    print(f"  💾 Saved {len(jobs)} jobs → {path.name}")
    return path


# ════════════════════════════════════════════════════════════════════════════
# PUBLIC ENTRY POINT
# ════════════════════════════════════════════════════════════════════════════

async def aggregate_jobs(
    domain: str,
    city: str,
    user_profile: dict | None = None,
    resume_text: str = "",
    sources: list[str] | None = None,
) -> dict[str, Any]:
    """
    Run all scrapers in parallel, score, deduplicate, sort, cache to CSV.

    Parameters
    ----------
    domain       : domain key e.g. "android", "backend" (see DOMAIN_KEYWORDS)
    city         : city name e.g. "Mumbai"
    user_profile : {"technical": [...], "tools": [...], "soft": [...]}
    resume_text  : raw resume text for semantic scoring
    sources      : which sources to use; default ["internshala","indeed","jsearch"]

    Returns
    -------
    {
        "jobs":       [...],   # sorted by match_score desc
        "total":      int,
        "csv_path":   str,
        "sources_hit": {...},  # count per source
    }
    """
    if sources is None:
        sources = ["internshala", "indeed", "jsearch"]

    keyword = DOMAIN_KEYWORDS.get(domain.lower(), domain) or domain

    print(f"\n🚀 Aggregating jobs | domain={domain!r} keyword={keyword!r} city={city!r}")
    print(f"   Sources: {sources}")

    loop = asyncio.get_event_loop()

    # ── Launch Selenium scrapers in thread-pool + JSearch async ──────────────
    futures: dict[str, Any] = {}

    if "internshala" in sources:
        futures["internshala"] = loop.run_in_executor(
            _EXECUTOR, _scrape_internshala, keyword, city
        )
    if "indeed" in sources:
        futures["indeed"] = loop.run_in_executor(
            _EXECUTOR, _scrape_indeed, keyword, city
        )

    # Start JSearch async immediately
    jsearch_task = None
    if "jsearch" in sources:
        jsearch_task = asyncio.create_task(_scrape_jsearch(keyword, city))

    # ── Gather all results ────────────────────────────────────────────────────
    raw_jobs: list[dict] = []
    sources_hit: dict[str, int] = {}

    if futures:
        done = await asyncio.gather(*futures.values(), return_exceptions=True)
        for src, result in zip(futures.keys(), done):
            if isinstance(result, Exception):
                print(f"  ❌ {src} failed: {result}")
                sources_hit[src] = 0
            else:
                sources_hit[src] = len(result)
                raw_jobs.extend(result)

    if jsearch_task:
        try:
            jsearch_results = await jsearch_task
            sources_hit["jsearch"] = len(jsearch_results)
            raw_jobs.extend(jsearch_results)
        except Exception as exc:
            print(f"  ❌ JSearch task failed: {exc}")
            sources_hit["jsearch"] = 0

    print(f"\n  📦 Total raw jobs: {len(raw_jobs)} | {sources_hit}")

    # ── Deduplication by apply_link ────────────────────────────────────────────
    seen_links: set[str] = set()
    unique_jobs: list[dict] = []
    for job in raw_jobs:
        link = job.get("apply_link", "")
        if link and link not in seen_links:
            seen_links.add(link)
            unique_jobs.append(job)
        elif not link:
            unique_jobs.append(job)  # keep if no link (avoid losing data)

    print(f"  🔗 After dedup: {len(unique_jobs)} jobs")

    # ── Score all jobs in thread pool (CPU-bound) ─────────────────────────────
    _up = user_profile or {}
    _rt = resume_text or ""

    if any(_up.values()) if _up else False:
        score_tasks = [
            loop.run_in_executor(_EXECUTOR, _score_job, job, _up, _rt)
            for job in unique_jobs
        ]
        scored_jobs: list[dict] = list(await asyncio.gather(*score_tasks))
    else:
        # No profile — just assign 0
        for job in unique_jobs:
            job["match_score"]  = 0.0
            job["gap_severity"] = "N/A"
            job["missing_skills"] = {}
        scored_jobs = unique_jobs

    # ── Sort by match_score descending ────────────────────────────────────────
    scored_jobs.sort(key=lambda j: j.get("match_score", 0), reverse=True)

    # ── Save to CSV ────────────────────────────────────────────────────────────
    csv_path = await loop.run_in_executor(
        _EXECUTOR, _save_to_csv, scored_jobs, domain, city
    )

    print(f"  🏆 Top job: {scored_jobs[0]['title'] if scored_jobs else 'N/A'}")

    return {
        "jobs":        scored_jobs,
        "total":       len(scored_jobs),
        "csv_path":    str(csv_path),
        "sources_hit": sources_hit,
    }
