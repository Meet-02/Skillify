import shutil
import asyncio
from pathlib import Path
from datetime import datetime
import os
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Form, Depends, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware
import httpx
import asyncio
from app.database import engine, get_db
from app.models import Base, Login
from app.core.utils import hash_password, verify_password
from app.services.resume_parser import extract_text_from_resume
from app.services.skill_extractor import extract_skills
from app.services.match_service import run_matching_pipeline
from app.services.bio_generator import generate_bio
from app.services.resume_tips import generate_resume_tips
from app.routes import auth, match
from experiment.alpha_dataset import DATASET as JOB_DATASET
 
load_dotenv()
 
ADZUNA_APP_ID  = os.getenv("ADZUNA_APP_ID")
ADZUNA_KEY     = os.getenv("ADZUNA_KEY")
ADZUNA_COUNTRY = os.getenv("ADZUNA_COUNTRY", "in")
JSEARCH_API_KEY = os.getenv("JSEARCH_API_KEY")
 
SKILLS_TO_TRACK = [
    "React", "Python", "TypeScript", "AWS", "Docker",
    "JavaScript", "AI", "ML", "Data Science", "Azure",
    "GCP", "Lambda", "MongoDB", "Google Cloud",       # ← comma added here
    "Kubernetes", "TensorFlow", "Node.js", "Go", "Rust",
    "SQL", "Figma", "Java", "C++", "C", "Linux", "Bash",
]
 
PROJECT_ROOT = Path(__file__).resolve().parent.parent
 
app = FastAPI(title="Skillify API")
 
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SESSION_SECRET", "skillify-dev-secret-change-in-prod"),
)
 
try:
    Base.metadata.create_all(bind=engine)
except Exception as _db_err:
    print(f"❌ Database init failed: {_db_err}")
    raise
 
static_dir    = PROJECT_ROOT / "static"
templates_dir = PROJECT_ROOT / "templates"
 
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
templates = Jinja2Templates(directory=str(templates_dir))
 
app.include_router(auth.router,  prefix="/auth")
app.include_router(match.router, prefix="/match")
 
 
# ─────────────────────────────────────────────────────────────────────────────
# Landing / Auth pages
# ─────────────────────────────────────────────────────────────────────────────
 
@app.get("/")
def landing_page(request: Request):
    return templates.TemplateResponse("landing-page.html", {"request": request})
 
 
@app.get("/register")
def register_page(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})
 
 
@app.post("/register")
def register_user(
    request:  Request,
    username: str     = Form(...),
    email:    str     = Form(...),
    password: str     = Form(...),
    db:       Session = Depends(get_db),
):
    from app.models import Login, Users
 
    existing = db.query(Login).filter(Login.email == email).first()
    if existing:
        return templates.TemplateResponse(
            "register.html",
            {"request": request, "error": "Email already registered"},
        )
 
    hashed = hash_password(password)
 
    db.add(Login(
        username=username,
        email=email,
        password_hash=hashed,
        created_at=datetime.utcnow(),
    ))
    db.commit()
 
    db.add(Users(
        name=username,
        email=email,
        password_hash=hashed,
        role="student",
        created_at=datetime.utcnow(),
    ))
    db.commit()
 
    return RedirectResponse("/login", status_code=303)
 
 
@app.get("/login")
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})
 
 
@app.post("/login")
def login_user(
    request:  Request,
    email:    str     = Form(...),
    password: str     = Form(...),
    db:       Session = Depends(get_db),
):
    from app.models import Login, Users, UserSkills
 
    user = db.query(Login).filter(Login.email == email).first()
    if not user:
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "User not found"},
        )
 
    if not verify_password(password, user.password_hash):
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Invalid password"},
        )
 
    profile_user = db.query(Users).filter(Users.email == email).first()
    if not profile_user:
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "User profile missing"},
        )
 
    request.session["user_id"] = profile_user.user_id
 
    skills_exist = db.query(UserSkills).filter(
        UserSkills.user_id == profile_user.user_id
    ).first()
 
    return RedirectResponse(
        "/dashboard" if skills_exist else "/upload-resume",
        status_code=303,
    )
 
 
@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)
 
 
# ─────────────────────────────────────────────────────────────────────────────
# Profile
# ─────────────────────────────────────────────────────────────────────────────
 
