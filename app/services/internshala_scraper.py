import time
import re
import json
import requests
from concurrent.futures import ThreadPoolExecutor
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from fake_useragent import UserAgent
from bs4 import BeautifulSoup

def get_stealth_driver():
    ua = UserAgent()
    options = Options()
    options.add_argument(f'user-agent={ua.random}')
    options.add_argument('--headless=new') # Headless is faster for parallel scraping
    options.add_argument('--no-sandbox')            # <--- ADD THIS
    options.add_argument('--disable-dev-shm-usage')
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    
    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()), 
        options=options
    )
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    return driver

def fetch_job_details(job_data):
    start_time = time.time()
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(job_data['detail_url'], headers=headers, timeout=10)

        soup = BeautifulSoup(res.text, 'html.parser')

        # ✅ BEST: JSON extraction
        json_script = soup.find('script', type='application/ld+json')

        skills = []
        if json_script:
            data = json.loads(json_script.string)
            if 'skills' in data:
                skills = [s.strip() for s in data['skills'].split(',')]

        job_data['skills'] = skills

    except Exception as e:
        print(f"Error: {e}")
        job_data['skills'] = []

    finally:
        end_time = time.time()
        print(f"⏱ {job_data['title']} took {end_time - start_time:.2f}s")

    return job_data

def start_scraping_parallel(keyword, location):
    main_driver = get_stealth_driver()
    search_url = f"https://internshala.com/internships/keywords-{keyword}/location-{location}"
    
    try:
        print(f"Fetching search results from: {search_url}")
        main_driver.get(search_url)
        time.sleep(4)

        # Scroll to bottom
        main_driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(2)

        soup = BeautifulSoup(main_driver.page_source, 'html.parser')
        cards = soup.find_all('div', class_=re.compile('individual_internship'))
        
        job_list = []
        for card in cards:
            if card.find_parent('a', class_='marketing_ads_card'): continue
            
            title_elem = card.select_one('a.job-title-href') or card.select_one('.job-internship-name a')
            company_elem = card.select_one('p.company-name')
            duration = "Not specified" 
            items = card.find_all('div', class_='row-1-item')
            if len(items) >= 3:
                duration = items[2].text.strip() if items[2] else "Not specified"
            status_elem = (
                card.select_one('.status-info ') or 
                card.select_one('.status-success ') or 
                card.select_one('.status-info ') or
                card.select_one('.status-inactive ') 
            )
            
            if title_elem and company_elem:
                job_list.append({
                    'title': title_elem.text.strip(),
                    'company': company_elem.text.strip(),
                    'detail_url': f"https://internshala.com{title_elem.get('href')}",
                    'stipend': card.select_one('span.stipend').text.strip() if card.select_one('span.stipend') else "N/A",
                    'duration': duration,
                    'status': status_elem.text.strip() if status_elem else "Not specified"
                })

        main_driver.quit()
        print(f"Found {len(job_list)} jobs. Starting parallel workers...\n")

        # PARALLEL EXECUTION: max_workers=5 means 5 browsers open at once
        results = []
        with ThreadPoolExecutor(max_workers=5) as executor:
            results = list(executor.map(fetch_job_details, job_list))

        # Final Output
        for job in results:
            print(f"🎯 {job['title']} | {job['company']} | Skills: {', '.join(job['skills'])} | Stipend: {job['stipend']} | Duration: {job['duration']} | Status: {job['status']}")

    except Exception as e:
        print(f"Main loop error: {e}")

if __name__ == "__main__":
    User = input("Enter the skill you want to search for (e.g., python): ")
    start_scraping_parallel(User, "india")


# ─────────────────────────────────────────────────────────────────
# Indian cities (for resilient location handling)
# ─────────────────────────────────────────────────────────────────
INDIAN_CITIES = {
    "mumbai", "delhi", "bangalore", "bengaluru", "hyderabad", "chennai",
    "pune", "kolkata", "ahmedabad", "jaipur", "surat", "lucknow",
    "noida", "gurugram", "gurgaon", "indore", "bhopal",
}


# ─────────────────────────────────────────────────────────────────
# FAST WRAPPER  (used by job_scraper_service.py aggregate pipeline)
# ─────────────────────────────────────────────────────────────────

