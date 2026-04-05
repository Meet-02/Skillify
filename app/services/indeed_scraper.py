import time
import os
from pathlib import Path
import re
import random
import pickle
import json
import requests
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
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

def fetch_indeed_details(job_data):
    """
    Fast parallel fetcher using requests. 
    Indeed often blocks simple requests, so we use headers.
    """
    start_time = time.time()
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://in.indeed.com/"
        }
        # Indeed detail pages are usually reachable via this URL pattern
        res = requests.get(job_data['Link'], headers=headers, timeout=10)
        
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, 'html.parser')
            pane_el = soup.select_one('#jobDescriptionText')
            if pane_el:
                jd_text = pane_el.get_text(separator=" ", strip=True)
                job_data['Skills'] = extract_skills(jd_text)
            else:
                job_data['Skills'] = []
        else:
            job_data['Skills'] = []

    except Exception as e:
        job_data['Skills'] = []
    
    finally:
        elapsed = time.time() - start_time
        print(f"⏱  {job_data['Job_Title'][:30]} took {elapsed:.2f}s")
    
    return job_data

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
TITLE_SELECTOR      = 'h2.jobTitle a'
COMPANY_SELECTOR    = '[data-testid="company-name"]'
LOCATION_SELECTOR   = '[data-testid="text-location"]'
SALARY_SELECTOR     = '.salary-snippet-container, .estimated-salary-container'
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
 
 
def get_stealth_driver():
    options = uc.ChromeOptions()
    if not os.path.exists(USER_DATA_DIR):
        os.makedirs(USER_DATA_DIR)
    
    options.add_argument(f"--user-data-dir={USER_DATA_DIR}")
    
    # 1. REMOVED Headless so you can see if a Captcha appears
    # 2. Keep these for stability
    options.add_argument("--no-first-run")
    options.add_argument("--no-service-autorun")
    options.add_argument("--password-store=basic")
    
    # 3. Use a realistic User-Agent to help bypass blocks
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")
    prefs = {
        "profile.managed_default_content_settings.images": 2,
        "profile.managed_default_content_settings.stylesheets": 2,
        "profile.managed_default_content_settings.fonts": 2
    }
    options.add_experimental_option("prefs", prefs)
    # 4. use_subprocess=True is good for FastAPI threading
    return uc.Chrome(options=options, version_main=146, use_subprocess=True)

# def get_stealth_driver():
#     options = uc.ChromeOptions()
#     if not os.path.exists(USER_DATA_DIR):
#         os.makedirs(USER_DATA_DIR)
    
#     options.add_argument(f"--user-data-dir={USER_DATA_DIR}")
    
#     # --- ADD HEADLESS MODE HERE ---
#     options.add_argument("--headless=new")  # Use "--headless=new" if using latest Chrome
#     options.add_argument("--no-sandbox")            # <--- ADD THIS
#     options.add_argument("--disable-dev-shm-usage")  # <--- ADD THIS
#     options.add_argument("--disable-gpu")
#     options.add_argument("--window-size=1920,1080")
#     # ------------------------------

#     # Fix for threading: prevent multiple instances from crashing
#     options.add_argument("--no-first-run")
#     options.add_argument("--no-service-autorun")
#     options.add_argument("--password-store=basic")
#     options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")
    
#     return uc.Chrome(options=options,version_main=146,use_subprocess=True)
#     return driver

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
    soup = BeautifulSoup(driver.page_source, 'html.parser')
    cards = soup.select(CARD_SELECTOR)
    print(f"   → Found {len(cards)} cards on results page.")

    stubs = []
    seen_jk = set()

    for card in cards:
        try:
            # 1. Extract Title and ID
            title_el = card.select_one(TITLE_SELECTOR)
            if not title_el: continue
            
            jk_id = title_el.get('data-jk') or title_el.get('id', '').replace('job_', '')
            if not jk_id or jk_id in seen_jk: continue
            seen_jk.add(jk_id)

            title_text = title_el.get_text(strip=True)

            # 2. Extract Company
            company_el = card.select_one(COMPANY_SELECTOR)
            company = company_el.get_text(strip=True) if company_el else "N/A"

            # 3. Extract Location
            location_el = card.select_one(LOCATION_SELECTOR)
            location = location_el.get_text(strip=True) if location_el else city

            # 4. Extract Salary (Using the new class found in your HTML)
            salary_el = card.select_one('div.salary-snippet-container') or card.select_one('div.metadata.salary-snippet-container')
            salary = salary_el.get_text(strip=True) if salary_el else "Not disclosed"

            stubs.append({
                "jk_id": jk_id,
                "Job_Title": title_text,
                "Company": company,
                "City": city,
                "Location": location,
                "Salary": salary,
                "Job_Type": "N/A",
                "Status": "Active",
                "Link": f"https://in.indeed.com/viewjob?jk={jk_id}",
            })
        except Exception as e:
            print(f"      ⚠️ Error parsing card: {e}")
            continue

    return stubs
 
 