@app.get("/profile")
def profile_page(request: Request, db: Session = Depends(get_db)):
    from app.models import Users, UserProfile, UserSkills, Skills
 
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse("/login", status_code=303)
 
    user = db.query(Users).filter(Users.user_id == user_id).first()
    if not user:
        return RedirectResponse("/login", status_code=303)
 
    profile = db.query(UserProfile).filter(UserProfile.user_id == user_id).first()
 
    skills = (
        db.query(Skills.skill_name, Skills.skill_type)
        .join(UserSkills, Skills.skill_id == UserSkills.skill_id)
        .filter(UserSkills.user_id == user_id)
        .all()
    )
    skill_list   = [s[0] for s in skills]
    skills_count = len(skill_list)
 
 
    resume_uploaded = bool(user.resume_uploaded) if user.resume_uploaded is not None \
                      else len(skill_list) > 0
 
 
    resume_filename = None
    if resume_uploaded:
        upload_dir = static_dir / "resumes"
        if upload_dir.exists():
            prefix     = f"{user_id}_"
            user_files = sorted(
                [p for p in upload_dir.iterdir()
                 if p.is_file() and p.name.startswith(prefix)],
                key=lambda p: p.stat().st_mtime,
            )
            if user_files:
                name_parts      = user_files[-1].name.split("_", 1)
                resume_filename = name_parts[1] if len(name_parts) == 2 \
                                  else user_files[-1].name
 
    matched_services  = []
    no_skills_message = None
 
    if skill_list:
        user_profile = {"technical": [], "tools": [], "soft": []}
        for skill_name, skill_type in skills:
            sk_t   = (skill_type or "").lower()
            bucket = ("tools"     if sk_t in ("tool", "tools") else
                      "soft"      if sk_t == "soft" else
                      "technical")
            user_profile[bucket].append(skill_name)
 
        if not any(user_profile.values()):
            user_profile["technical"] = skill_list
 
        resume_text = " ".join(skill_list)
 
        for job in JOB_DATASET:
            result = run_matching_pipeline(
                user_profile=user_profile,
                job_profile=job["job_profile"],
                resume_text=resume_text,
                job_text=job["job_title"],
            )
            matched_services.append({
                "job_title":         job["job_title"],
                "final_match_score": result["final_match_score"],
                "structured_score":  result["structured_score"],
                "semantic_score":    result["semantic_score"],
                "gap_severity":      result["gap_severity"],
            })
 
        matched_services.sort(key=lambda s: s["final_match_score"], reverse=True)
    else:
        no_skills_message = "Upload resume to see recommendations"
 
    return templates.TemplateResponse("profile.html", {
        "request":          request,
        "user":             user,
        "profile":          profile,
        "skills":           skill_list,
        "skills_count":     skills_count,
        "resume_uploaded":  resume_uploaded,
        "resume_filename":  resume_filename,
        "matched_services": matched_services,
        "no_skills_message": no_skills_message,
        "resume_tips":      request.session.get("resume_tips", []),
    })
 
 
@app.post("/profile")
def update_profile(
    request:          Request,
    phone:            str     = Form(None),
    bio:              str     = Form(None),
    education:        str     = Form(None),
    experience_level: str     = Form(None),
    domain_interest:  str     = Form(None),
    db:               Session = Depends(get_db),
):
    from app.models import Users, UserProfile
 
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse("/login", status_code=303)
 
    user = db.query(Users).filter(Users.user_id == user_id).first()
    if not user:
        return RedirectResponse("/login", status_code=303)
 
    if phone and phone.strip():
        user.phone = phone.strip()
    if bio and bio.strip():
        user.bio = bio.strip()
 
    profile = db.query(UserProfile).filter(UserProfile.user_id == user_id).first()
    if not profile:
        profile = UserProfile(user_id=user_id)
        db.add(profile)
 
    if education and education.strip():
        profile.education = education.strip()
    if experience_level and experience_level.strip():
        profile.experience_level = experience_level.strip()
    if domain_interest and domain_interest.strip():
        profile.domain_interest = domain_interest.strip()
 
    score = sum([
        20 if user.phone          else 0,
        20 if user.bio            else 0,
        20 if profile.education   else 0,
        20 if profile.experience_level else 0,
        20 if profile.domain_interest  else 0,
    ])
    profile.profile_completion_score = score
    db.commit()
 
    try:
        from app.models import UserSkills, Skills
        skills_raw = (
            db.query(Skills.skill_name, Skills.skill_type)
            .join(UserSkills, Skills.skill_id == UserSkills.skill_id)
            .filter(UserSkills.user_id == user_id)
            .all()
        )
        skill_list = [{"skill_name": s[0], "skill_type": s[1]} for s in skills_raw]
        if skill_list:
            tips = generate_resume_tips(skill_list, {
                "experience_level": profile.experience_level,
                "domain_interest":  profile.domain_interest,
            })
            request.session["resume_tips"] = tips
    except Exception as e:
        print(f"Tips refresh error: {e}")
 
    return RedirectResponse("/profile", status_code=303)
 
 
