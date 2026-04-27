"""
run_background_scraper.py
────────────────────────────────────────────────────────────────────────────────
Background scraper run by GitHub Actions every 12 hours.

FIXES:
  1. Expanded to ALL domains (not just frontend + data).
  2. Expanded to multiple cities so DB has broad coverage.
  3. scraped_at is now set on every INSERT so date_filter works in production.
────────────────────────────────────────────────────────────────────────────────
"""

import os
import pymysql
import requests  # <-- ADDED for JSearch
from datetime import datetime, timezone
from dotenv import load_dotenv
from app.services.internshala_scraper import scrape_internshala_fast
from app.services.indeed_scraper import scrape_indeed_fast

load_dotenv()

# ── All domains to scrape ──────────────────────────────────────────────────────
# Add / remove entries freely. Key = search keyword, value = DB domain tag.
JOB_TARGETS = {
    "Backend Developer":     "backend",
    "Data Science":          "data",    
}

# Cities to scrape for each domain
CITIES = ["Mumbai"]


def get_connection():
    return pymysql.connect(
        host=os.getenv('TIDB_HOST'),
        user=os.getenv('TIDB_USER'),
        password=os.getenv('TIDB_PASS'),
        database=os.getenv('TIDB_NAME'),
        port=int(os.getenv('TIDB_PORT', 4000)),
        ssl={'ssl_mode': 'PREFERRED'},
    )


def ensure_schema(connection):
    """Make sure the jobs table has the domain and scraped_at columns."""
    with connection.cursor() as cursor:
        # Add domain column if missing
        cursor.execute("""
            SELECT COUNT(*) FROM information_schema.columns
            WHERE table_schema = DATABASE()
              AND table_name = 'jobs'
              AND column_name = 'domain'
        """)
        if cursor.fetchone()[0] == 0:
            cursor.execute("ALTER TABLE jobs ADD COLUMN domain VARCHAR(50) DEFAULT '' AFTER skills")
            print("  ✅ Added 'domain' column to jobs table.")

        # Add scraped_at column if missing (critical for date_filter to work!)
        cursor.execute("""
            SELECT COUNT(*) FROM information_schema.columns
            WHERE table_schema = DATABASE()
              AND table_name = 'jobs'
              AND column_name = 'scraped_at'
        """)
        if cursor.fetchone()[0] == 0:
            cursor.execute(
                "ALTER TABLE jobs ADD COLUMN scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP AFTER domain"
            )
            cursor.execute("UPDATE jobs SET scraped_at = created_at WHERE scraped_at IS NULL")
            print("  ✅ Added 'scraped_at' column to jobs table.")

        # Add index on (domain, scraped_at) for fast filtered queries
        cursor.execute("""
            SELECT COUNT(*) FROM information_schema.statistics
            WHERE table_schema = DATABASE()
              AND table_name = 'jobs'
              AND index_name = 'idx_domain_scraped'
        """)
        if cursor.fetchone()[0] == 0:
            cursor.execute("ALTER TABLE jobs ADD INDEX idx_domain_scraped (domain, scraped_at)")
            print("  ✅ Added index idx_domain_scraped.")

    connection.commit()


