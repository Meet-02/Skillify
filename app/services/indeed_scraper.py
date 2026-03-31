import time
import os
from pathlib import Path
import re
import random
import pickle
from datetime import datetime, timezone
import pandas as pd
import undetected_chromedriver as uc
from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# ── Indian cities & date-filter map ─────────────────────────
INDIAN_CITIES = {
    "mumbai", "delhi", "bangalore", "bengaluru", "hyderabad", "chennai",
    "pune", "kolkata", "ahmedabad", "jaipur", "surat", "lucknow",
    "noida", "gurugram", "gurgaon", "indore", "bhopal",
}

DATE_FILTER_MAP: dict[str, int] = {
    "24h": 1, "last 24h": 1, "today": 1,
    "3days": 3, "last 3 days": 3,
    "week": 7, "last week": 7,
    "month": 30, "last month": 30,
}


import json

# Path to your master skills file
_SERVICE_DIR = Path(__file__).resolve().parent
_ROOT = _SERVICE_DIR.parent.parent
SKILLS_JSON_PATH = _ROOT / "app" / "data" / "skills_master_indeed.json"

def load_skills_from_json():
    try:
        with open(SKILLS_JSON_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        flat_skills = set()
        for item in data:
            # Add the primary name (e.g., "Python")
            flat_skills.add(item["name"].lower())
            # Add all synonyms (e.g., "py", "python3")
            if "synonyms" in item:
                for syn in item["synonyms"]:
                    flat_skills.add(syn.lower())
        
        # Sort by length descending to ensure "Spring Boot" matches before "Spring"
        return sorted(list(flat_skills), key=len, reverse=True)
    except Exception as e:
        print(f"⚠️ Error loading skills_master.json: {e}")
        return []

# Dynamic list replaces the hardcoded block
KNOWN_SKILLS = load_skills_from_json()
 
def extract_skills(text: str) -> list:
    if not text:
        return []
    text_lower = text.lower()
    upper_set = {"sql", "html", "css", "aws", "gcp", "api", "php", "nlp",
                 "seo", "ci/cd", "ios", "npm", "git", "rest api", "restful",
                 "mssql", "devops", "xml", "sdk"}
    found = set()
    for skill in KNOWN_SKILLS:
        if re.search(r'\b' + re.escape(skill) + r'\b', text_lower):
            found.add(skill.upper() if skill in upper_set else skill.title())
    return sorted(found)
 
 
# ─────────────────────────────────────────────────────────────
# SELECTORS
# ─────────────────────────────────────────────────────────────
CARD_SELECTOR       = 'div.job_seen_beacon'
TITLE_LINK_SELECTOR = 'h2.jobTitle a'
TITLE_SELECTOR      = 'h2.jobTitle a span'
COMPANY_SELECTOR    = 'span[data-testid="company-name"]'
LOCATION_SELECTOR   = 'div[data-testid="text-location"]'
SALARY_SELECTOR     = 'li.salary-snippet-container span.css-zydy3i'
META_SNIPPET_SEL    = 'span.css-zydy3i'
RESPONSE_SEL        = 'div.mosaic-provider-jobcards-1f1q1js'
NEXT_PAGE_SEL       = 'a[aria-label="Next Page"]'
JD_PANE_SEL         = '#jobDescriptionText'
 
# ─────────────────────────────────────────────────────────────
# ⚙️  FIRST RUN:  FIRST_RUN = True  → log in manually, saves cookies
#     AFTER THAT:  FIRST_RUN = False → loads cookies automatically
# ─────────────────────────────────────────────────────────────
FIRST_RUN = False  # ← Change to True only for first-time login
 
 
# ─────────────────────────────────────────────────────────────
# SESSION
# ─────────────────────────────────────────────────────────────

SERVICE_DIR = Path(__file__).resolve().parent
COOKIES_FILE = str(SERVICE_DIR / "indeed_cookies.pkl")
USER_DATA_DIR = str(SERVICE_DIR / "indeed_profile")

def save_indeed_session(driver):
    driver.get("https://in.indeed.com/account/login")
    print("\n👉 Log in to Indeed in the browser window.")
    input("   Press Enter once you see the job search homepage...\n")
    pickle.dump(driver.get_cookies(), open(COOKIES_FILE, "wb"))
    print(f"✅ Session saved. Set FIRST_RUN = False and run again.\n")
 
 
# def get_stealth_driver():
#     options = uc.ChromeOptions()
#     if not os.path.exists(USER_DATA_DIR):
#         os.makedirs(USER_DATA_DIR)
    
#     options.add_argument(f"--user-data-dir={USER_DATA_DIR}")
#     # Fix for threading: prevent multiple instances from crashing
#     options.add_argument("--no-first-run")
#     options.add_argument("--no-service-autorun")
#     options.add_argument("--password-store=basic")
    
#     return uc.Chrome(options=options, version_main=146)

def get_stealth_driver():
    options = uc.ChromeOptions()
    if not os.path.exists(USER_DATA_DIR):
        os.makedirs(USER_DATA_DIR)
    
    options.add_argument(f"--user-data-dir={USER_DATA_DIR}")
    
    # --- ADD HEADLESS MODE HERE ---
    options.add_argument("--headless=new")  # Use "--headless=new" if using latest Chrome
    options.add_argument("--no-sandbox")            # <--- ADD THIS
    options.add_argument("--disable-dev-shm-usage")  # <--- ADD THIS
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    # ------------------------------

    # Fix for threading: prevent multiple instances from crashing
    options.add_argument("--no-first-run")
    options.add_argument("--no-service-autorun")
    options.add_argument("--password-store=basic")
    
    return uc.Chrome(options=options)

def load_indeed_session(driver):
    if not os.path.exists(COOKIES_FILE):
        print(f"⚠️ No cookies found at {COOKIES_FILE}. Set FIRST_RUN = True first.")
        return False
    
    driver.get("https://in.indeed.com")
    time.sleep(3)
    try:
        with open(COOKIES_FILE, "rb") as f:
            cookies = pickle.load(f)
            for cookie in cookies:
                driver.add_cookie(cookie)
        driver.refresh()
        time.sleep(3)
        return True
    except Exception as e:
        print(f"❌ Cookie load error: {e}")
        return False
 
 
def close_popups(driver):
    for sel in [
        '//button[@aria-label="close"]',
        '//button[contains(text(),"Close")]',
        '//button[@id="onetrust-accept-btn-handler"]',
        '//button[contains(@class,"popover-x-button")]',
    ]:
        try:
            driver.find_element("xpath", sel).click()
            time.sleep(0.8)
        except:
            pass
 
 
def human_scroll(driver):
    total = driver.execute_script("return document.body.scrollHeight")
    for i in range(random.randint(4, 6)):
        driver.execute_script(f"window.scrollTo(0, {int(total * (i+1) / 6)});")
        time.sleep(random.uniform(0.3, 0.6))
    driver.execute_script("window.scrollTo(0, window.scrollY - 200);")
    time.sleep(0.4)
 
 
def wait_for_cards(driver, timeout=15):
    try:
        WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, CARD_SELECTOR))
        )
        return True
    except:
        return False
 
 