# ─────────────────────────────────────────────────────────────────────────────
# Resume upload
# ─────────────────────────────────────────────────────────────────────────────
 
@app.get("/upload-resume")
def upload_resume_page(request: Request):
    if not request.session.get("user_id"):
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse("upload_resume.html", {"request": request})
 
 
@app.post("/upload-resume")
async def upload_resume(
    request: Request,
    resume:  UploadFile = File(...),
    db:      Session    = Depends(get_db),
):
    from app.models import Users, Skills, UserSkills
 
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse("/login", status_code=303)
 
    user = db.query(Users).filter(Users.user_id == user_id).first()
    if not user:
        return RedirectResponse("/login", status_code=303)
 
 
    if resume.content_type not in ("application/pdf", "application/octet-stream"):
        return templates.TemplateResponse(
            "upload_resume.html",
            {"request": request, "error": "Only PDF files are supported."},
        )
 
    upload_dir = static_dir / "resumes"
    upload_dir.mkdir(parents=True, exist_ok=True)
    file_path = upload_dir / f"{user_id}_resume.pdf"
 
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(resume.file, buffer)
 
    try:
        text      = extract_text_from_resume(str(file_path))
        extracted = extract_skills(text)
 
        user.resume_filename = f"{user_id}_resume.pdf"
        user.resume_uploaded = True
 
        if not user.bio or not user.bio.strip():
            generated_bio = generate_bio(extracted)
            if generated_bio:
                user.bio = generated_bio.strip()
 
        db.commit()
 
    except Exception as e:
        print(f"Resume Error: {e}")
        return templates.TemplateResponse(
            "upload_resume.html",
            {"request": request, "error": "Resume parsing failed"},
        )
 
    # roll back to keep existing skills if the insert loop fails mid-way.
    try:
        db.query(UserSkills).filter(
            UserSkills.user_id == user_id,
            UserSkills.source  == "resume",
        ).delete()
        db.flush()   # apply delete within the open transaction
 
        inserted_skill_ids: set[int] = set()
 
        for skill in extracted:
            skill_name = skill["skill_name"]
 
            skill_obj = db.query(Skills).filter(
                Skills.skill_name == skill_name
            ).first()
 
            if not skill_obj:
                skill_obj = Skills(
                    skill_name=skill_name,
                    skill_type=skill["skill_type"],
                )
                db.add(skill_obj)
                db.flush()   # get skill_id without committing
 
            if skill_obj.skill_id in inserted_skill_ids:
                continue    # skip duplicate within this upload
            inserted_skill_ids.add(skill_obj.skill_id)
 
            db.add(UserSkills(
                user_id=user_id,
                skill_id=skill_obj.skill_id,
                proficiency_level="beginner",
                source="resume",
            ))
 
        db.commit()
 
    except Exception as e:
        db.rollback()
        print(f"Skills insert error: {e}")
        return templates.TemplateResponse(
            "upload_resume.html",
            {"request": request, "error": "Failed to save skills — please try again."},
        )
 
    try:
        tips = generate_resume_tips(extracted)
        request.session["resume_tips"] = tips
    except Exception as e:
        print(f"Tips generation error: {e}")
 
    return RedirectResponse("/dashboard", status_code=303)
 
 
# ─────────────────────────────────────────────────────────────────────────────
# Protected pages
# ─────────────────────────────────────────────────────────────────────────────
 
