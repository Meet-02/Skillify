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

def _score_job_wrapper(args):
    """Helper for multiprocessing to unpack arguments."""
    job, user_profile, resume_text = args
    return _score_job(job, user_profile, resume_text)
    
import json

# Use the absolute root path you already defined in the file
_SERVICE_DIR = Path(__file__).resolve().parent
_ROOT = _SERVICE_DIR.parent.parent
SKILLS_JSON_PATH = _ROOT / "app" / "data" / "skills_master_indeed.json"

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
        
        # Sort by length descending so 'React Native' matches before 'React'
        return sorted(list(flat_skills), key=len, reverse=True)
    except Exception as e:
        print(f"⚠️ Error loading skills JSON: {e}")
        return []

# Now KNOWN_SKILLS is always synced with your JSON
KNOWN_SKILLS = load_skills_from_json() 


def _extract_skills_fast(text: str) -> list[str]:
    """Resilient keyword skill extraction using Regex Lookarounds."""
    if not text: 
        return []
    
    tl = text.lower()
    found = set()
    
    for skill in KNOWN_SKILLS:
        skill_clean = skill.lower()
        # The 'Secret Sauce': Lookarounds catch skills even without spaces around them
        pattern = r'(?<![a-zA-Z0-9])' + re.escape(skill_clean) + r'(?![a-zA-Z0-9])'
        
        if re.search(pattern, tl):
            # Normalization logic
            if len(skill_clean) <= 3:
                found.add(skill_clean.upper())
            else:
                special_cases = {"mern", "mean", "rest", "node.js", "mongodb"}
                if skill_clean in special_cases:
                    # Professional formatting
                    mapping = {"node.js": "Node.js", "mongodb": "MongoDB"}
                    found.add(mapping.get(skill_clean, skill_clean.upper()))
                else:
                    found.add(skill_clean.title())
                
    return sorted(list(found))

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

    # ── PREPARE TASKS ──────────────────────────────────────────────────────
    tasks = []

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
    
    # This is where the magic happens!
    raw_results = await asyncio.gather(*tasks, return_exceptions=True)

    # ── PROCESS RESULTS ───────────────────────────────────────────────────
    scraper_jobs: list[dict] = []
    jsearch_jobs: list[dict] = []
    sources_hit: dict[str, int] = {}

    # Map results back to their sources based on order of 'tasks' list
    task_idx = 0
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
    print(f"       Internshala : {sources_hit.get('internshala', 0)} jobs")
    print(f"       Indeed      : {sources_hit.get('indeed', 0)} jobs")
    print(f"       JSearch     : {sources_hit.get('jsearch', 0)} jobs")
    print(f"       Scrapers total: {len(scraper_jobs)} | JSearch total: {len(jsearch_jobs)}")

    # ── Apply split logic ─────────────────────────────────────────────────
    # If JSearch returned jobs: apply 75% scrapers / 25% JSearch cap.
    # If JSearch is empty (quota/429): disable the cap entirely and use
    # 100% of scraper results so volume isn't artificially limited.
    if jsearch_jobs:
        total_target = len(scraper_jobs) + len(jsearch_jobs)
        if scraper_jobs:
            scraper_cap = max(1, int(total_target * 0.75))
            jsearch_cap = max(1, total_target - scraper_cap)
            combined = scraper_jobs[:scraper_cap] + jsearch_jobs[:jsearch_cap]
            print(f"  📦 75/25 split applied: scrapers capped={scraper_cap} jsearch capped={jsearch_cap}")
        else:
            # Scrapers empty — fall back to 100% JSearch
            combined = jsearch_jobs
            print(f"  ⚠️  No scraper jobs — falling back to 100% JSearch ({len(jsearch_jobs)} jobs)")
    else:
        # JSearch empty (quota/429) — use 100% of scraper results, no cap
        combined = scraper_jobs
        print(f"  ⚠️  JSearch returned 0 jobs (quota/429?) — using 100% scraper results ({len(scraper_jobs)} jobs, no cap)")

    print(f"\n  📦 Total raw (before dedup): scrapers={len(scraper_jobs)} jsearch={len(jsearch_jobs)} combined={len(combined)}")

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

    print(f"  🔗 After dedup: {len(unique_jobs)} jobs (removed {len(combined) - len(unique_jobs)} duplicates)")

# ── Score all jobs using MULTIPROCESSING (CPU-bound optimization) ──
    _up = user_profile or {}
    _rt = resume_text or ""

    if any(_up.values()) if _up else False:
        print(f"  🎯 Scoring {len(unique_jobs)} jobs using parallel CPU cores...")
        _score_start = time.time()
        
        from concurrent.futures import ProcessPoolExecutor
        # Use all available CPU cores to score jobs in parallel
        with ProcessPoolExecutor(max_workers=os.cpu_count()) as process_executor:
            scored_jobs = list(process_executor.map(
                _score_job_wrapper, 
                [(job, _up, _rt) for job in unique_jobs]
            ))
        print(f"  🎯 Scoring done in {time.time() - _score_start:.1f}s")

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
# ── Final Alignment for Frontend ──
    for job in scored_jobs:
        # 1. Clean up skills: Ensure it is a list, never a string or "Not listed"
        skills_raw = job.get("skills", [])
        if isinstance(skills_raw, str):
            parts = [s.strip() for s in skills_raw.split(",") if s.strip()]
            skills_list = [s for s in parts if s.lower() != "not listed"]
        elif isinstance(skills_raw, list):
            skills_list = [str(s).strip() for s in skills_raw if str(s).strip()]
        else:
            skills_list = []
        
        job["skills"] = skills_list

        # 2. Map to qualifications for frontend UI (tags)
        # This ensures the 'Node, React, Express' tags actually appear on the card
        job["qualifications"] = skills_list[:6] 
            
        # 3. Ensure match_score exists for the SVG ring
        if "match_score" not in job:
            job["match_score"] = 0

    return {
        "jobs":        scored_jobs,
        "total":       len(scored_jobs),
        "csv_path":    str(csv_path),
        "sources_hit": sources_hit,
        "city":        city
    }

    # return result