# ─────────────────────────────────────────────────────────────
# STEP 1 — Collect basic info + jk IDs from search results page
# No clicking, no navigation — pure HTML parsing only
# ─────────────────────────────────────────────────────────────
 
def collect_job_stubs(driver, city):
    """
    Parse the current search results page and return a list of job stubs.
    Each stub has all card info + the jk ID needed to visit the detail page.
    Does NOT navigate away from the results page.
    """
    soup  = BeautifulSoup(driver.page_source, 'html.parser')
    cards = soup.select(CARD_SELECTOR)
    print(f"  → Found {len(cards)} cards on results page.")
 
    stubs = []
    seen_jk = set()
 
    for card in cards:
        try:
            title_link = card.select_one(TITLE_LINK_SELECTOR)
            if not title_link:
                continue
 
            jk_id = title_link.get('data-jk', '')
            if not jk_id or jk_id in seen_jk:
                continue
            seen_jk.add(jk_id)
 
            title_span = card.select_one(TITLE_SELECTOR)
            title_text = title_span.get_text(strip=True) if title_span else title_link.get_text(strip=True)
 
            company_el  = card.select_one(COMPANY_SELECTOR)
            location_el = card.select_one(LOCATION_SELECTOR)
            company     = company_el.get_text(strip=True)  if company_el  else "N/A"
            location    = location_el.get_text(strip=True) if location_el else city
 
            salary_el   = card.select_one(SALARY_SELECTOR)
            salary      = salary_el.get_text(strip=True) if salary_el else "Not disclosed"
 
            all_snippets = [s.get_text(strip=True) for s in card.select(META_SNIPPET_SEL)]
            other_meta   = [m for m in all_snippets if m != salary]
            job_type     = other_meta[0] if other_meta else "N/A"
            perks        = ", ".join(other_meta[1:]) if len(other_meta) > 1 else "N/A"
 
            all_resp  = [d.get_text(strip=True) for d in card.select(RESPONSE_SEL)]
            resp_filt = [r for r in all_resp if r not in all_snippets and len(r) > 3]
            status    = resp_filt[0] if resp_filt else "Standard"
 
            stubs.append({
                "jk_id":    jk_id,
                "Job_Title": title_text,
                "Company":   company,
                "City":      city,
                "Location":  location,
                "Salary":    salary,
                "Job_Type":  job_type,
                "Perks":     perks,
                "Status":    status,
                "Link":      f"https://in.indeed.com/viewjob?jk={jk_id}",
            })
        except:
            continue
 
    return stubs
 
 