def save_jobs_to_tidb(jobs: list, source: str, domain_tag: str):
    if not jobs:
        print(f"  ⚠️  No {source} jobs to save for domain={domain_tag!r}.")
        return

    print(f"Connecting to DB: {os.getenv('TIDB_HOST')} as {os.getenv('TIDB_USER')}")
    connection = get_connection()
    now = datetime.now(timezone.utc)

    with connection.cursor() as cursor:
        # First run: ensure schema is up to date
        ensure_schema(connection)

        saved = 0
        for job in jobs:
            skills_str = ", ".join(job.get('skills', []))
            try:
                title_val   = job.get('title', '').strip()
                company_val = job.get('employer', '').strip()
                link_val    = job.get('apply_link', '').strip()

                # Dedup strategy: if same title+company+domain already exists
                # (possibly with a different URL slug), update it instead of inserting.
                cursor.execute("""
                    SELECT id FROM jobs
                    WHERE LOWER(title) = LOWER(%s)
                      AND LOWER(company) = LOWER(%s)
                      AND domain = %s
                    LIMIT 1
                """, (title_val, company_val, domain_tag))
                existing = cursor.fetchone()

                if existing:
                    # Update scraped_at + skills so it stays fresh in date_filter queries
                    cursor.execute("""
                        UPDATE jobs SET scraped_at = %s, skills = %s, link = %s
                        WHERE id = %s
                    """, (now, skills_str, link_val or existing[0], existing[0]))
                else:
                    cursor.execute("""
                        INSERT IGNORE INTO jobs
                            (source, title, company, location, link, skills, domain, scraped_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        job.get('source', source),
                        title_val, company_val,
                        job.get('location', ''),
                        link_val,
                        skills_str,
                        domain_tag,
                        now,
                    ))
                saved += 1
            except Exception as e:
                print(f"  ⚠️  Insert error: {e}")

    connection.commit()
    connection.close()
    print(f"  ✅ Saved/updated {saved} {source} jobs for domain={domain_tag!r}.")


# ── ADDED: Synchronous JSearch Scraper ─────────────────────────────────────────
def scrape_jsearch_fast(keyword: str, city: str, date_filter: str = "3days", max_pages: int = 1) -> list[dict]:
    api_key = os.getenv("JSEARCH_API_KEY")
    if not api_key:
        print("  ⚠️ JSEARCH_API_KEY not found in .env! Skipping JSearch.")
        return []

    print(f"  Scraping JSearch for {keyword} in {city} (Max Pages: {max_pages})...")
    url = "https://jsearch.p.rapidapi.com/search"
    headers = {
        "x-rapidapi-key": api_key,
        "x-rapidapi-host": "jsearch.p.rapidapi.com"
    }

    # Format query for JSearch
    query = f"{keyword} in {city}"
    
    # Map '3days' to RapidAPI's expected string format
    date_map = {"3days": "3days", "week": "week", "month": "month"}
    date_posted = date_map.get(date_filter.lower().strip(), "month")

    querystring = {
        "query": query,
        "page": "1",
        "num_pages": str(max_pages),
        "date_posted": date_posted
    }

    jobs = []
    try:
        response = requests.get(url, headers=headers, params=querystring, timeout=30)
        
        if response.status_code == 200:
            data = response.json().get("data", [])
            for job in data:
                # Discard jobs with no link to match our strict DB limits
                link = job.get("job_apply_link", "")
                if not link:
                    continue
                    
                jobs.append({
                    "source": "JSearch",
                    "title": job.get("job_title", ""),
                    "employer": job.get("employer_name", ""),
                    "location": job.get("job_city") or city,
                    "apply_link": link,
                    "skills": [], # The DB matcher/frontend handles skills via text blob
                })
            print(f"  ✅ JSearch: Found {len(jobs)} jobs!")
            
        elif response.status_code == 429:
            print("  ❌ JSearch Error 429: Monthly RapidAPI quota exhausted!")
        else:
            print(f"  ⚠️ JSearch API Error: {response.status_code} - {response.text}")
            
    except Exception as e:
        print(f"  ⚠️ JSearch Network Error: {e}")

    return jobs
# ───────────────────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    print("🚀 Starting Background Scrapers...")
    print(f"   Domains : {len(JOB_TARGETS)}")
    print(f"   Cities  : {CITIES}")

    total_saved = 0

    for keyword, domain_tag in JOB_TARGETS.items():
        for city in CITIES:
            print(f"\n── {keyword} / {city} ──")

            try:
                print(f"  Scraping Internshala...")
                internshala_jobs = scrape_internshala_fast(keyword, city, "3days",max_pages=1)
                save_jobs_to_tidb(internshala_jobs, "Internshala", domain_tag)
                total_saved += len(internshala_jobs)
            except Exception as e:
                print(f"  ❌ Internshala error: {e}")

            try:
                print(f"  Scraping Indeed...")
                indeed_jobs = scrape_indeed_fast(keyword, city, "3days",max_pages=5)
                save_jobs_to_tidb(indeed_jobs, "Indeed", domain_tag)
                total_saved += len(indeed_jobs)
            except Exception as e:
                print(f"  ❌ Indeed error: {e}")

            # ── ADDED: JSearch Try/Except Block ──────────────────────────────────
            try:
                print(f"  Scraping JSearch...")
                jsearch_jobs = scrape_jsearch_fast(keyword, city, "3days", max_pages=1)
                save_jobs_to_tidb(jsearch_jobs, "JSearch", domain_tag)
                total_saved += len(jsearch_jobs)
            except Exception as e:
                print(f"  ❌ JSearch error: {e}")
            # ─────────────────────────────────────────────────────────────────────

    print(f"\n🎉 Background scraping complete! ~{total_saved} jobs processed.")