@app.get("/dashboard")
def dashboard(request: Request):
    if not request.session.get("user_id"):
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse("dashboard.html", {"request": request})
 
 
@app.get("/internships")
def internships_page(request: Request):
    if not request.session.get("user_id"):
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse("internship.html", {"request": request})
 
 
@app.get("/internship_list")
def internship_list_page(request: Request):
    if not request.session.get("user_id"):
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse("internship_list.html", {"request": request})
 
 
# ─────────────────────────────────────────────────────────────────────────────
# Market data API (Adzuna)
# ─────────────────────────────────────────────────────────────────────────────
 
@app.get("/api/market-data")
async def get_market_data():
    if not ADZUNA_APP_ID or not ADZUNA_KEY:
        print("❌ ERROR: ADZUNA_APP_ID / ADZUNA_KEY missing in .env")
        return []
 
    results = []
    async with httpx.AsyncClient(timeout=15) as client:
        tasks = [
            client.get(
                f"https://api.adzuna.com/v1/api/jobs/{ADZUNA_COUNTRY}/search/1",
                params={
                    "app_id":       ADZUNA_APP_ID,
                    "app_key":      ADZUNA_KEY,
                    "what":         skill,
                    "content-type": "application/json",
                },
            )
            for skill in SKILLS_TO_TRACK
        ]
 
        try:
            responses = await asyncio.gather(*tasks)
        except Exception as e:
            print(f"❌ Adzuna connection error: {e}")
            return []
 
        for skill, response in zip(SKILLS_TO_TRACK, responses):
            if response.status_code != 200:
                results.append({"name": skill, "jobs": 0, "salary": 0})
                continue
 
            data      = response.json()
            job_count = data.get("count", 0)
 
            if "mean" in data:
                avg_salary = data["mean"]
            else:
                total_salary   = 0
                salary_samples = 0
                for job in data.get("results", []):
                    if "salary_min" in job and "salary_max" in job:
                        total_salary   += (job["salary_min"] + job["salary_max"]) / 2
                        salary_samples += 1
                    elif "salary_min" in job:
                        total_salary   += job["salary_min"]
                        salary_samples += 1
                    elif "salary_max" in job:
                        total_salary   += job["salary_max"]
                        salary_samples += 1
                avg_salary = (total_salary / salary_samples) if salary_samples else 0
 
            results.append({"name": skill, "jobs": job_count, "salary": avg_salary})
 
    return results
 
 
 
INDIAN_CITIES = [
    "Mumbai", "Delhi", "Bangalore", "Hyderabad", "Chennai",
    "Pune", "Kolkata", "Ahmedabad", "Jaipur", "Surat",
    "Lucknow", "Noida", "Gurugram", "Indore", "Bhopal",
]
 
# ─────────────────────────────────────────────────────────────────────────────
#  JOB FETCH STRATEGY
#  ─────────────────────────────────────────────────────────────────────────────
#  Source priority (all run in PARALLEL with asyncio):
#    1. JSearch  (if JSEARCH_API_KEY set)  — best Indian results
#    2. Adzuna   (if ADZUNA_APP_ID set)    — key already in .env, 10k/month free
#
#  Page counts  →  raw jobs fetched before dedup:
#    3days : 10 pages × 2 queries × 2 sources  =  ~200-400 raw  →  90+ unique
#    week  : 15 pages × 2 queries × 2 sources  =  ~300-600 raw  →  140+ unique
#    month : 15 pages × 2 queries × 2 sources  =  ~300-600 raw  →  140+ unique
#
#  NO Selenium, NO web scraping — pure async HTTP, takes 3-6 seconds total.
# ─────────────────────────────────────────────────────────────────────────────
 
_PAGES_BY_FILTER: dict = {"3days": 10, "week": 15, "month": 15}
 
from concurrent.futures import ThreadPoolExecutor
_SCORE_EXECUTOR = ThreadPoolExecutor(max_workers=8)
 
