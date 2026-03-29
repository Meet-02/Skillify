"""
app/services/job_scraper_service.py
────────────────────────────────────────────────────────────────────────────────
Unified job aggregator:
  • Internshala  — via internshala_scraper.scrape_internshala_fast
  • Indeed IN    — via indeed_scraper.scrape_indeed_fast
  • JSearch API  — httpx async call  (jobs via RapidAPI)

75% of results come from scrapers, 25% from JSearch API.
All three run CONCURRENTLY via asyncio + ThreadPoolExecutor.
Results are:
  1. Scored + ranked with run_matching_pipeline
  2. Saved to CSV  (tmp/jobs_cache/<domain>_<city>_<timestamp>.csv)
  3. CSV deleted after data is captured
  4. Returned sorted by match_score descending
────────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import asyncio
import csv
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

load_dotenv()

JSEARCH_API_KEY: str = os.getenv("JSEARCH_API_KEY", "")

# ── CSV cache directory ──────────────────────────────────────────────────────
_ROOT = Path(__file__).resolve().parent.parent.parent
CACHE_DIR = _ROOT / "tmp" / "jobs_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# ── Thread-pool shared by Selenium scrapers ──────────────────────────────────
_EXECUTOR = ThreadPoolExecutor(max_workers=4)

# ════════════════════════════════════════════════════════════════════════════
# DOMAIN → KEYWORD MAP
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
    "python","java","javascript","typescript","c++","c#","c","ruby","go","golang",
    "php","swift","kotlin","scala","rust","perl","r","dart","objective-c","bash",
    "shell","powershell","groovy","lua","haskell","elixir","erlang","vba","matlab",
    "react","angular","vue","html","css","sass","scss","bootstrap","jquery",
    "next.js","nuxt.js","gatsby","remix","astro","svelte","sveltekit","webpack",
    "vite","redux","zustand","tailwind","tailwindcss","material ui","graphql",
    "three.js","d3.js","pwa","webgl","webassembly","rxjs","storybook",
    "node.js","nodejs","express","expressjs","nestjs","fastify","django","flask",
    "fastapi","spring","spring boot","spring mvc","hibernate","rails","laravel",
    "symfony","asp.net",".net",".net core","gin","fiber","phoenix","grpc",
    "microservices","rest api","restful","soap","websocket","oauth","jwt","swagger",
    "sql","mysql","postgresql","postgres","sqlite","mssql","mariadb","oracle",
    "mongodb","redis","elasticsearch","cassandra","dynamodb","firebase","firestore",
    "snowflake","bigquery","redshift","databricks","neo4j","influxdb","room database",
    "prisma","sequelize","sqlalchemy","typeorm","mongoose",
    "aws","azure","gcp","google cloud","ec2","s3","lambda","docker","kubernetes",
    "helm","istio","terraform","pulumi","ansible","puppet","chef","vagrant",
    "jenkins","github actions","gitlab ci","circleci","argocd","prometheus",
    "grafana","datadog","splunk","elk stack","nginx","apache","linux","ubuntu",
    "devops","sre","ci/cd","gitops","devsecops","sonarqube","vault","consul",
    "kafka","rabbitmq","activemq","nats","cdn","vpc","iam",
    "machine learning","deep learning","nlp","computer vision","generative ai",
    "llm","tensorflow","pytorch","keras","jax","scikit-learn","xgboost","lightgbm",
    "pandas","numpy","scipy","matplotlib","seaborn","plotly","spark","pyspark",
    "hadoop","hive","flink","airflow","prefect","dagster","dbt","tableau","power bi",
    "looker","data science","data analysis","data engineering","mlops","mlflow",
    "kubeflow","opencv","yolo","hugging face","langchain","openai","anthropic",
    "vector database","pinecone","rag","embeddings","fine-tuning","prompt engineering",
    "a/b testing","statistics","feature engineering",
    "android","android sdk","android studio","jetpack compose","viewmodel",
    "livedata","room database","retrofit","okhttp","hilt","dagger","koin",
    "mvvm","mvp","mvi","coroutines","rxjava","rxandroid","workmanager",
    "navigation component","firebase","fcm","crashlytics","espresso","gradle",
    "ios","swift","swiftui","uikit","core data","combine","xcode","cocoapods",
    "spm","arkit","healthkit","xctest","fastlane",
    "react native","flutter","dart","expo","ionic",
    "git","github","gitlab","bitbucket","jira","confluence","trello","asana",
    "notion","figma","sketch","zeplin","adobe xd","postman","swagger",
    "selenium","appium","cypress","playwright","puppeteer","espresso","xcuitest",
    "junit","testng","pytest","jest","mocha","chai","cucumber","jmeter","gatling",
    "k6","tdd","bdd","sonarqube",
    "oauth","jwt","saml","sso","ldap","ssl","tls","encryption","cybersecurity",
    "penetration testing","owasp","devsecops","iam","rbac","zero trust",
    "siem","soar","burp suite","metasploit","kali linux","iso 27001","nist",
    "microservices","event driven","cqrs","ddd","clean architecture","solid",
    "design patterns","api gateway","serverless","faas","domain driven design",
    "blockchain","web3","solidity","ethereum","smart contracts","nft","defi",
    "hardhat","foundry","ethers.js","web3.js","ipfs","chainlink",
    "embedded systems","rtos","firmware","microcontroller","arduino","raspberry pi",
    "esp32","stm32","freertos","zephyr","device drivers","uart","spi","i2c",
    "mqtt","bluetooth","ble","lorawan","iot","verilog","vhdl","fpga","plc","scada",
    "seo","sem","ppc","google ads","meta ads","facebook ads","google analytics",
    "ga4","hubspot","salesforce","marketo","mailchimp","klaviyo","ahrefs","semrush",
    "marketing automation","content marketing","email marketing","crm","growth hacking",
    "conversion rate optimization","influencer marketing","affiliate marketing",
    "financial modeling","financial analysis","accounting","excel","advanced excel",
    "power bi","tableau","erp","sap","oracle financials","tally","quickbooks",
    "financial reporting","budgeting","forecasting","valuation","dcf","ifrs","gaap",
    "investment analysis","risk management","derivatives","treasury","payroll",
    "recruitment","talent acquisition","sourcing","onboarding","performance management",
    "hris","hrms","workday","bamboohr","darwinbox","linkedin recruiter","greenhouse",
    "hr analytics","people analytics","learning and development","compensation",
    "organizational development","change management","dei","labor law","compliance",
    "sales","business development","b2b sales","b2c sales","account management",
    "lead generation","crm","salesforce","hubspot","negotiation","solution selling",
    "consultative selling","revenue growth","upselling","cross selling","salesforce",
    "linkedin sales navigator","apollo","outreach", "pipeline management",
    "operations management","lean","six sigma","supply chain","logistics",
    "inventory management","procurement","erp","sap","project management","pmp",
    "scrum","agile","kanban","bpm","sop","quality management","iso 9001","kpi","sla",
    "rpa","uipath","automation anywhere","process improvement",
    "content writing","copywriting","content strategy","seo writing","blogging",
    "technical writing","social media","video editing","youtube","premiere pro",
    "davinci resolve","podcast","photography","wordpress","cms","canva",
    "brand voice","proofreading","translation","localization",
    "graphic design","visual design","brand design","logo design","illustration",
    "typography","adobe photoshop","adobe illustrator","adobe indesign",
    "after effects","coreldraw","affinity designer","figma","sketch","canva",
    "motion graphics","animation","blender","cinema 4d","web design","ui design",
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
# SCORING HELPER
# ════════════════════════════════════════════════════════════════════════════

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
        from app.services.match_service import run_matching_pipeline
        text_blob = f"{job.get('title','')} {job.get('description','')[:1500]}"

        # Build job_profile from skills list or from text extraction
        job_profile: dict[str, list] = {"technical": [], "tools": [], "soft": []}
        skills = job.get("skills", [])
        if skills:
            job_profile["technical"] = list(skills)
        else:
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
# SOURCE 3 — JSEARCH API  (async httpx, non-blocking)
# ════════════════════════════════════════════════════════════════════════════

async def _scrape_jsearch(keyword: str, city: str, date_filter: str = "month") -> list[dict]:
    """Calls JSearch RapidAPI — pure async, no Selenium."""
    if not JSEARCH_API_KEY:
        print("  ⚠️  JSEARCH_API_KEY not set — skipping JSearch")
        return []

    # Map date_filter to JSearch's date_posted param
    jsearch_date_map = {
        "24h": "today", "last 24h": "today", "today": "today",
        "3days": "3days", "last 3 days": "3days",
        "week": "week", "last week": "week",
        "month": "month", "last month": "month",
    }
    date_posted = jsearch_date_map.get(date_filter.lower().strip(), "month")

    jobs: list[dict] = []
    queries = [
        f"{keyword} internship in {city}",
        f"{keyword} fresher jobs in {city}",
    ]
    seen_links: set[str] = set()

    _headers = {
        "x-rapidapi-key":  JSEARCH_API_KEY,
        "x-rapidapi-host": "jsearch.p.rapidapi.com",
    }

    async with httpx.AsyncClient(timeout=15) as client:
        tasks = [
            client.get(
                "https://jsearch.p.rapidapi.com/search",
                params={"query": q, "page": "1", "num_pages": "3", "date_posted": date_posted},
                headers=_headers,
            )
            for q in queries
        ]
        responses = await asyncio.gather(*tasks, return_exceptions=True)

    # If RapidAPI rate-limits this request, skip JSearch immediately.
    # This prevents API retries/logging overhead from slowing overall aggregation.
    if any(
        not isinstance(resp, Exception) and getattr(resp, "status_code", None) == 429
        for resp in responses
    ):
        print("  ⚠️  JSearch returned HTTP 429 (rate-limited) — skipping JSearch for this run")
        return []

    for i, resp in enumerate(responses):
        query_used = queries[i] if i < len(queries) else "?"

        if isinstance(resp, Exception):
            print(f"  ❌ JSearch error for query={query_used!r}: {resp}")
            continue

        data_list = resp.json().get("data", [])
        print(f"  📡 JSearch query={query_used!r} | status={resp.status_code} "
              f"| date_posted={date_posted!r} | results={len(data_list)}")

        if resp.status_code != 200:
            print(f"  ⚠️  JSearch non-200! URL={resp.url}")
            print(f"       Headers sent: host={_headers['x-rapidapi-host']} key=...{JSEARCH_API_KEY[-6:]}")
            print(f"       Response body: {resp.text[:300]}")
            continue

        if len(data_list) == 0:
            print(f"  ⚠️  JSearch returned 0 jobs for this query!")
            print(f"       Full URL: {resp.url}")
            print(f"       API key (last 6): ...{JSEARCH_API_KEY[-6:]}")

        for job in data_list:
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

    print(f"  ✅ JSearch → {len(jobs)} jobs total")
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
    date_filter: str = "month",
) -> dict[str, Any]:
    """
    Run all scrapers in parallel, score, deduplicate, sort, cache to CSV.

    75% of jobs come from scrapers (Internshala + Indeed).
    25% come from JSearch API.
    If scrapers fail, 100% falls back to JSearch.

    Parameters
    ----------
    domain       : domain key e.g. "android", "backend" (see DOMAIN_KEYWORDS)
    city         : city name e.g. "Mumbai"
    user_profile : {"technical": [...], "tools": [...], "soft": [...]}
    resume_text  : raw resume text for semantic scoring
    sources      : which sources to use; default ["internshala","indeed","jsearch"]
    date_filter  : "3days", "week", "month" etc.

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

    # Fix case sensitivity: always normalise before lookup
    domain_clean = domain.lower().strip()
    keyword = DOMAIN_KEYWORDS.get(domain_clean)
    if keyword is None:
        # Fallback: use a Title Case version of the raw domain
        keyword = domain.strip().title() if domain.strip() else ""
    keyword = keyword or domain_clean   # ultimate fallback

    print(f"\n🚀 Aggregating jobs | domain={domain!r} keyword={keyword!r} city={city!r}")
    print(f"   Sources: {sources}  date_filter={date_filter!r}")

    import time as _t
    _start = _t.time()

    loop = asyncio.get_event_loop()

    # ── Launch scrapers in thread-pool + JSearch async ─────────────────────
    futures: dict[str, Any] = {}

    if "internshala" in sources:
        from app.services.internshala_scraper import scrape_internshala_fast
        print(f"  ▶️  Launching Internshala scraper in thread pool...")
        futures["internshala"] = loop.run_in_executor(
            _EXECUTOR, scrape_internshala_fast, keyword, city, date_filter
        )

    if "indeed" in sources:
        from app.services.indeed_scraper import scrape_indeed_fast
        print(f"  ▶️  Launching Indeed scraper in thread pool...")
        futures["indeed"] = loop.run_in_executor(
            _EXECUTOR, scrape_indeed_fast, keyword, city, date_filter
        )

    # Start JSearch async immediately
    jsearch_task = None
    if "jsearch" in sources:
        print(f"  ▶️  Launching JSearch API (async)...")
        jsearch_task = asyncio.create_task(_scrape_jsearch(keyword, city, date_filter))

    # ── Gather all results ────────────────────────────────────────────────
    print(f"\n  ⏳ Waiting for all sources to complete...")
    scraper_jobs: list[dict] = []
    jsearch_jobs: list[dict] = []
    sources_hit: dict[str, int] = {}

    if futures:
        done = await asyncio.gather(*futures.values(), return_exceptions=True)
        for src, result in zip(futures.keys(), done):
            if isinstance(result, Exception):
                print(f"  ❌ {src} FAILED: {result}")
                sources_hit[src] = 0
            else:
                print(f"  ✅ {src} returned {len(result)} jobs")
                sources_hit[src] = len(result)
                scraper_jobs.extend(result)

    if jsearch_task:
        try:
            jsearch_results = await jsearch_task
            print(f"  ✅ jsearch returned {len(jsearch_results)} jobs")
            sources_hit["jsearch"] = len(jsearch_results)
            jsearch_jobs.extend(jsearch_results)
        except Exception as exc:
            print(f"  ❌ JSearch task FAILED: {exc}")
            sources_hit["jsearch"] = 0

    _gather_elapsed = _t.time() - _start
    print(f"  ⏱️  All sources gathered in {_gather_elapsed:.1f}s")

    # ── Apply 75/25 split ─────────────────────────────────────────────────
    # 75% from scrapers, 25% from JSearch
    # If scrapers return 0, use all JSearch results (fallback)
    total_target = len(scraper_jobs) + len(jsearch_jobs)
    if scraper_jobs:
        scraper_cap = max(1, int(total_target * 0.75))
        jsearch_cap = max(1, total_target - scraper_cap)
        combined = scraper_jobs[:scraper_cap] + jsearch_jobs[:jsearch_cap]
        print(f"  📦 75/25 split: scrapers capped={scraper_cap} jsearch capped={jsearch_cap}")
    else:
        # Fallback: all JSearch
        combined = jsearch_jobs
        print(f"  ⚠️  No scraper jobs — falling back to 100% JSearch ({len(jsearch_jobs)} jobs)")

    print(f"\n  📦 Total raw: scrapers={len(scraper_jobs)} jsearch={len(jsearch_jobs)}")
    print(f"  📦 After 75/25 split: {len(combined)} jobs | {sources_hit}")

    # ── Deduplication by apply_link ────────────────────────────────────────
    seen_links: set[str] = set()
    unique_jobs: list[dict] = []
    for job in combined:
        link = job.get("apply_link", "")
        if link and link not in seen_links:
            seen_links.add(link)
            unique_jobs.append(job)
        elif not link:
            unique_jobs.append(job)

    print(f"  🔗 After dedup: {len(unique_jobs)} jobs")

    # ── Score all jobs in thread pool (CPU-bound) ─────────────────────────
    _up = user_profile or {}
    _rt = resume_text or ""

    if any(_up.values()) if _up else False:
        print(f"  🎯 Scoring {len(unique_jobs)} jobs against user profile...")
        _score_start = _t.time()
        score_tasks = [
            loop.run_in_executor(_EXECUTOR, _score_job, job, _up, _rt)
            for job in unique_jobs
        ]
        scored_jobs: list[dict] = list(await asyncio.gather(*score_tasks))
        print(f"  🎯 Scoring done in {_t.time() - _score_start:.1f}s")
    else:
        print(f"  ⚠️  No user profile — assigning match_score=0 to all jobs")
        for job in unique_jobs:
            job["match_score"]  = 0.0
            job["gap_severity"] = "N/A"
            job["missing_skills"] = {}
        scored_jobs = unique_jobs

    # ── Sort by match_score descending ────────────────────────────────────
    scored_jobs.sort(key=lambda j: j.get("match_score", 0), reverse=True)

    # ── Save to CSV ──────────────────────────────────────────────────────
    csv_path = await loop.run_in_executor(
        _EXECUTOR, _save_to_csv, scored_jobs, domain, city
    )

    print(f"  🏆 Top job: {scored_jobs[0]['title'] if scored_jobs else 'N/A'}")

    result = {
        "jobs":        scored_jobs,
        "total":       len(scored_jobs),
        "csv_path":    str(csv_path),
        "sources_hit": sources_hit,
    }

    # ── Cleanup: delete temporary CSV immediately ─────────────────────────
    try:
        os.remove(csv_path)
        print(f"  🗑️  Deleted temp CSV: {csv_path.name}")
    except OSError as exc:
        print(f"  ⚠️  Could not delete CSV: {exc}")

    # ── Final Alignment for Frontend ──
    for job in scored_jobs:
        # Frontend expects an array for skills/qualifications; never leave strings like "Not listed".
        skills_raw = job.get("skills", [])
        if isinstance(skills_raw, list):
            skills_list = [str(s).strip() for s in skills_raw if str(s).strip()]
        elif isinstance(skills_raw, str):
            parts = [s.strip() for s in skills_raw.split(",") if s.strip()]
            skills_list = [s for s in parts if s.lower() != "not listed"]
        else:
            skills_list = []
        job["skills"] = skills_list

        # Frontend script.js looks for 'qualifications' to render the small tags
        if not job.get("qualifications"):
            job["qualifications"] = skills_list[:4]
            
        # Ensure match_score exists for the SVG ring
        if "match_score" not in job:
            job["match_score"] = 0

    result = {
        "jobs":        scored_jobs,
        "total":       len(scored_jobs),
        "csv_path":    str(csv_path),
        "sources_hit": sources_hit,
        "city":        city
    }

    return result