# ─────────────────────────────────────────────────────────────
# STEP 2 — Visit each job's detail page directly, scrape skills
# Never uses driver.back() — always navigates forward to known URLs
# ─────────────────────────────────────────────────────────────
 
def fetch_skills_for_stubs(driver, stubs, search_url):
    """
    For each stub, navigate directly to its viewjob URL,
    extract the description text, run skill matching,
    then return to the search results URL (not driver.back()).
    """
    results = []
 
    for i, stub in enumerate(stubs):
        job_url = stub["Link"]
        print(f"     [{i+1}/{len(stubs)}] {stub['Job_Title'][:45]}...", end=" ", flush=True)
 
        try:
            driver.get(job_url)
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, JD_PANE_SEL))
            )
            time.sleep(random.uniform(0.8, 1.5))
 
            pane_el   = driver.find_element(By.CSS_SELECTOR, JD_PANE_SEL)
            pane_html = pane_el.get_attribute("innerHTML")
            soup      = BeautifulSoup(pane_html, 'html.parser')
            jd_text   = soup.get_text(separator=" ", strip=True)
            skills    = extract_skills(jd_text)
 
        except Exception as e:
            skills = []
 
        skills_str = ", ".join(skills) if skills else "Not listed"
        print(f"→ {len(skills)} skills")
 
        job = dict(stub)
        job.pop("jk_id")
        job["Skills"] = skills_str
        results.append(job)
 
        # Random delay between job pages — avoids rate limiting
        time.sleep(random.uniform(2.0, 4.0))
 
    return results
 
 
# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────
 
