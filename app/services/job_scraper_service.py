"""
app/services/job_scraper_service.py
────────────────────────────────────────────────────────────────────────────────
Unified job aggregator:
  • Internshala  — via internshala_scraper.scrape_internshala_fast
  • Indeed IN    — via indeed_scraper.scrape_indeed_fast
  • JSearch API  — httpx async call  (jobs via RapidAPI)
  • TiDB Database — Pulls background-scraped jobs in Production

75% of results come from scrapers/DB, 25% from JSearch API.
All run CONCURRENTLY via asyncio + ThreadPoolExecutor.
────────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import asyncio
import csv
import os
import re
import time
import json
import pymysql
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

load_dotenv()

JSEARCH_API_KEY: str = os.getenv("JSEARCH_API_KEY", "")

# ── CSV cache directory ──────────────────────────────────────────────────────
_SERVICE_DIR = Path(__file__).resolve().parent
_ROOT = _SERVICE_DIR.parent.parent
CACHE_DIR = _ROOT / "tmp" / "jobs_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
SKILLS_JSON_PATH = _ROOT / "app" / "data" / "skills_master_indeed.json"

# ── Thread-pool shared by Selenium scrapers & DB queries ─────────────────────
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
    "blockchain": "Blockchain",
    "marketing":  "Marketing",
    "finance":    "Finance",
    "hr":         "Human Resources",
    "sales":      "Sales",
    "operations": "Operations",
    "content":    "Content Writer",
    "design":     "Graphic Designer",
}

def _score_job_wrapper(args):
    """Helper for multiprocessing to unpack arguments."""
    job, user_profile, resume_text = args
    return _score_job(job, user_profile, resume_text)

def load_skills_from_json():
    """Loads names and synonyms from JSON into a flat, sorted list."""
    try:
        if not SKILLS_JSON_PATH.exists():
            print(f"⚠️ Skills JSON not found at {SKILLS_JSON_PATH}")
            return []
            
        with open(SKILLS_JSON_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        flat_skills = set()
        for item in data:
            flat_skills.add(item["name"].lower())
            if "synonyms" in item:
                for syn in item["synonyms"]:
                    flat_skills.add(syn.lower())
        
        return sorted(list(flat_skills), key=len, reverse=True)
    except Exception as e:
        print(f"⚠️ Error loading skills JSON: {e}")
        return []

KNOWN_SKILLS = load_skills_from_json() 

def _extract_skills_fast(text: str) -> list[str]:
    """Resilient keyword skill extraction using Regex Lookarounds."""
    if not text: 
        return []
    
    tl = text.lower()
    found = set()
    
    for skill in KNOWN_SKILLS:
        skill_clean = skill.lower()
        pattern = r'(?<![a-zA-Z0-9])' + re.escape(skill_clean) + r'(?![a-zA-Z0-9])'
        
        if re.search(pattern, tl):
            if len(skill_clean) <= 3:
                found.add(skill_clean.upper())
            else:
                special_cases = {"mern", "mean", "rest", "node.js", "mongodb"}
                if skill_clean in special_cases:
                    mapping = {"node.js": "Node.js", "mongodb": "MongoDB"}
                    found.add(mapping.get(skill_clean, skill_clean.upper()))
                else:
                    found.add(skill_clean.title())
                
    return sorted(list(found))


# ════════════════════════════════════════════════════════════════════════════
# SOURCE: TIDB DATABASE (Replaces Selenium in Production)
# ════════════════════════════════════════════════════════════════════════════

# ════════════════════════════════════════════════════════════════════════════
# SOURCE: TIDB DATABASE (Replaces Selenium in Production)
# ════════════════════════════════════════════════════════════════════════════

def _fetch_jobs_from_db(domain: str, city: str) -> list[dict]:
    """Fetch jobs previously scraped by GitHub Actions from TiDB using strict domain tags."""
    try:
        connection = pymysql.connect(
            host=os.getenv('TIDB_HOST'),
            user=os.getenv('TIDB_USER'),
            password=os.getenv('TIDB_PASS'),
            database=os.getenv('TIDB_NAME'),
            port=4000,
            ssl={'ssl_mode': 'PREFERRED'},
            cursorclass=pymysql.cursors.DictCursor
        )
        
        with connection.cursor() as cursor:
            # 1. THE BULLETPROOF DOMAIN SEARCH
            # No more wildcards! No more guessing titles! 
            sql = """
            SELECT source, title, company as employer, location, link as apply_link, skills, domain
            FROM jobs 
            WHERE domain = %s
              AND (LOWER(location) LIKE %s OR LOWER(location) LIKE '%%work from home%%' OR LOWER(location) LIKE '%%remote%%')
            ORDER BY id DESC
            LIMIT 150
            """
            
            # Pass ONLY the exact domain tag and the city
            cursor.execute(sql, (domain, f"%{city.lower()}%"))
            rows = cursor.fetchall()
            
            db_jobs = []
            for row in rows:
                skills_str = row.get('skills', '')
                skills_list = [s.strip() for s in skills_str.split(',') if s.strip()] if skills_str else []
                
                db_jobs.append({
                    "source": row.get('source', 'Database'),
                    "title": row.get('title', ''),
                    "employer": row.get('employer', ''),
                    "location": row.get('location', ''),
                    "salary": "Not disclosed",
                    "duration": "N/A",
                    "status": "Active",
                    "apply_link": row.get('apply_link', ''),
                    "description": "",
                    "skills": skills_list,
                    "employment_type": "Full Time",
                    "posted_at": datetime.now(timezone.utc).isoformat(),
                    "employer_logo": "",
                })
        
        connection.close()
        print(f"  🗄️ TiDB Database → Found {len(db_jobs)} saved jobs.")
        return db_jobs
    except Exception as e:
        print(f"  ⚠️ Database fetch error: {e}")
        return []


# ════════════════════════════════════════════════════════════════════════════
# SCORING HELPER
# ════════════════════════════════════════════════════════════════════════════

def _score_job(
    job: dict[str, Any],
    user_profile: dict,
    resume_text: str,
) -> dict[str, Any]:
    if not user_profile or not any(user_profile.values()):
        job["match_score"] = 0.0
        job["gap_severity"] = "N/A"
        job["missing_skills"] = {}
        return job

    try:
        from app.services.match_service import run_matching_pipeline
        text_blob = f"{job.get('title','')} {job.get('description','')[:1500]}"

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
# SOURCE: JSEARCH API
# ════════════════════════════════════════════════════════════════════════════

async def _scrape_jsearch(keyword: str, city: str, date_filter: str = "month") -> list[dict]:
    if not JSEARCH_API_KEY:
        print("  ⚠️  JSEARCH_API_KEY not set — skipping JSearch")
        return []

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

    if any(not isinstance(resp, Exception) and getattr(resp, "status_code", None) == 429 for resp in responses):
        print("  ⚠️  JSearch returned HTTP 429 (rate-limited) — skipping JSearch for this run")
        return []

    for i, resp in enumerate(responses):
        query_used = queries[i] if i < len(queries) else "?"
        if isinstance(resp, Exception) or resp.status_code != 200: continue

        data_list = resp.json().get("data", [])
        
        for job in data_list:
            link = job.get("job_apply_link", "")
            if not link or link in seen_links: continue
            seen_links.add(link)

            qualifs = job.get("job_highlights", {}).get("Qualifications") or []
            desc    = job.get("job_description", "") or ""
            text_blob = f"{job.get('job_title','')} {' '.join(str(q) for q in qualifs[:5])} {desc[:1500]}"

            lo = job.get("job_min_salary")
            hi = job.get("job_max_salary")
            salary_str = f"₹{int(lo):,} – ₹{int(hi):,}" if (lo and hi) else (f"₹{int(lo):,}+" if lo else "Not disclosed")

            jobs.append({
                "source":        "JSearch",
                "title":         job.get("job_title", ""),
                "employer":      job.get("employer_name", ""),
                "location":      job.get("job_city") or city,
                "salary":        salary_str,
                "duration":      "N/A",
                "status":        "Active",
                "apply_link":    link,
                "description":   desc[:2000],
                "skills":        _extract_skills_fast(text_blob),
                "employment_type": job.get("job_employment_type", ""),
                "posted_at":     job.get("job_posted_at_datetime_utc", ""),
                "employer_logo": job.get("employer_logo", ""),
            })

    print(f"  ✅ JSearch → {len(jobs)} jobs total")
    return jobs


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
            if isinstance(row.get("skills"), list): row["skills"] = ", ".join(row["skills"])
            if isinstance(row.get("missing_skills"), dict): row.pop("missing_skills", None)
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
    
    if sources is None:
        sources = ["internshala", "indeed", "jsearch"]

    # --- PRODUCTION GUARD ---
    IS_RENDER = os.getenv("RENDER") == "true"
    if IS_RENDER:
        print("⚠️ [PRODUCTION MODE] Disabling Selenium scrapers to prevent RAM crash.")
        # Replaces Selenium with TiDB database pull + live JSearch
        sources = ["database", "jsearch"]

    domain_clean = domain.lower().strip()
    keyword = DOMAIN_KEYWORDS.get(domain_clean)
    if keyword is None:
        keyword = domain.strip().title() if domain.strip() else ""
    keyword = keyword or domain_clean

    print(f"\n🚀 Aggregating jobs | domain={domain!r} keyword={keyword!r} city={city!r}")
    print(f"   Sources: {sources}  date_filter={date_filter!r}")

    import time as _t
    _start = _t.time()
    loop = asyncio.get_event_loop()

    # ── PREPARE TASKS ──────────────────────────────────────────────────────
    tasks = []

    if "database" in sources:
        tasks.append(loop.run_in_executor(_EXECUTOR, _fetch_jobs_from_db, domain_clean, city))

    if "internshala" in sources:
        from app.services.internshala_scraper import scrape_internshala_fast
        tasks.append(loop.run_in_executor(_EXECUTOR, scrape_internshala_fast, keyword, city, date_filter))

    if "indeed" in sources:
        from app.services.indeed_scraper import scrape_indeed_fast
        tasks.append(loop.run_in_executor(_EXECUTOR, scrape_indeed_fast, keyword, city, date_filter))

    if "jsearch" in sources:
        tasks.append(_scrape_jsearch(keyword, city, date_filter))

    # ── EXECUTE ALL CONCURRENTLY ──────────────────────────────────────────
    print(f"  ▶️  Launching all sources ({len(tasks)}) concurrently...")
    raw_results = await asyncio.gather(*tasks, return_exceptions=True)

    # ── PROCESS RESULTS ───────────────────────────────────────────────────
    scraper_jobs: list[dict] = []
    jsearch_jobs: list[dict] = []
    sources_hit: dict[str, int] = {}

    task_idx = 0
    if "database" in sources:
        res = raw_results[task_idx]
        if not isinstance(res, Exception):
            scraper_jobs.extend(res) # Treat DB jobs as "scraper jobs" for logic
            sources_hit["database"] = len(res)
        task_idx += 1

    if "internshala" in sources:
        res = raw_results[task_idx]
        if not isinstance(res, Exception):
            scraper_jobs.extend(res)
            sources_hit["internshala"] = len(res)
        task_idx += 1

    if "indeed" in sources:
        res = raw_results[task_idx]
        if not isinstance(res, Exception):
            scraper_jobs.extend(res)
            sources_hit["indeed"] = len(res)
        task_idx += 1

    if "jsearch" in sources:
        res = raw_results[task_idx]
        if not isinstance(res, Exception):
            jsearch_jobs.extend(res)
            sources_hit["jsearch"] = len(res)
        task_idx += 1

    _gather_elapsed = _t.time() - _start
    print(f"  ⏱️  All sources gathered in {_gather_elapsed:.1f}s")

    # ── Log raw counts per source before dedup ────────────────────────────
    print(f"\n  📊 Raw counts before dedup:")
    for source_name, count in sources_hit.items():
        print(f"       {source_name.title()} : {count} jobs")

    # ── Apply split logic ─────────────────────────────────────────────────
    if jsearch_jobs:
        total_target = len(scraper_jobs) + len(jsearch_jobs)
        if scraper_jobs:
            scraper_cap = max(1, int(total_target * 0.75))
            jsearch_cap = max(1, total_target - scraper_cap)
            combined = scraper_jobs[:scraper_cap] + jsearch_jobs[:jsearch_cap]
        else:
            combined = jsearch_jobs
    else:
        combined = scraper_jobs

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

    # ── Score all jobs using MULTIPROCESSING (CPU-bound optimization) ──
    _up = user_profile or {}
    _rt = resume_text or ""

    if any(_up.values()) if _up else False:
        print(f"  🎯 Scoring {len(unique_jobs)} jobs using parallel CPU cores...")
        _score_start = time.time()
        
        # NOTE: ProcessPoolExecutor requires __main__ on Windows, safe on Render (Linux)
        with ProcessPoolExecutor(max_workers=os.cpu_count() or 1) as process_executor:
            scored_jobs = list(process_executor.map(
                _score_job_wrapper, 
                [(job, _up, _rt) for job in unique_jobs]
            ))
        print(f"  🎯 Scoring done in {time.time() - _score_start:.1f}s")
    else:
        scored_jobs = unique_jobs

    # ── Sort by match_score descending ────────────────────────────────────
    scored_jobs.sort(key=lambda j: j.get("match_score", 0), reverse=True)

    # ── Save to CSV ──────────────────────────────────────────────────────
    csv_path = await loop.run_in_executor(
        _EXECUTOR, _save_to_csv, scored_jobs, domain, city
    )

    # ── Final Alignment for Frontend ──
    for job in scored_jobs:
        skills_raw = job.get("skills", [])
        if isinstance(skills_raw, str):
            parts = [s.strip() for s in skills_raw.split(",") if s.strip()]
            skills_list = [s for s in parts if s.lower() != "not listed"]
        elif isinstance(skills_raw, list):
            skills_list = [str(s).strip() for s in skills_raw if str(s).strip()]
        else:
            skills_list = []
        
        job["skills"] = skills_list
        job["qualifications"] = skills_list[:6] 
        if "match_score" not in job: job["match_score"] = 0

    return {
        "jobs":        scored_jobs,
        "total":       len(scored_jobs),
        "csv_path":    str(csv_path),
        "sources_hit": sources_hit,
        "city":        city
    }