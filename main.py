from fastapi import FastAPI
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request
from fastapi.staticfiles import StaticFiles
import schemas
from sqlalchemy.orm import Session
import models
from database import engine, SessionLocal
from fastapi import Form, Depends, UploadFile, File
from fastapi.responses import RedirectResponse
import shutil
import os
from utils import hash_password,verify_password
from starlette.middleware.sessions import SessionMiddleware 


app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key="some-random-secret-string")
models.Base.metadata.create_all(bind=engine)

def get_db(): 
    db = SessionLocal() 
    try: 
        yield db
    finally:
        db.close()
print("STATIC PATH =", os.path.abspath("static"))

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

@app.get("/")
def landing_page(request: Request):
    return templates.TemplateResponse("landing-page.html", {"request": request})

@app.get("/register")
def register(request: Request):
    return templates.TemplateResponse('register.html',{"request":request})

@app.post("/register")
def register_user(
    request: Request,
    fullname: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):

    existing_user = db.query(models.User).filter(models.User.email == email).first()

    if existing_user:
        return templates.TemplateResponse("register.html", {
            "request": request,
            "error": "Email already registered"
        })

    hashed_pw = hash_password(password)

    user = models.User(
        fullname=fullname,
        email=email,
        hashed_password=hashed_pw
    )

    db.add(user)
    db.commit()
    db.refresh(user)

    return RedirectResponse("/login", status_code=303)

@app.get("/login")
def login(request: Request):
    return templates.TemplateResponse('login.html',{"request":request})

@app.post('/login')
def login_user(
    request:Request,
    email:str = Form(...),
    password:str = Form(...),
    db:Session = Depends(get_db)
):
    user = db.query(models.User).filter(models.User.email == email).first()

    if not user:
        return templates.TemplateResponse("login.html", {
            "request": request,
            "error": "User not found"
        })

    if not verify_password(password, user.hashed_password):
        return templates.TemplateResponse("login.html", {
            "request": request,
            "error": "Invalid password"
        })
    request.session['user_id'] = user.id
    return RedirectResponse("/upload-resume", status_code=303)

@app.get("/profile")
def profile(request: Request, db: Session = Depends(get_db)):
    

    user_id = request.session.get("user_id")

    if not user_id:

        return RedirectResponse("/login")


    user = db.query(models.User).filter(models.User.id == user_id).first()

    return templates.TemplateResponse("profile.html", {
        "request": request,
        "user": user
    })

@app.get("/logout")
def logout(requets:Request):
    return RedirectResponse("/login",status_code=303)

@app.get("/upload-resume")
def upload_resume_page(request: Request):
    user_id = request.session.get("user_id")

    if not user_id:
        return RedirectResponse("/login", status_code=303)

    return templates.TemplateResponse("upload_resume.html", {"request": request})

@app.post("/upload-resume")
async def upload_resume(
    request: Request,
    resume: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    user_id = request.session.get("user_id")

    if not user_id:
        return RedirectResponse("/login", status_code=303)

    user = db.query(models.User).filter(models.User.id == user_id).first()

    if not user:
        return RedirectResponse("/login", status_code=303)


    upload_dir = os.path.join("static", "resumes")
    os.makedirs(upload_dir, exist_ok=True)


    filename = f"{user_id}_{resume.filename}"
    file_path = os.path.join(upload_dir, filename)

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(resume.file, buffer)


    user.resume_filename = filename
    db.commit()
    db.refresh(user)

    return RedirectResponse("/profile", status_code=303)