def scrape_internshala_fast(keyword: str, city: str, date_filter: str = "month") -> list[dict]:
    """
    Paginated Internshala scraper: up to 3 pages, normalised output.
    Card limit increased to 60 to contribute significantly to the 150-job goal.
    Returns list of dicts matching the unified job schema.
    """
    import json as _json

    search_city = f"{city}, India" if city.lower().strip() in INDIAN_CITIES else city

    # Internshala uses /page-N suffix for pagination
    base_search_url = (
        f"https://internshala.com/internships/"
        f"keywords-{keyword.replace(' ', '-')}/"
        f"location-{search_city.replace(' ', '-')}"
    )

    # get_stealth_driver already uses --headless; confirmed here
    main_driver = get_stealth_driver()
    all_job_list: list[dict] = []
    jobs: list[dict] = []

    try:
        for page_num in range(1, 4):  # pages 1, 2, 3
            if page_num == 1:
                page_url = base_search_url
            else:
                page_url = f"{base_search_url}/page-{page_num}"

            print(f"  Internshala: fetching page {page_num} → {page_url}")
            main_driver.get(page_url)
            time.sleep(4)
            main_driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)

            soup = BeautifulSoup(main_driver.page_source, 'html.parser')
            cards = soup.find_all('div', class_=re.compile('individual_internship'))

            page_jobs = 0
            for card in cards:
                if card.find_parent('a', class_='marketing_ads_card'):
                    continue

                title_elem = card.select_one('a.job-title-href') or card.select_one('.job-internship-name a')
                company_elem = card.select_one('p.company-name')
                if not title_elem or not company_elem:
                    continue

                duration = "Not specified"
                items = card.find_all('div', class_='row-1-item')
                if len(items) >= 3:
                    duration = items[2].text.strip() if items[2] else "Not specified"

                status_elem = (
                    card.select_one('.status-info span') or
                    card.select_one('.status-success span') or
                    card.select_one('.status span') or
                    card.select_one('.status-inactive span')
                )

                href = title_elem.get('href', '')
                detail_url = f"https://internshala.com{href}" if href.startswith('/') else href

                all_job_list.append({
                    'title':      title_elem.text.strip(),
                    'company':    company_elem.text.strip(),
                    'detail_url': detail_url,
                    'stipend':    card.select_one('span.stipend').text.strip() if card.select_one('span.stipend') else "N/A",
                    'duration':   duration,
                    'status':     status_elem.text.strip() if status_elem else "Active",
                })
                page_jobs += 1

                # Cap total at 60 across all pages
                if len(all_job_list) >= 60:
                    break

            print(f"       Internshala page {page_num}: {page_jobs} cards | running total: {len(all_job_list)}")

            if len(all_job_list) >= 60:
                break

            # No page found (redirected back to page 1 or empty)
            if page_jobs == 0:
                print(f"  ℹ️  Internshala: no cards on page {page_num} — stopping pagination")
                break

        main_driver.quit()
        main_driver = None

        print(f"  Internshala: {len(all_job_list)} cards collected before detail fetch")

        # Parallel detail fetching for all collected jobs
        results = []
        if all_job_list:
            with ThreadPoolExecutor(max_workers=5) as executor:
                results = list(executor.map(fetch_job_details, all_job_list))

        print(f"  Internshala: {len(results)} detail pages fetched")

        # Normalise to unified schema
        for d in results:
            jobs.append({
                "source":          "Internshala",
                "title":           d.get("title", ""),
                "employer":        d.get("company", "N/A"),
                "location":        city,
                "salary":          d.get("stipend", "N/A"),
                "duration":        d.get("duration", "N/A"),
                "status":          d.get("status", "Active"),
                "apply_link":      d.get("detail_url", ""),
                "description":     "",
                "skills":          d.get("skills", []),
                "employment_type": "Internship",
                "posted_at":       "",
                "employer_logo":   "",
            })

    except Exception as exc:
        print(f"  ❌ Internshala fast scraper error: {exc}")
    finally:
        if main_driver:
            try:
                main_driver.quit()
            except Exception:
                pass

    print(f"  ✅ Internshala → {len(jobs)} jobs")
    return jobs


# @app.route('/internships/keywords-<skill>')
# def show_internships(skill):
#     # The variable 'skill' becomes "python"
#     jobs = database.find_jobs_by_skill(skill)
#     return render_template('jobs_list.html', jobs=jobs, search_term=skill)