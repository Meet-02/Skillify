import time
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from fake_useragent import UserAgent
from bs4 import BeautifulSoup

def get_stealth_driver():
    ua = UserAgent()
    # 1. Generate a random identity
    user_agent = ua.random 
    
    options = Options()
    # 2. IMPORTANT: Keep headless=False so you can SEE if you are being blocked
    options.add_argument(f'user-agent={user_agent}')
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    
    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()), 
        options=options
    )
    
    # 3. Hidden script to stop the site from knowing it's a bot
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    return driver

def start_scraping(keyword, location):
    driver = get_stealth_driver()
    # Format the URL for Internshala
    search_url = f"https://internshala.com/internships/keywords-{keyword}/location-{location}"
    
    try:
        print(f"Opening: {search_url}")
        driver.get(search_url)
        
        # 4. Give the page 5 seconds to load JS
        time.sleep(5) 
        
        # 5. Hand off the HTML to BeautifulSoup (much faster than Selenium for searching)
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        
        # 6. YOUR JOB: Find the container that holds all jobs
        # Look for the <div> class that repeats for every job card
        job_cards = soup.find_all('div', class_='container-fluid individual_internship') 
        
        print(f"Found {len(job_cards)} jobs!")
        
        for card in job_cards:
            title = card.find('div', class_='main_heading').text.strip()
            company = card.find('p', class_='company_name').text.strip()
            print(f"Matching Job: {title} at {company}")

    except Exception as e:
        print(f"Error occurred: {e}")
    finally:
        driver.quit()

if __name__ == "__main__":
    # Test it here
    start_scraping("python", "mumbai")