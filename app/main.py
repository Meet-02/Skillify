import shutil
from pathlib import Path

from fastapi import FastAPI, Request, Form, Depends, UploadFile, File
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from app.database import engine, get_db
from app.models import Base,Login
from app.core.utils import hash_password, verify_password
from app.services.resume_parser import extract_text_from_resume
from app.services.skill_extractor import extract_skills
from app.routes import auth, match

# Project root (parent of app/) for static and templates
PROJECT_ROOT = Path(__file__).resolve().parent.parent

app = FastAPI(title="Skillify API")
app.add_middleware(SessionMiddleware, secret_key="skillify-session-secret")

# Database
Base.metadata.create_all(bind=engine)

# Static and templates (paths valid regardless of cwd)
static_dir = PROJECT_ROOT / "static"
templates_dir = PROJECT_ROOT / "templates"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
templates = Jinja2Templates(directory=str(templates_dir))

# API routers
app.include_router(auth.router, prefix="/auth", tags=["Authentication"])
app.include_router(match.router, prefix="/match", tags=["Matching"])


# ---------- Template (Jinja2) routes ----------

@app.get("/")
def landing_page(request: Request):
    return templates.TemplateResponse("landing-page.html", {"request": request})


@app.get("/register")
def register_page(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})


@app.post("/register")
def register_user(
    request: Request,
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):

    existing_email = db.query(Login).filter(Login.email == email).first()

    if existing_email:
        return templates.TemplateResponse(
            "register.html",
            {"request": request, "error": "Email already registered"},
        )

    existing_username = db.query(Login).filter(Login.username == username).first()

    if existing_username:
        return templates.TemplateResponse(
            "register.html",
            {"request": request, "error": "Username already exists"},
        )

    user = Login(
        username=username,
        email=email,
        password_hash=hash_password(password),
        created_at=datetime.utcnow()
    )

    db.add(user)
    db.commit()

    return RedirectResponse("/login", status_code=303)

@app.get("/login")
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@app.post("/login")
def login_user(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):

    from app.models import Login

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

    request.session["user_id"] = user.id

    return RedirectResponse("/upload-resume", status_code=303)

@app.get("/logout")
def logout(request: Request):
    return RedirectResponse("/login", status_code=303)


@app.get("/profile")
def profile_page(request: Request, db: Session = Depends(get_db)):
    from app.models import User

    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse("/login", status_code=303)
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return RedirectResponse("/login", status_code=303)
    extracted_skills = request.session.get("extracted_skills") or []
    return templates.TemplateResponse(
        "profile.html",
        {"request": request, "user": user, "extracted_skills": extracted_skills},
    )


@app.get("/upload-resume")
def upload_resume_page(request: Request):
    if not request.session.get("user_id"):
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse("upload_resume.html", {"request": request})


@app.post("/upload-resume")
async def upload_resume(
    request: Request,
    resume: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    from app.models import User

    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse("/login", status_code=303)
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return RedirectResponse("/login", status_code=303)

    upload_dir = static_dir / "resumes"
    upload_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{user_id}_{resume.filename}"
    file_path = upload_dir / filename

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(resume.file, buffer)

    # Connect services: extract text and skills
    try:
        resume_text = extract_text_from_resume(str(file_path))
        extracted_skills = extract_skills(resume_text)
        request.session["extracted_skills"] = [
            {"skill_name": s["skill_name"], "skill_type": s["skill_type"]}
            for s in extracted_skills
        ]
    except Exception:
        request.session["extracted_skills"] = []

    user.resume_filename = filename
    db.commit()
    db.refresh(user)

    return RedirectResponse("/profile", status_code=303)