# ── Domain → search keyword ───────────────────────────────────────────────────
DOMAIN_KEYWORDS: dict = {
    "":           "",
    # Tech
    "frontend":   "frontend developer",
    "backend":    "backend developer",
    "fullstack":  "full stack developer",
    "android":    "android developer",
    "ios":        "ios developer swift",
    "devops":     "devops cloud engineer",
    "data":       "data science analyst",
    "ml":         "machine learning AI engineer",
    "dataeng":    "data engineer ETL pipeline",
    "cyber":      "cybersecurity information security",
    "uiux":       "UI UX designer",
    "embedded":   "embedded systems IoT firmware",
    "blockchain": "blockchain web3 solidity",
    "qa":         "quality assurance software testing",
    "software":   "software engineer developer",
    "product":    "product manager",
    # Non-tech
    "marketing":  "digital marketing",
    "finance":    "finance accounting",
    "hr":         "human resources HR recruiter",
    "sales":      "sales business development",
    "operations": "operations supply chain",
    "content":    "content writing copywriting",
    "design":     "graphic design creative",
}
 
# ── Domain title-filter keywords (module-level, evaluated once) ───────────────
DOMAIN_TITLE_KEYWORDS: dict = {
    "frontend":   {"frontend", "front-end", "react", "angular", "vue",
                   "javascript", "html", "css", "ui developer", "web developer"},
    "backend":    {"backend", "back-end", "nodejs", "node.js", "django",
                   "flask", "spring", "java developer", "python developer",
                   "api developer", "server", "php"},
    "fullstack":  {"full stack", "fullstack", "full-stack", "mern", "mean"},
    "android":    {"android", "kotlin", "mobile app", "mobile developer"},
    "ios":        {"ios", "swift", "iphone", "apple developer"},
    "devops":     {"devops", "cloud", "aws", "azure", "gcp", "kubernetes",
                   "docker", "sre", "site reliability", "infrastructure"},
    "data":       {"data science", "data scientist", "data analyst", "analytics",
                   "business analyst", "machine learning", "python analyst"},
    "ml":         {"machine learning", "ml engineer", "ai engineer",
                   "deep learning", "nlp", "data scientist", "artificial intelligence"},
    "dataeng":    {"data engineer", "etl", "pipeline", "spark", "airflow",
                   "bigdata", "big data", "hadoop", "databricks"},
    "uiux":       {"ui", "ux", "ui/ux", "product designer", "interaction design",
                   "user experience", "figma", "visual design"},
    "qa":         {"qa", "quality assurance", "testing", "tester", "sdet",
                   "automation engineer", "test engineer"},
    "cyber":      {"cyber", "cybersecurity", "security analyst", "penetration",
                   "ethical hacking", "infosec", "soc analyst"},
    "product":    {"product manager", "product management", "pm ", "apm",
                   "associate product", "product owner"},
    "embedded":   {"embedded", "iot", "firmware", "arduino", "raspberry",
                   "rtos", "hardware"},
    "blockchain": {"blockchain", "web3", "solidity", "smart contract",
                   "ethereum", "defi", "nft", "crypto"},
    "software":   {"software engineer", "software developer", "sde", "swe",
                   "programmer", "developer", "engineer"},
    "marketing":  {"marketing", "digital marketing", "seo", "social media",
                   "growth", "brand", "performance marketing"},
    "finance":    {"finance", "financial", "accounting", "accountant",
                   "ca intern", "cfa", "investment", "banking"},
    "hr":         {"hr", "human resources", "recruitment", "recruiter",
                   "talent acquisition", "people operations"},
    "sales":      {"sales", "business development", "bd intern",
                   "account manager", "client", "pre-sales"},
    "operations": {"operations", "ops", "supply chain", "logistics",
                   "procurement", "inventory"},
    "content":    {"content", "writing", "copywriting", "editorial",
                   "journalist", "blogger", "media"},
    "design":     {"graphic design", "graphic designer", "visual design",
                   "creative", "illustrator", "photoshop"},
}
 
 
# ─────────────────────────────────────────────────────────────────────────────
#  SOURCE 1 — JSearch (RapidAPI)
# ─────────────────────────────────────────────────────────────────────────────
 
