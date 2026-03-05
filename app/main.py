import shutil
from pathlib import Path
from datetime import datetime

from fastapi import FastAPI, Request, Form, Depends, UploadFile, File
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from app.database import engine, get_db
from app.models import Base, Login
from app.core.utils import hash_password, verify_password
from app.services.resume_parser import extract_text_from_resume
from app.services.skill_extractor import extract_skills
from app.services.match_service import run_matching_pipeline
from app.services.bio_generator import generate_bio
from app.routes import auth, match
from experiment.alpha_dataset import DATASET as JOB_DATASET

PROJECT_ROOT = Path(__file__).resolve().parent.parent

app = FastAPI(title="Skillify API")

app.add_middleware(
    SessionMiddleware,
    secret_key="skillify-session-secret"
)

Base.metadata.create_all(bind=engine)

static_dir = PROJECT_ROOT / "static"
templates_dir = PROJECT_ROOT / "templates"

app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
templates = Jinja2Templates(directory=str(templates_dir))


app.include_router(auth.router, prefix="/auth")
app.include_router(match.router, prefix="/match")


@app.get("/")
def landing_page(request: Request):
    return templates.TemplateResponse(
        "landing-page.html",
        {"request": request}
    )

@app.get("/register")
def register_page(request: Request):
    return templates.TemplateResponse(
        "register.html",
        {"request": request}
    )

@app.post("/register")
def register_user(
        request: Request,
        username: str = Form(...),
        email: str = Form(...),
        password: str = Form(...),
        db: Session = Depends(get_db),
):

    from app.models import Login, Users

    existing = db.query(Login).filter(
        Login.email == email
    ).first()

    if existing:
        return templates.TemplateResponse(
            "register.html",
            {
                "request": request,
                "error": "Email already registered"
            }
        )

    hashed = hash_password(password)

    login_user = Login(
        username=username,
        email=email,
        password_hash=hashed,
        created_at=datetime.utcnow()
    )

    db.add(login_user)
    db.commit()

    new_user = Users(
        name=username,
        email=email,
        password_hash=hashed,
        role="student",
        created_at=datetime.utcnow()
    )

    db.add(new_user)
    db.commit()

    return RedirectResponse("/login", status_code=303)

@app.get("/login")
def login_page(request: Request):
    return templates.TemplateResponse(
        "login.html",
        {"request": request}
    )


@app.post("/login")
def login_user(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
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

    # Get Users table record
    profile_user = db.query(Users).filter(
        Users.email == email
    ).first()

    if not profile_user:
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "User profile missing"},
        )

    request.session["user_id"] = profile_user.user_id

    # ✅ Check if resume already uploaded
    skills_exist = db.query(UserSkills).filter(
        UserSkills.user_id == profile_user.user_id
    ).first()

    if skills_exist:
        return RedirectResponse("/profile", status_code=303)

    return RedirectResponse("/upload-resume", status_code=303)

@app.get("/logout")
def logout(request: Request):

    request.session.clear()

    return RedirectResponse("/login", status_code=303)

@app.get("/profile")
def profile_page(
        request: Request,
        db: Session = Depends(get_db)
):

    from app.models import Users, UserProfile, UserSkills, Skills

    user_id = request.session.get("user_id")

    if not user_id:
        return RedirectResponse("/login", status_code=303)

    user = db.query(Users).filter(
        Users.user_id == user_id
    ).first()

    if not user:
        return RedirectResponse("/login", status_code=303)

    profile = db.query(UserProfile).filter(
        UserProfile.user_id == user_id
    ).first()

    skills = (
        db.query(Skills.skill_name, Skills.skill_type)
        .join(UserSkills, Skills.skill_id == UserSkills.skill_id)
        .filter(UserSkills.user_id == user_id)
        .all()
    )

    skill_list = [s[0] for s in skills]

    resume_uploaded = len(skill_list) > 0
    skills_count = len(skill_list)

    # Try to infer the latest uploaded resume filename for display
    resume_filename = None
    if resume_uploaded:
        upload_dir = static_dir / "resumes"
        if upload_dir.exists():
            prefix = f"{user_id}_"
            user_files = sorted(
                [
                    p
                    for p in upload_dir.iterdir()
                    if p.is_file() and p.name.startswith(prefix)
                ],
                key=lambda p: p.stat().st_mtime,
            )
            if user_files:
                latest_resume = user_files[-1]
                name_parts = latest_resume.name.split("_", 1)
                resume_filename = name_parts[1] if len(name_parts) == 2 else latest_resume.name

    matched_services = []
    no_skills_message = None

    if skill_list:
        # Build user profile structure expected by the matching pipeline
        user_profile = {
            "technical": [],
            "tools": [],
            "soft": [],
        }

        for skill_name, skill_type in skills:
            key = (skill_type or "").lower()
            if key in user_profile:
                user_profile[key].append(skill_name)

        # Fallback: if no types mapped, treat all skills as technical
        if not any(user_profile.values()):
            user_profile["technical"] = skill_list

        # We do not persist full resume text; approximate using skills
        resume_text = " ".join(skill_list)

        for job in JOB_DATASET:
            result = run_matching_pipeline(
                user_profile=user_profile,
                job_profile=job["job_profile"],
                resume_text=resume_text,
                job_text=job["job_title"],
            )
            matched_services.append(
                {
                    "job_title": job["job_title"],
                    "final_match_score": result["final_match_score"],
                    "structured_score": result["structured_score"],
                    "semantic_score": result["semantic_score"],
                    "gap_severity": result["gap_severity"],
                }
            )

        matched_services.sort(key=lambda s: s["final_match_score"], reverse=True)
    else:
        no_skills_message = "Upload resume to see recommendations"

    return templates.TemplateResponse(
        "profile.html",
        {
            "request": request,
            "user": user,
            "profile": profile,
            "skills": skill_list,
            "skills_count": skills_count,
            "resume_uploaded": resume_uploaded,
            "resume_filename": resume_filename,
            "matched_services": matched_services,
            "no_skills_message": no_skills_message,
        }
    )