def get_indeed_data(job_title, cities, pages_per_city=3):
    driver   = get_stealth_driver()
    all_jobs = []
 
    try:
        if FIRST_RUN:
            save_indeed_session(driver)
            print("First run done. Set FIRST_RUN = False and run again.")
            return []
        else:
            if not load_indeed_session(driver):
                return []
 
        for city in cities:
            print(f"\n{'─'*55}")
            print(f"🔍 '{job_title}' in {city}")
            print(f"{'─'*55}")
 
            base_url = (f"https://in.indeed.com/jobs"
                        f"?q={job_title.replace(' ', '+')}"
                        f"&l={city.replace(' ', '+')}")
            driver.get(base_url)
            time.sleep(random.uniform(5, 8))
            close_popups(driver)
 
            for page in range(pages_per_city):
                # Build the page URL explicitly so we can return to it
                search_url = base_url if page == 0 else f"{base_url}&start={page * 10}"
                print(f"\n  📄 Page {page + 1}")
 
                if not wait_for_cards(driver):
                    print("  ⚠️  No cards. Waiting 30s...")
                    time.sleep(30)
                    if not wait_for_cards(driver, timeout=10):
                        print("  ❌ Still blocked. Stopping.")
                        break
 
                human_scroll(driver)
                time.sleep(random.uniform(1, 2))
 
                # ── Phase 1: collect all job stubs from this results page ──
                stubs = collect_job_stubs(driver, city)
                if not stubs:
                    print("  ⚠️  No stubs collected.")
                    break
 
                # ── Phase 2: visit each job page to extract skills ──
                print(f"  🔎 Fetching skills for {len(stubs)} jobs...")
                page_results = fetch_skills_for_stubs(driver, stubs, search_url)
                all_jobs.extend(page_results)
                print(f"  ✅ {len(page_results)} jobs done from page {page + 1}")
 
                # ── Navigate to next results page directly via URL ──
                if page < pages_per_city - 1:
                    next_url = f"{base_url}&start={(page + 1) * 10}"
                    driver.get(next_url)
                    time.sleep(random.uniform(5, 8))
                    close_popups(driver)
 
                    # Check if Indeed redirected us (e.g. login wall)
                    if not wait_for_cards(driver, timeout=10):
                        print("  ℹ️  No cards on next page — last page or blocked.")
                        break
                    print(f"  ➡️  Loaded page {page + 2}")
 
    except Exception as e:
        print(f"\nScraper error: {e}")
    finally:
        try:
            driver.quit()
        except:
            pass
 
    return all_jobs
 
 
# ─────────────────────────────────────────────────────────────────
# FAST WRAPPER  (used by job_scraper_service.py aggregate pipeline)
# ─────────────────────────────────────────────────────────────────