async def _fetch_jsearch_page(
    client: httpx.AsyncClient,
    query: str,
    page: int,
    date_posted: str,
) -> list:
    """Fetch one JSearch result page. Returns raw JSearch job list on success."""
    url = (
        "https://jsearch.p.rapidapi.com/search"
        f"?query={query.replace(' ', '%20')}"
        f"&page={page}&num_pages=1&date_posted={date_posted}"
    )
    try:
        resp = await client.get(url, headers={
            "x-rapidapi-key":  JSEARCH_API_KEY,
            "x-rapidapi-host": "jsearch.p.rapidapi.com",
        }, timeout=20)
        if resp.status_code == 200:
            return resp.json().get("data", [])
        print(f"JSearch p{page} HTTP {resp.status_code}")
    except Exception as exc:
        print(f"JSearch p{page} error: {exc}")
    return []
 
 
def _normalise_jsearch(job: dict, city: str) -> dict:
    """Convert a raw JSearch job dict to the common internal format."""
    highlights     = job.get("job_highlights") or {}
    qualifications = highlights.get("Qualifications") or []
    return {
        # fields used by _score_job and the frontend
        "job_title":                    job.get("job_title")           or "",
        "employer_name":                job.get("employer_name")        or "",
        "employer_logo":                job.get("employer_logo")        or "",
        "job_city":                     job.get("job_city") or job.get("job_state") or city,
        "job_apply_link":               job.get("job_apply_link")       or "#",
        "job_description":              job.get("job_description")     or "",
        "job_posted_at_datetime_utc":   job.get("job_posted_at_datetime_utc") or "",
        "job_employment_type":          job.get("job_employment_type")  or "Internship",
        "job_publisher":                job.get("job_publisher")        or "JSearch",
        "qualifications":               [str(q) for q in qualifications[:5] if q],
        "_source":                      "jsearch",
    }
 
 
# ─────────────────────────────────────────────────────────────────────────────
#  SOURCE 2 — Adzuna (already configured in .env, 10 000 free calls/month)
# ─────────────────────────────────────────────────────────────────────────────
 
async def _fetch_adzuna_page(
    client: httpx.AsyncClient,
    query: str,
    city: str,
    page: int,
) -> list:
    """Fetch one Adzuna result page. Returns normalised job dicts."""
    if not ADZUNA_APP_ID or not ADZUNA_KEY:
        return []
    try:
        resp = await client.get(
            f"https://api.adzuna.com/v1/api/jobs/{ADZUNA_COUNTRY}/search/{page}",
            params={
                "app_id":       ADZUNA_APP_ID,
                "app_key":      ADZUNA_KEY,
                "what":         f"{query} internship",
                "where":        city,
                "results_per_page": 10,
                "content-type": "application/json",
            },
            timeout=20,
        )
        if resp.status_code == 200:
            raw = resp.json().get("results", [])
            return [_normalise_adzuna(j, city) for j in raw]
        print(f"Adzuna p{page} HTTP {resp.status_code}")
    except Exception as exc:
        print(f"Adzuna p{page} error: {exc}")
    return []
 
 
def _normalise_adzuna(job: dict, city: str) -> dict:
    """Convert a raw Adzuna result to the common internal format."""
    desc = job.get("description") or ""
    return {
        "job_title":                    job.get("title")                or "",
        "employer_name":                (job.get("company") or {}).get("display_name", "") or "",
        "employer_logo":                "",
        "job_city":                     (job.get("location") or {}).get("display_name", city),
        "job_apply_link":               job.get("redirect_url")         or "#",
        "job_description":              desc,
        "job_posted_at_datetime_utc":   job.get("created")              or "",
        "job_employment_type":          "Internship",
        "job_publisher":                "Adzuna",
        "qualifications":               [],
        "_source":                      "adzuna",
    }
 
 
# ─────────────────────────────────────────────────────────────────────────────
#  SCORING — runs in ThreadPoolExecutor, never blocks event loop
# ─────────────────────────────────────────────────────────────────────────────
 