@app.post("/profile")
def update_profile(
        request: Request,
        phone: str = Form(None),
        bio: str = Form(None),
        education: str = Form(None),
        experience_level: str = Form(None),
        domain_interest: str = Form(None),
        db: Session = Depends(get_db),
):

    from app.models import Users, UserProfile

    user_id = request.session.get("user_id")

    if not user_id:
        return RedirectResponse("/login", status_code=303)

    user = db.query(Users).filter(
        Users.user_id == user_id
    ).first()

    if not user:
        return RedirectResponse("/login", status_code=303)

    if phone is not None and phone.strip() != "":
        user.phone = phone.strip()

    if bio is not None and bio.strip() != "":
        user.bio = bio.strip()

    profile = db.query(UserProfile).filter(
        UserProfile.user_id == user_id
    ).first()

    if not profile:
        profile = UserProfile(user_id=user_id)
        db.add(profile)

    if education is not None and education.strip() != "":
        profile.education = education.strip()

    if experience_level is not None and experience_level.strip() != "":
        profile.experience_level = experience_level.strip()

    if domain_interest is not None and domain_interest.strip() != "":
        profile.domain_interest = domain_interest.strip()


    score = 0
    if user.phone:
        score += 20
    if user.bio:
        score += 20
    if profile.education:
        score += 20
    if profile.experience_level:
        score += 20
    if profile.domain_interest:
        score += 20

    profile.profile_completion_score = score

    db.commit()

    return RedirectResponse("/profile", status_code=303)


@app.get("/upload-resume")
def upload_resume_page(request: Request):

    if not request.session.get("user_id"):
        return RedirectResponse("/login", status_code=303)

    return templates.TemplateResponse(
        "upload_resume.html",
        {"request": request}
    )


@app.post("/upload-resume")
async def upload_resume(
        request: Request,
        resume: UploadFile = File(...),
        db: Session = Depends(get_db),
):

    from app.models import Users, Skills, UserSkills

    user_id = request.session.get("user_id")

    if not user_id:
        return RedirectResponse("/login", status_code=303)

    user = db.query(Users).filter(
        Users.user_id == user_id
    ).first()

    if not user:
        return RedirectResponse("/login", status_code=303)

    upload_dir = static_dir / "resumes"
    upload_dir.mkdir(parents=True, exist_ok=True)

    file_path = upload_dir / f"{user_id}_resume.pdf"

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(resume.file, buffer)

    try:
        text = extract_text_from_resume(str(file_path))
        extracted = extract_skills(text)

        user.resume_filename = f"{user_id}_resume.pdf"

        user.resume_uploaded = True

        if not user.bio or not user.bio.strip():
            generated_bio = generate_bio(extracted)
            if generated_bio:
                user.bio = generated_bio.strip()

        db.commit()

    except Exception as e:
        print("Resume Error:", e)
        return templates.TemplateResponse(
            "upload_resume.html",
            {
                "request": request,
                "error": "Resume parsing failed"
            }
        )

    db.query(UserSkills).filter(
        UserSkills.user_id == user_id,
        UserSkills.source == "resume"
    ).delete()

    db.commit()

    for skill in extracted:
        skill_name = skill["skill_name"]

        skill_obj = db.query(Skills).filter(
            Skills.skill_name == skill_name
        ).first()

        if not skill_obj:
            skill_obj = Skills(
                skill_name=skill_name,
                skill_type=skill["skill_type"]
            )
            db.add(skill_obj)
            db.commit()
            db.refresh(skill_obj)

        user_skill = UserSkills(
            user_id=user_id,
            skill_id=skill_obj.skill_id,
            proficiency_level="beginner",
            source="resume"
        )

        db.add(user_skill)

    db.commit()

    return RedirectResponse("/profile", status_code=303)