def scrape_indeed_fast(keyword: str, city: str, date_filter: str = "month") -> list[dict]:
    """
    Paginated Indeed scraper: up to 5 pages, normalised output.

    Strategy to avoid 403 / Human Verification:
      • Deep Scrape  — first 5 jobs on Page 1 only: visits each viewjob URL
                       to extract full description + skills.
      • Shallow Scrape — all remaining jobs (pages 1-5, jobs 6+): extracts
                         Title, Company, Location, Salary from the search
                         results HTML only — no detail page navigation.
                         Sets skills=[] to keep frontend/scoring safe.

    Volume targets:
      3days → ~80+ jobs   (3 pages)
      week  → ~120+ jobs  (4 pages)
      month → ~150+ jobs  (5 pages)
    """
    search_city = f"{city}, India" if city.lower().strip() in INDIAN_CITIES else city
    fromage = DATE_FILTER_MAP.get(date_filter.lower().strip(), 30)

    # Determine page count based on date_filter
    date_key = date_filter.lower().strip()
    if date_key in ("3days", "last 3 days"):
        max_pages = 3
    elif date_key in ("week", "last week"):
        max_pages = 4
    else:
        max_pages = 5

    driver = get_stealth_driver()
    jobs: list[dict] = []
    deep_done = False  # flag: deep scrape only runs once (first 5 of page 1)

    try:
        if not load_indeed_session(driver):
            print("  ⚠️  Indeed: no saved session — skipping")
            return []

        base_url = (
            f"https://in.indeed.com/jobs"
            f"?q={keyword.replace(' ', '+')}"
            f"&l={search_city.replace(' ', '+')}"
            f"&fromage={fromage}"
        )
        print(f"  🔎 Indeed base_url: {base_url}")
        driver.get(base_url)
        time.sleep(random.uniform(4, 6))
        close_popups(driver)

        if not wait_for_cards(driver):
            print("  ⚠️  Indeed: no cards found on page 1")
            return []

        for page in range(max_pages):
            page_url = base_url if page == 0 else f"{base_url}&start={page * 10}"
            print(f"  📄 Indeed page {page + 1}/{max_pages}")

            if page > 0:
                driver.get(page_url)
                # Reduced sleep for pagination pages
                time.sleep(random.uniform(1.0, 2.0))
                close_popups(driver)
                if not wait_for_cards(driver, timeout=10):
                    print(f"  ℹ️  Indeed: no cards on page {page + 1} — stopping pagination")
                    break

            human_scroll(driver)
            time.sleep(random.uniform(0.8, 1.5))

            stubs = collect_job_stubs(driver, city)
            if not stubs:
                print(f"  ⚠️  Indeed: no stubs on page {page + 1}")
                break

            print(f"       Stubs collected on page {page + 1}: {len(stubs)}")

            if page == 0 and not deep_done:
                # ── DEEP SCRAPE: first 5 jobs of page 1 ──────────────────
                deep_stubs   = stubs[:5]
                shallow_stubs = stubs[5:]
                deep_done = True

                print(f"       Deep scraping {len(deep_stubs)} jobs...")
                detailed = fetch_skills_for_stubs(driver, deep_stubs, page_url)

                for d in detailed:
                    skills_raw = d.get("Skills", [])
                    if isinstance(skills_raw, str):
                        skills_list = [
                            s.strip() for s in skills_raw.split(",")
                            if s.strip() and s.strip().lower() != "not listed"
                        ]
                    elif isinstance(skills_raw, list):
                        skills_list = [str(s).strip() for s in skills_raw if str(s).strip()]
                    else:
                        skills_list = []

                    jobs.append({
                        "source":          "Indeed",
                        "title":           d.get("Job_Title", ""),
                        "employer":        d.get("Company", "N/A"),
                        "location":        d.get("Location", city),
                        "salary":          d.get("Salary", "Not disclosed"),
                        "duration":        "N/A",
                        "status":          d.get("Status", "Active"),
                        "apply_link":      d.get("Link", ""),
                        "description":     "",
                        "skills":          skills_list,
                        "qualifications":  list(skills_list),
                        "employment_type": d.get("Job_Type", "Permanent"),
                        "posted_at":       datetime.now(timezone.utc).isoformat(),
                        "employer_logo":   "",
                    })

                # Remaining page-1 stubs go through shallow scrape below
                stubs_to_shallow = shallow_stubs
            else:
                # All stubs on pages 2-5 are shallow
                stubs_to_shallow = stubs

            # ── SHALLOW SCRAPE: no detail page navigation ─────────────────
            for stub in stubs_to_shallow:
                jobs.append({
                    "source":          "Indeed",
                    "title":           stub.get("Job_Title", ""),
                    "employer":        stub.get("Company", "N/A"),
                    "location":        stub.get("Location", city),
                    "salary":          stub.get("Salary", "Not disclosed"),
                    "duration":        "N/A",
                    "status":          stub.get("Status", "Active"),
                    "apply_link":      stub.get("Link", ""),
                    "description":     "",
                    "skills":          [],   # empty list — safe for frontend/scoring
                    "qualifications":  [],
                    "employment_type": stub.get("Job_Type", "Permanent"),
                    "posted_at":       datetime.now(timezone.utc).isoformat(),
                    "employer_logo":   "",
                })

            print(f"       Indeed running total after page {page + 1}: {len(jobs)}")

            # Reduced inter-page sleep
            if page < max_pages - 1:
                time.sleep(random.uniform(1.0, 2.0))

    except Exception as exc:
        print(f"  ❌ Indeed fast scraper error: {exc}")
    finally:
        try:
            driver.quit()
        except Exception:
            pass

    print(f"  ✅ Indeed → {len(jobs)} jobs")
    return jobs


if __name__ == "__main__":
    job_title  = input("Job Role (e.g. Data Science): ").strip()
    city_input = input("Cities (comma-separated, e.g. Mumbai,Bangalore): ").strip()
 
    cities         = [c.strip() for c in city_input.split(",")]
    pages_per_city = 3
 
    data = get_indeed_data(job_title, cities, pages_per_city)
 
    if data:
        df = pd.DataFrame(data)
        df.drop_duplicates(subset=["Link"], inplace=True)
        df.reset_index(drop=True, inplace=True)
 
        filename = f"indeed_{job_title.replace(' ', '_')}_{len(df)}_jobs.csv"
        df.to_csv(filename, index=False, encoding="utf-8-sig")
 
        print(f"\n{'='*55}")
        print(f"✅ Saved {len(df)} jobs to '{filename}'")
        print(f"{'='*55}")
        print(df[["Job_Title", "Company", "Salary", "Status", "Skills"]].to_string())
    else:
        print("\n❌ No jobs collected.")