def _score_job(
    job_raw: dict,
    city: str,
    user_skills_list: list,
    user_profile_struct: dict,
    resume_text: str,
) -> dict:
    from app.services.skill_extractor import extract_skills as ext_sk
    from app.services.scoring_model import semantic_similarity, gap_severity as gap_sev_fn
 
    title           = job_raw.get("job_title")                  or ""
    employer        = job_raw.get("employer_name")               or ""
    employer_logo   = job_raw.get("employer_logo")               or ""
    location        = job_raw.get("job_city")                    or city
    apply_link      = job_raw.get("job_apply_link")              or "#"
    description     = job_raw.get("job_description")            or ""
    posted_at       = job_raw.get("job_posted_at_datetime_utc") or ""
    employment_type = job_raw.get("job_employment_type")         or "Internship"
    publisher       = job_raw.get("job_publisher")               or ""
    req_skills      = job_raw.get("qualifications")              or []
 
    match_score = 0
    gap_sev     = "N/A"
    missing: dict = {}
 
    if user_skills_list:
        job_text_blob    = f"{title} {' '.join(req_skills)} {description[:3000]}"
        job_text_scoring = f"{title} {' '.join(req_skills)} {description[:800]}"
 
        job_skills_extracted = ext_sk(job_text_blob)
 
        job_profile: dict = {"technical": [], "tools": [], "soft": []}
        for js in job_skills_extracted:
            sk_type = (js.get("skill_type") or "technical").lower()
            bucket  = ("tools"     if sk_type in ("tool", "tools") else
                       "soft"      if sk_type == "soft" else
                       "technical")
            name = js["skill_name"]
            if name not in job_profile[bucket]:
                job_profile[bucket].append(name)
 
        total_job_skills = sum(len(v) for v in job_profile.values())
 
        try:
            if total_job_skills == 0:
                match_score = round(semantic_similarity(resume_text, job_text_scoring), 1)
                gap_sev     = gap_sev_fn(match_score)
            else:
                result = run_matching_pipeline(
                    user_profile=user_profile_struct,
                    job_profile=job_profile,
                    resume_text=resume_text,
                    job_text=job_text_scoring,
                )
                match_score = result["final_match_score"]
                gap_sev     = result["gap_severity"]
                missing     = {
                    cat: skls
                    for cat, skls in result["missing_skills"].items()
                    if skls
                }
        except Exception as exc:
            print(f"Scoring error: {exc}")
 
    return {
        "title":           title,
        "employer":        employer,
        "employer_logo":   employer_logo,
        "location":        location,
        "apply_link":      apply_link,
        "posted_at":       posted_at,
        "employment_type": employment_type,
        "publisher":       publisher,
        "qualifications":  req_skills,
        "match_score":     round(match_score, 1),
        "gap_severity":    gap_sev,
        "missing_skills":  missing,
        "has_profile":     bool(user_skills_list),
    }
 
 
# ─────────────────────────────────────────────────────────────────────────────
#  MAIN ENDPOINT
# ─────────────────────────────────────────────────────────────────────────────
 
