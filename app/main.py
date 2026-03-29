import shutil
from pathlib import Path
from datetime import datetime
import os
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Form, Depends, UploadFile, File, HTTPException
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
 
DOMAIN_KEYWORDS: dict[str, str] = {
    "":           "",
    "frontend":   "Frontend",
    "backend":    "Backend",
    "fullstack":  "Full Stack",
    "android":    "Android",
    "ios":        "iOS",
    "devops":     "DevOps",
    "data":       "Data Science",
    "ml":         "Machine Learning",
    "dataeng":    "Data Engineering",
    "cyber":      "Cyber Security",
    "uiux":       "UI UX Design",
    "embedded":   "Embedded Systems",
    "blockchain": "Blockchain",
    "qa":         "QA Testing",
    "software":   "Software Engineering",
    "product":    "Product Management",
    "marketing":  "Marketing",
    "finance":    "Finance",
    "hr":         "Human Resources",
    "sales":      "Sales",
    "operations": "Operations",
    "content":    "Content Writing",
    "design":     "Graphic Design",
}

INDIAN_CITIES = [
    "Mumbai", "Delhi", "Bangalore", "Hyderabad", "Chennai",
    "Pune", "Kolkata", "Ahmedabad", "Jaipur", "Surat",
    "Lucknow", "Noida", "Gurugram", "Indore", "Bhopal",
]

@app.get("/api/internships")
async def get_internships(
    request: Request,
    city: str = "Mumbai",
    date_filter: str = "month",
    domain: str = "",
    db: Session = Depends(get_db),
):
    from app.services.job_scraper_service import aggregate_jobs
    from app.models import UserSkills, Skills, UserProfile

    print(f"\n{'='*60}")
    print(f"📥 /api/internships called | city={city!r} domain={domain!r} date_filter={date_filter!r}")
    print(f"{'='*60}")

    user_id = request.session.get("user_id")
    print(f"  🔑 user_id = {user_id}")

    # ---------------- USER PROFILE ----------------
    user_skills_list = []
    user_profile_struct = {"technical": [], "tools": [], "soft": []}
    resume_text = ""

    if user_id:
        skills_raw = (
            db.query(Skills.skill_name, Skills.skill_type)
            .join(UserSkills, Skills.skill_id == UserSkills.skill_id)
            .filter(UserSkills.user_id == user_id)
            .all()
        )
        print(f"  📋 Found {len(skills_raw)} user skills in DB")

        for sname, stype in skills_raw:
            user_skills_list.append(sname)
            sk_t = (stype or "").lower()
            bucket = (
                "tools" if sk_t in ("tool", "tools")
                else "soft" if sk_t == "soft"
                else "technical"
            )
            user_profile_struct[bucket].append(sname)

        resume_text = " ".join(user_skills_list)
        print(f"  📋 User profile: tech={len(user_profile_struct['technical'])} tools={len(user_profile_struct['tools'])} soft={len(user_profile_struct['soft'])}")
    else:
        print("  ⚠️  No user_id in session — scoring will be 0% for all jobs")

    # ---------------- CALL UNIFIED PIPELINE ----------------
    print(f"\n  ⏳ Calling aggregate_jobs() ...")
    import time as _time
    _t0 = _time.time()

    result = await aggregate_jobs(
        domain       = domain,
        city         = city,
        user_profile = user_profile_struct,
        resume_text  = resume_text,
        sources      = ["internshala", "indeed", "jsearch"],
        date_filter  = date_filter,
    )

    _elapsed = _time.time() - _t0
    print(f"  ✅ aggregate_jobs() returned in {_elapsed:.1f}s — {result.get('total', 0)} jobs")

    # ---------------- RESHAPE FOR FRONTEND ----------------
    jobs = result.get("jobs", [])
    print(f"  🔄 Reshaping {len(jobs)} jobs for frontend (has_profile={bool(user_skills_list)})")
    for job in jobs:
        # Add has_profile flag for the frontend UI
        job["has_profile"] = bool(user_skills_list)
        # Strip heavy fields
        job.pop("description", None)
        # Cap skills shown
        if isinstance(job.get("skills"), list):
            job["skills"] = job["skills"][:12]

    print(f"  📤 Returning {len(jobs)} jobs to frontend")
    print(f"{'='*60}\n")

    return {
        "jobs":  jobs,
        "total": result.get("total", 0),
        "city":  city,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Unified Jobs API  (Internshala + Indeed + JSearch — parallel)
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/jobs")
async def get_jobs_unified(
    request:     Request,
    city:        str = "Mumbai",
    domain:      str = "",
    date_filter: str = "month",
    sources:     str = "internshala,indeed,jsearch",   # comma-separated
    db:          Session = Depends(get_db),
):
    """
    Parallel job aggregator endpoint.

    Query params:
      city     — e.g. Mumbai, Delhi, Bangalore
      domain   — e.g. android, backend, fullstack  (see DOMAIN_KEYWORDS)
      sources  — comma list of: internshala, indeed, jsearch

    Returns jobs sorted by match_score descending.
    Caches results to CSV in tmp/jobs_cache/.
    """
    from app.services.job_scraper_service import aggregate_jobs
    from app.models import UserSkills, Skills, UserProfile

    user_id = request.session.get("user_id")

    # Build user profile for scoring
    user_profile_struct = {"technical": [], "tools": [], "soft": []}
    resume_text = ""

    if user_id:
        skills_raw = (
            db.query(Skills.skill_name, Skills.skill_type)
            .join(UserSkills, Skills.skill_id == UserSkills.skill_id)
            .filter(UserSkills.user_id == user_id)
            .all()
        )
        for sname, stype in skills_raw:
            sk_t   = (stype or "").lower()
            bucket = (
                "tools"     if sk_t in ("tool", "tools") else
                "soft"      if sk_t == "soft"             else
                "technical"
            )
            user_profile_struct[bucket].append(sname)
        resume_text = " ".join(
            user_profile_struct["technical"] +
            user_profile_struct["tools"] +
            user_profile_struct["soft"]
        )

    # Parse sources list
    source_list = [s.strip().lower() for s in sources.split(",") if s.strip()]

    result = await aggregate_jobs(
        domain       = domain,
        city         = city,
        user_profile = user_profile_struct,
        resume_text  = resume_text,
        sources      = source_list,
        date_filter  = date_filter,
    )

    # Strip heavy fields before sending to frontend
    for job in result["jobs"]:
        job.pop("description", None)
        job.pop("missing_skills", None)
        if isinstance(job.get("skills"), list):
            job["skills"] = job["skills"][:12]   # cap skills shown

    return {
        "jobs":        result["jobs"],
        "total":       result["total"],
        "csv_path":    result["csv_path"],
        "sources_hit": result["sources_hit"],
        "city":        city,
        "domain":      domain,
    }
