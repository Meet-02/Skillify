import asyncio
import os
import pymysql
from dotenv import load_dotenv
from app.services.internshala_scraper import scrape_internshala_fast
from app.services.indeed_scraper import scrape_indeed_fast

# Load the variables from the .env file
load_dotenv()

def save_jobs_to_tidb(jobs, source):
    # Debug print to ensure .env is loading!
    print(f"Connecting to DB: {os.getenv('TIDB_HOST')} as {os.getenv('TIDB_USER')}")

    # Connect to your TiDB database
    connection = pymysql.connect(
        host=os.getenv('TIDB_HOST'),
        user=os.getenv('TIDB_USER'),
        password=os.getenv('TIDB_PASS'),
        database=os.getenv('TIDB_NAME'),
        port=4000,                     # <--- MAKE SURE THIS IS EXACTLY 4000
        ssl={'ssl_mode': 'PREFERRED'}
    )
    
    with connection.cursor() as cursor:
        for job in jobs:
            sql = """
            INSERT IGNORE INTO jobs (source, title, company, location, link, skills)
            VALUES (%s, %s, %s, %s, %s, %s)
            """
            skills_str = ", ".join(job.get('skills', []))
            
            cursor.execute(sql, (
                job.get('source', source),
                job.get('title', ''),
                job.get('employer', ''),
                job.get('location', ''),
                job.get('apply_link', ''),
                skills_str
            ))
    connection.commit()
    connection.close()
    print(f"✅ Saved {len(jobs)} {source} jobs to TiDB.")

# ... rest of the code remains the same ...

if __name__ == "__main__":
    print("🚀 Starting Background Scrapers...")
    
    # Scrape for standard tech roles
    keywords = ["Software Engineer", "Data Analyst", "Frontend Developer"]
    cities = ["Mumbai", "Bangalore"]
    
    for city in cities:
        for kw in keywords:
            print(f"Scraping Indeed for {kw}...")
            indeed_jobs = scrape_indeed_fast(kw, city, "3days")
            if indeed_jobs:
                save_jobs_to_tidb(indeed_jobs, "Indeed")
                
            print(f"Scraping Internshala for {kw}...")
            internshala_jobs = scrape_internshala_fast(kw, city, "3days")
            if internshala_jobs:
                save_jobs_to_tidb(internshala_jobs, "Internshala")
            
    print("🎉 Background scraping complete!")