# ─────────────────────────────────────────────────────────────
# STEP 2 — Visit each job's detail page directly, scrape skills
# Never uses driver.back() — always navigates forward to known URLs
# ─────────────────────────────────────────────────────────────
 
from concurrent.futures import ThreadPoolExecutor

def fetch_stubs_parallel(stubs):
    """
    Fetches details for all stubs concurrently using background requests.
    No browser navigation = No waiting for rendering.
    """
    print(f"  🚀 Starting parallel skill extraction for {len(stubs)} jobs...")
    
    # We use 10 workers to fetch 10 jobs at once
    with ThreadPoolExecutor(max_workers=10) as executor:
        # This calls the fast 'fetch_indeed_details' function you already have
        results = list(executor.map(fetch_indeed_details, stubs))
    
    # Clean up data for the final list
    final_jobs = []
    for job in results:
        job_copy = dict(job)
        if "jk_id" in job_copy:
            job_copy.pop("jk_id")
        
        # Ensure Skills is a string for your existing CSV/Logic
        if isinstance(job_copy.get("Skills"), list):
            job_copy["Skills"] = ", ".join(job_copy["Skills"])
            
        final_jobs.append(job_copy)
        
    return final_jobs
 
 
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
 

def fetch_skills_for_stubs_parallel(stubs):
    """
    Fetches details for all stubs concurrently using background requests.
    """
    print(f"  🚀 Starting parallel skill extraction for {len(stubs)} jobs...")
    
    with ThreadPoolExecutor(max_workers=10) as executor:
        # This calls the 'fetch_indeed_details' function already in your file
        results = list(executor.map(fetch_indeed_details, stubs))
    
    final_jobs = []
    for job in results:
        job_copy = dict(job)
        if "jk_id" in job_copy:
            job_copy.pop("jk_id")
        
        # Format skills for the scoring model
        if isinstance(job_copy.get("Skills"), list):
            job_copy["Skills"] = ", ".join(job_copy["Skills"])
            
        final_jobs.append(job_copy)
        
    return final_jobs
 
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
    deep_done = False 

    try:
        if not load_indeed_session(driver):
            return []

        base_url = f"https://in.indeed.com/jobs?q={keyword.replace(' ', '+')}&l={search_city.replace(' ', '+')}&fromage={fromage}"
        driver.get(base_url)
        time.sleep(8) # Wait for the slow two-pane layout
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
                deep_stubs = stubs[:10] # Or increase this to 10-15 since it's now fast!
                shallow_stubs = stubs[5:]
                deep_done = True

                print(f"       Deep scraping {len(deep_stubs)} jobs...")
                detailed = fetch_skills_for_stubs_parallel(deep_stubs)

                for d in detailed:
                    jobs.append({
                        "source": "Indeed",
                        "title": d.get("Job_Title", ""),
                        "employer": d.get("Company", "N/A"),
                        "location": d.get("Location", city),
                        "salary": d.get("Salary", "Not disclosed"),
                        "duration": "N/A",
                        "status": "Active",
                        "apply_link": d.get("Link", ""),
                        "description": "",
                        "skills": d.get("Skills", []),
                        "qualifications": d.get("Skills", []),
                        "employment_type": d.get("Job_Type", "Permanent"),
                        "posted_at": datetime.now(timezone.utc).isoformat(),
                        "employer_logo": "",
                    })
                stubs_to_shallow = shallow_stubs
            else:
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