@app.get("/api/internships")
async def get_internships(
    request:     Request,
    city:        str     = "Mumbai",
    date_filter: str     = "3days",
    domain:      str     = "",
    db:          Session = Depends(get_db),
):
    from app.models import UserSkills, Skills, UserProfile
 
    # ── 1. Load user profile ──────────────────────────────────────────────────
    user_id                 = request.session.get("user_id")
    user_skills_list: list  = []
    user_profile_struct     = {"technical": [], "tools": [], "soft": []}
    resume_text             = ""
    profile_domain_interest = ""
 
    if user_id:
        try:
            skills_raw = (
                db.query(Skills.skill_name, Skills.skill_type)
                .join(UserSkills, Skills.skill_id == UserSkills.skill_id)
                .filter(UserSkills.user_id == user_id)
                .all()
            )
            for sname, stype in skills_raw:
                user_skills_list.append(sname)
                sk_t   = (stype or "").lower()
                bucket = ("tools"     if sk_t in ("tool", "tools") else
                          "soft"      if sk_t == "soft" else
                          "technical")
                user_profile_struct[bucket].append(sname)
            resume_text = " ".join(user_skills_list)
 
            prof = db.query(UserProfile).filter(
                UserProfile.user_id == user_id
            ).first()
            if prof and prof.domain_interest:
                profile_domain_interest = prof.domain_interest
        except Exception as exc:
            print(f"Profile load error: {exc}")
 
    # ── 2. Resolve domain keyword ─────────────────────────────────────────────
    domain_key = (domain or "").strip().lower()
    domain_kw  = DOMAIN_KEYWORDS.get(domain_key, "")
    if not domain_kw and not domain_key and profile_domain_interest:
        domain_kw = profile_domain_interest
 
    # ── 3. Build queries and page counts ─────────────────────────────────────
    date_posted = {"3days": "3days", "week": "week", "month": "month"}.get(
                  date_filter, "3days")
    num_pages   = _PAGES_BY_FILTER.get(date_filter, 10)
 
    # Two query variants per source — domain-specific + broad fallback
    if domain_kw:
        q_domain = f"{domain_kw} internship in {city}"
        q_intern = f"{domain_kw} intern {city}"
    else:
        q_domain = f"internship in {city}"
        q_intern = f"intern {city}"
    q_broad   = f"internship in {city}"
    q_fresher = f"fresher jobs in {city}"
 
    half = max(1, num_pages // 2)
 
    # ── 4. Fetch from ALL sources concurrently ────────────────────────────────
    raw_jobs: list = []
 
    async with httpx.AsyncClient(timeout=20) as client:
        fetch_tasks = []
 
        # JSearch tasks (if key configured)
        if JSEARCH_API_KEY:
            for p in range(1, num_pages + 1):
                fetch_tasks.append(_fetch_jsearch_page(client, q_domain, p, date_posted))
                fetch_tasks.append(_fetch_jsearch_page(client, q_broad,  p, date_posted))
            for p in range(1, half + 1):
                fetch_tasks.append(_fetch_jsearch_page(client, q_intern,  p, date_posted))
                fetch_tasks.append(_fetch_jsearch_page(client, q_fresher, p, date_posted))
 
        # Adzuna tasks (if keys configured — already in .env)
        if ADZUNA_APP_ID and ADZUNA_KEY:
            adzuna_kw = domain_kw or "internship"
            for p in range(1, num_pages + 1):
                fetch_tasks.append(_fetch_adzuna_page(client, adzuna_kw, city, p))
            for p in range(1, half + 1):
                fetch_tasks.append(_fetch_adzuna_page(client, "internship", city, p))
 
        if not fetch_tasks:
            return {"jobs": [], "total": 0, "city": city, "cities": INDIAN_CITIES,
                    "error": "No API keys configured. Add JSEARCH_API_KEY or ADZUNA_APP_ID to .env"}
 
        page_results = await asyncio.gather(*fetch_tasks, return_exceptions=True)
 
        for pr in page_results:
            if isinstance(pr, list):
                # Normalise JSearch raw dicts that haven't been normalised yet
                for item in pr:
                    if isinstance(item, dict):
                        if "_source" not in item:
                            raw_jobs.append(_normalise_jsearch(item, city))
                        else:
                            raw_jobs.append(item)
 
    # ── 5. Deduplicate by apply_link ──────────────────────────────────────────
    seen_links: set   = set()
    unique_jobs: list = []
    for job in raw_jobs:
        key = job.get("job_apply_link") or ""
        if not key or key not in seen_links:
            if key:
                seen_links.add(key)
            unique_jobs.append(job)
 
    # ── 6. Domain relevance filter ────────────────────────────────────────────
    if domain_key and domain_key in DOMAIN_TITLE_KEYWORDS:
        title_kws = DOMAIN_TITLE_KEYWORDS[domain_key]
 
        def _is_relevant(j: dict) -> bool:
            title = (j.get("job_title") or "").lower()
            desc  = (j.get("job_description") or "")[:400].lower()
            return any(kw in title + " " + desc for kw in title_kws)
 
        filtered = [j for j in unique_jobs if _is_relevant(j)]
        # Safety net: keep unfiltered if domain filter is too aggressive
        unique_jobs = filtered if len(filtered) >= 20 else unique_jobs
 
    # ── 7. Score all jobs in parallel (CPU work in thread pool) ──────────────
    loop = asyncio.get_event_loop()
    score_futures = [
        loop.run_in_executor(
            _SCORE_EXECUTOR,
            _score_job,
            job, city, user_skills_list, user_profile_struct, resume_text,
        )
        for job in unique_jobs
    ]
    results: list = list(await asyncio.gather(*score_futures))
 
    # ── 8. Sort ───────────────────────────────────────────────────────────────
    if user_skills_list:
        results.sort(key=lambda x: x["match_score"], reverse=True)
    else:
        results.sort(key=lambda x: x.get("posted_at") or "", reverse=True)
 
    return {
        "jobs":   results,
        "total":  len(results),
        "city":   city,
        "cities": INDIAN_CITIES,
    }