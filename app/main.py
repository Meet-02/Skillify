from fastapi import FastAPI
from app.routes import auth,match

app = FastAPI(title="Skillify API")

app.include_router(auth.router, prefix="/auth", tags=["Authentication"])
app.include_router(match.router, prefix="/match", tags=["Matching"])
