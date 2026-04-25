"""
app/services/job_scraper_service.py  — v3
────────────────────────────────────────────────────────────────────────────────
ROOT CAUSE OF HANG (found in v2):
  sklearn's TfidfVectorizer uses numpy/OpenBLAS internally.
  On Render's free tier, OpenBLAS reads /proc/cpuinfo and thinks it has 2+ CPUs,
  so it spawns its own internal thread pool. When scoring runs inside
  run_in_executor(), those OpenBLAS threads deadlock against the ThreadPoolExecutor
  — the container CPU is over-subscribed and threads starve indefinitely.

THE FIX:
  1. Set OMP_NUM_THREADS=1 and OPENBLAS_NUM_THREADS=1 at process start.
     This forces numpy/sklearn to run single-threaded. Fast enough for 50-300 jobs.
  2. Run scoring DIRECTLY in the async event loop (no executor at all).
     Sklearn TF-IDF releases the GIL, so it doesn't block other coroutines.
  3. Separate executor pool for I/O (DB, CSV) vs compute — avoids pool exhaustion.
────────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

# ── CRITICAL: Must be set BEFORE numpy/sklearn is imported anywhere ──────────
import os
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")

import asyncio
import csv
import re
import time
import json
import pymysql
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

load_dotenv()

JSEARCH_API_KEY: str = os.getenv("JSEARCH_API_KEY", "")

# ── Directories ──────────────────────────────────────────────────────────────
_SERVICE_DIR   = Path(__file__).resolve().parent
_ROOT          = _SERVICE_DIR.parent.parent
CACHE_DIR      = _ROOT / "tmp" / "jobs_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
SKILLS_JSON_PATH = _ROOT / "app" / "data" / "skills_master_indeed.json"

# ── Single I/O thread pool (DB reads, CSV writes only — NOT scoring) ─────────
_IO_EXECUTOR = ThreadPoolExecutor(max_workers=4)

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

DATE_FILTER_DAYS: dict[str, int] = {
    "24h": 1, "today": 1,
    "3days": 3, "last 3 days": 3,
    "week": 7, "last week": 7,
    "month": 30, "last month": 30,
}

def _days_for_filter(date_filter: str) -> int:
    return DATE_FILTER_DAYS.get(date_filter.lower().strip(), 30)


# ════════════════════════════════════════════════════════════════════════════
# SKILLS — loaded once at startup
# ════════════════════════════════════════════════════════════════════════════
def load_skills_from_json() -> list[str]:
    try:
        if not SKILLS_JSON_PATH.exists():
            return []
        with open(SKILLS_JSON_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        flat = set()
        for item in data:
            flat.add(item["name"].lower())
            for syn in item.get("synonyms", []):
                flat.add(syn.lower())
        return sorted(flat, key=len, reverse=True)
    except Exception as e:
        print(f"⚠️ Error loading skills JSON: {e}")
        return []

KNOWN_SKILLS = load_skills_from_json()

def _extract_skills_fast(text: str) -> list[str]:
    if not text:
        return []
    tl = text.lower()
    found: set[str] = set()
    for skill in KNOWN_SKILLS:
        pattern = r'(?<![a-zA-Z0-9])' + re.escape(skill) + r'(?![a-zA-Z0-9])'
        if re.search(pattern, tl):
            if len(skill) <= 3:
                found.add(skill.upper())
            else:
                mapping = {"node.js": "Node.js", "mongodb": "MongoDB"}
                found.add(mapping.get(skill, skill.title()))
    return sorted(found)


# ════════════════════════════════════════════════════════════════════════════
# SOURCE: TIDB DATABASE
# ════════════════════════════════════════════════════════════════════════════
def _fetch_jobs_from_db(domain: str, city: str, date_filter: str = "month") -> list[dict]:
    days   = _days_for_filter(date_filter)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    try:
        conn = pymysql.connect(
            host=os.getenv("TIDB_HOST"),
            user=os.getenv("TIDB_USER"),
            password=os.getenv("TIDB_PASS"),
            database=os.getenv("TIDB_NAME"),
            port=4000,
            ssl={"ssl_mode": "PREFERRED"},
            cursorclass=pymysql.cursors.DictCursor,
            connect_timeout=10,
        )
        with conn.cursor() as cur:
            cur.execute("""
                SELECT source, title, company AS employer, location,
                       link AS apply_link, skills, domain, scraped_at
                FROM jobs
                WHERE domain = %s
                  AND (
                        LOWER(location) LIKE %s
                     OR LOWER(location) LIKE '%%work from home%%'
                     OR LOWER(location) LIKE '%%remote%%'
                  )
                  AND scraped_at >= %s
                ORDER BY scraped_at DESC
                LIMIT 300
            """, (domain, f"%{city.lower()}%", cutoff))
            rows = cur.fetchall()
        conn.close()

        jobs = []
        for row in rows:
            skills_str = row.get("skills") or ""
            skills_list = [s.strip() for s in skills_str.split(",") if s.strip()]
            ts = row.get("scraped_at")
            jobs.append({
                "source":          row.get("source", "Database"),
                "title":           row.get("title", ""),
                "employer":        row.get("employer", ""),
                "location":        row.get("location", ""),
                "salary":          "Not disclosed",
                "duration":        "N/A",
                "status":          "Active",
                "apply_link":      row.get("apply_link", ""),
                "description":     "",
                "skills":          skills_list,
                "employment_type": "Full Time",
                "posted_at":       ts.isoformat() if ts else datetime.now(timezone.utc).isoformat(),
                "employer_logo":   "",
            })
        print(f"  🗄️ TiDB Database → Found {len(jobs)} saved jobs (last {days} days).")
        return jobs
    except Exception as e:
        print(f"  ⚠️ Database fetch error: {e}")
        return []


# ════════════════════════════════════════════════════════════════════════════
# SCORING — runs directly in the async event loop, NO executor
#
# WHY NO EXECUTOR:
#   sklearn's TF-IDF releases the GIL during vectorisation, so it doesn't
#   block other coroutines. Putting it in a thread pool on Render causes
#   OpenBLAS to spawn its own threads → deadlock on a single-vCPU container.
#   Keeping it synchronous here is both simpler and faster on Render.
# ════════════════════════════════════════════════════════════════════════════
def _batch_score_jobs(
    jobs: list[dict],
    user_profile: dict,
    resume_text: str,
) -> list[dict]:
    """
    Score all jobs in one pass:
    - Single TF-IDF matrix (resume + all job texts) — O(N) not O(N²)
    - Structured skill overlap per job — pure Python, fast
    - Runs single-threaded (OMP_NUM_THREADS=1) to avoid OpenBLAS deadlock
    """
    if not jobs:
        return jobs

    if not any(user_profile.values()):
        for job in jobs:
            job.update({"match_score": 0.0, "gap_severity": "N/A", "missing_skills": {}})
        return jobs

    from app.services.scoring_model import structured_skill_score, hybrid_match_score, gap_severity
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity

    WEIGHTS = {"technical": 0.55, "tools": 0.25, "soft": 0.20}

    # Build job text blobs and skill profiles in one pass
    job_texts: list[str] = []
    job_profiles: list[dict] = []
    for job in jobs:
        blob = f"{job.get('title', '')} {job.get('description', '')[:1500]}"
        skills = job.get("skills", [])
        jp = {"technical": list(skills) if skills else _extract_skills_fast(blob),
              "tools": [], "soft": []}
        job_profiles.append(jp)
        job_texts.append(blob)

    # Single TF-IDF pass: [resume, job0, job1, ... jobN]
    semantic_scores: list[float] = [0.0] * len(jobs)
    try:
        vec = TfidfVectorizer(stop_words="english", max_features=5000)
        mat = vec.fit_transform([resume_text or ""] + job_texts)
        sims = cosine_similarity(mat[0:1], mat[1:])[0]  # shape: (N,)
        semantic_scores = (sims * 100).tolist()
    except Exception as e:
        print(f"  ⚠️ TF-IDF error: {e}")

    # Structured scoring loop
    for i, job in enumerate(jobs):
        try:
            struct, missing = structured_skill_score(user_profile, job_profiles[i], WEIGHTS)
            final = hybrid_match_score(struct, float(semantic_scores[i]))
            job["match_score"]    = round(final, 1)
            job["gap_severity"]   = gap_severity(final)
            job["missing_skills"] = missing
        except Exception as e:
            print(f"  ⚠️ Score error job {i}: {e}")
            job.update({"match_score": 0.0, "gap_severity": "N/A", "missing_skills": {}})

    return jobs


# ════════════════════════════════════════════════════════════════════════════
# SOURCE: JSEARCH API
# ════════════════════════════════════════════════════════════════════════════
async def _scrape_jsearch(keyword: str, city: str, date_filter: str = "month") -> list[dict]:
    if not JSEARCH_API_KEY:
        print("  ⚠️  JSEARCH_API_KEY not set — skipping JSearch")
        return []

    date_map = {
        "24h": "today", "today": "today",
        "3days": "3days", "last 3 days": "3days",
        "week": "week", "last week": "week",
        "month": "month",
    }
    date_posted = date_map.get(date_filter.lower().strip(), "month")
    queries = [f"{keyword} internship in {city}", f"{keyword} fresher jobs in {city}"]
    seen: set[str] = set()
    jobs: list[dict] = []

    headers = {"x-rapidapi-key": JSEARCH_API_KEY, "x-rapidapi-host": "jsearch.p.rapidapi.com"}

    async with httpx.AsyncClient(timeout=15) as client:
        responses = await asyncio.gather(*[
            client.get("https://jsearch.p.rapidapi.com/search",
                       params={"query": q, "page": "1", "num_pages": "3", "date_posted": date_posted},
                       headers=headers)
            for q in queries
        ], return_exceptions=True)

    if any(not isinstance(r, Exception) and getattr(r, "status_code", None) == 429
           for r in responses):
        print("  ⚠️  JSearch returned HTTP 429 (rate-limited) — skipping")
        return []

    for resp in responses:
        if isinstance(resp, Exception) or resp.status_code != 200:
            continue
        for job in resp.json().get("data", []):
            link = job.get("job_apply_link", "")
            if not link or link in seen:
                continue
            seen.add(link)
            desc = job.get("job_description", "") or ""
            qualifs = job.get("job_highlights", {}).get("Qualifications") or []
            blob = f"{job.get('job_title','')} {' '.join(str(q) for q in qualifs[:5])} {desc[:1500]}"
            lo, hi = job.get("job_min_salary"), job.get("job_max_salary")
            salary = f"₹{int(lo):,} – ₹{int(hi):,}" if (lo and hi) else (f"₹{int(lo):,}+" if lo else "Not disclosed")
            jobs.append({
                "source": "JSearch", "title": job.get("job_title", ""),
                "employer": job.get("employer_name", ""), "location": job.get("job_city") or city,
                "salary": salary, "duration": "N/A", "status": "Active",
                "apply_link": link, "description": desc[:2000],
                "skills": _extract_skills_fast(blob),
                "employment_type": job.get("job_employment_type", ""),
                "posted_at": job.get("job_posted_at_datetime_utc", ""),
                "employer_logo": job.get("employer_logo", ""),
            })

    print(f"  ✅ JSearch → {len(jobs)} jobs")
    return jobs


# ════════════════════════════════════════════════════════════════════════════
# CSV CACHE
# ════════════════════════════════════════════════════════════════════════════
_CSV_FIELDS = [
    "source", "title", "employer", "location", "salary", "duration", "status",
    "employment_type", "skills", "match_score", "gap_severity", "apply_link", "posted_at",
]

def _save_to_csv(jobs: list[dict], domain: str, city: str) -> Path:
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = re.sub(r"[^a-z0-9_]", "_", f"{domain or 'all'}_{city}".lower())
    path = CACHE_DIR / f"{slug}_{ts}.csv"
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=_CSV_FIELDS, extrasaction="ignore")
        w.writeheader()
        for job in jobs:
            row = dict(job)
            if isinstance(row.get("skills"), list):
                row["skills"] = ", ".join(row["skills"])
            row.pop("missing_skills", None)
            w.writerow(row)
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

    IS_RENDER = os.getenv("RENDER") == "true"
    if IS_RENDER or sources is None:
        sources = ["database", "jsearch"]
    if IS_RENDER:
        print("⚠️ [PRODUCTION MODE] Disabling Selenium scrapers to prevent RAM crash.")

    domain_clean = domain.lower().strip()
    keyword = DOMAIN_KEYWORDS.get(domain_clean) or domain.strip().title() or domain_clean

    print(f"\n🚀 Aggregating jobs | domain={domain!r} keyword={keyword!r} city={city!r}")
    print(f"   Sources: {sources}  date_filter={date_filter!r}")

    _start = time.time()
    loop   = asyncio.get_event_loop()

    # ── Launch I/O sources concurrently ──────────────────────────────────────
    tasks = []
    if "database" in sources:
        tasks.append(("database", loop.run_in_executor(
            _IO_EXECUTOR, _fetch_jobs_from_db, domain_clean, city, date_filter
        )))
    if "internshala" in sources:
        from app.services.internshala_scraper import scrape_internshala_fast
        tasks.append(("internshala", loop.run_in_executor(
            _IO_EXECUTOR, scrape_internshala_fast, keyword, city, date_filter
        )))
    if "indeed" in sources:
        from app.services.indeed_scraper import scrape_indeed_fast
        tasks.append(("indeed", loop.run_in_executor(
            _IO_EXECUTOR, scrape_indeed_fast, keyword, city, date_filter
        )))
    if "jsearch" in sources:
        tasks.append(("jsearch", _scrape_jsearch(keyword, city, date_filter)))

    print(f"  ▶️  Launching all sources ({len(tasks)}) concurrently...")
    names    = [t[0] for t in tasks]
    results  = await asyncio.gather(*[t[1] for t in tasks], return_exceptions=True)

    # ── Collect results ───────────────────────────────────────────────────────
    scraper_jobs: list[dict] = []
    jsearch_jobs: list[dict] = []
    sources_hit: dict[str, int] = {}

    for name, res in zip(names, results):
        if isinstance(res, Exception):
            print(f"  ⚠️  {name} error: {res}")
            sources_hit[name] = 0
            continue
        sources_hit[name] = len(res)
        if name == "jsearch":
            jsearch_jobs.extend(res)
        else:
            scraper_jobs.extend(res)

    print(f"  ⏱️  All sources gathered in {time.time() - _start:.1f}s")
    print(f"\n  📊 Raw counts before dedup:")
    for sname, count in sources_hit.items():
        print(f"       {sname.title():12s}: {count} jobs")

    # ── Merge (75% scraper / 25% jsearch) ────────────────────────────────────
    if jsearch_jobs and scraper_jobs:
        total  = len(scraper_jobs) + len(jsearch_jobs)
        s_cap  = max(1, int(total * 0.75))
        j_cap  = max(1, total - s_cap)
        combined = scraper_jobs[:s_cap] + jsearch_jobs[:j_cap]
    elif jsearch_jobs:
        combined = jsearch_jobs
    else:
        combined = scraper_jobs

    # ── Dedup by apply_link ───────────────────────────────────────────────────
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

    # ── SCORING — runs synchronously in the event loop, NO thread pool ────────
    # This avoids the OpenBLAS multi-thread deadlock on Render containers.
    _up = user_profile or {}
    _rt = resume_text or ""
    if any(_up.values()) if _up else False:
        print(f"  🎯 Scoring {len(unique_jobs)} jobs (single-threaded batch TF-IDF)...")
        _score_start = time.time()
        scored_jobs = _batch_score_jobs(unique_jobs, _up, _rt)   # ← direct call, no executor
        print(f"  🎯 Scoring done in {time.time() - _score_start:.1f}s")
    else:
        scored_jobs = unique_jobs

    scored_jobs.sort(key=lambda j: j.get("match_score", 0), reverse=True)

    # ── CSV (offloaded to I/O thread so it doesn't block the event loop) ─────
    csv_path = await loop.run_in_executor(
        _IO_EXECUTOR, _save_to_csv, scored_jobs, domain, city
    )

    # ── Normalise skills for frontend ─────────────────────────────────────────
    for job in scored_jobs:
        raw = job.get("skills", [])
        if isinstance(raw, str):
            lst = [s.strip() for s in raw.split(",") if s.strip() and s.strip().lower() != "not listed"]
        else:
            lst = [str(s).strip() for s in raw if str(s).strip()]
        job["skills"]         = lst
        job["qualifications"] = lst[:6]
        job.setdefault("match_score", 0)

    return {
        "jobs":        scored_jobs,
        "total":       len(scored_jobs),
        "csv_path":    str(csv_path),
        "sources_hit": sources_hit,
        "city":        city,
    }
